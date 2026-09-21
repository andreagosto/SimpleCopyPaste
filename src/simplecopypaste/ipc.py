"""Tiny newline-delimited JSON protocol over a Unix socket."""

from __future__ import annotations

import fcntl
import json
import os
import socket
import threading
from typing import Callable

from . import config

MAX_MSG = 4 * 1024 * 1024


class CommandError(RuntimeError):
    pass


def send(payload: dict, timeout: float = 3.0) -> dict:
    """Send a command to a running daemon. Raises on connection failure."""
    path = str(config.socket_file())
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        sock.connect(path)
        sock.sendall((json.dumps(payload) + "\n").encode("utf-8"))
        data = _read_line(sock)
    try:
        return json.loads(data) if data else {}
    except ValueError:
        return {}


def is_alive() -> bool:
    path = config.socket_file()
    if not path.exists():
        return False
    try:
        send({"cmd": "ping"}, timeout=1.0)
        return True
    except (OSError, CommandError):
        return False


class Server:
    """Background Unix-socket server dispatching to a callback.

    The callback is invoked on the server thread and must return a JSON
    serialisable dict. Callers that need the GTK thread should marshal
    with GLib.idle_add inside the callback.
    """

    def __init__(self, handler: Callable[[dict], dict]) -> None:
        self.handler = handler
        self.path = config.socket_file()
        self._sock: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock_file = None

    def start(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._acquire_lock()
        # The lock proves we are the only daemon, so any socket file left
        # behind is stale and safe to replace.
        if self.path.exists():
            self.path.unlink(missing_ok=True)
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.bind(str(self.path))
        os.chmod(self.path, 0o600)
        self._sock.listen(8)
        self._stop.clear()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _acquire_lock(self) -> None:
        """Take an exclusive lock so only one daemon can ever run.

        The kernel releases it when the process dies, so a crash never
        leaves a stuck lock. Without this, a daemon started while the
        service was briefly down could linger and share the socket path.
        """
        lock_path = self.path.with_suffix(".lock")
        self._lock_file = open(lock_path, "w")
        try:
            fcntl.flock(self._lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self._lock_file.close()
            self._lock_file = None
            raise CommandError("another simplecopypaste daemon is already running")

    def _serve(self) -> None:
        assert self._sock is not None
        while not self._stop.is_set():
            try:
                conn, _ = self._sock.accept()
            except OSError:
                break
            with conn:
                try:
                    data = _read_line(conn)
                    request = json.loads(data) if data else {}
                    if not isinstance(request, dict):
                        response = {"ok": False, "error": "bad request"}
                    else:
                        response = self.handler(request)
                except Exception as exc:  # keep the daemon alive
                    response = {"ok": False, "error": str(exc)}
                try:
                    conn.sendall((json.dumps(response) + "\n").encode("utf-8"))
                except OSError:
                    pass

    def stop(self) -> None:
        self._stop.set()
        # Only tear down the socket if this instance actually created it;
        # a daemon that never started must not delete a running one's file.
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
            self.path.unlink(missing_ok=True)
        if self._lock_file is not None:
            try:
                fcntl.flock(self._lock_file, fcntl.LOCK_UN)
            except OSError:
                pass
            self._lock_file.close()
            self._lock_file = None


def _read_line(sock: socket.socket) -> str:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = sock.recv(65536)
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_MSG:
            raise CommandError("message too large")
        if b"\n" in chunk:
            chunks.append(chunk.split(b"\n", 1)[0])
            break
        chunks.append(chunk)
    return b"".join(chunks).decode("utf-8", "replace")
