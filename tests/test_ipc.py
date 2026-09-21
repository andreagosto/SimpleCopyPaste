"""IPC protocol tests over a real Unix socket in a temp runtime dir."""

from __future__ import annotations

import threading
import time

import pytest

from simpleclips import config, ipc


def test_send_and_receive():
    server = ipc.Server(lambda req: {"ok": True, "echo": req.get("cmd")})
    server.start()
    try:
        assert ipc.send({"cmd": "ping"})["echo"] == "ping"
        assert ipc.is_alive()
    finally:
        server.stop()


def test_server_reports_handler_errors_without_dying():
    def handler(request):
        if request.get("cmd") == "boom":
            raise RuntimeError("nope")
        return {"ok": True}

    server = ipc.Server(handler)
    server.start()
    try:
        assert ipc.send({"cmd": "boom"})["ok"] is False
        assert ipc.send({"cmd": "fine"})["ok"] is True
    finally:
        server.stop()


def test_is_alive_false_when_no_socket():
    assert not ipc.is_alive()


def test_second_daemon_refuses_to_start():
    first = ipc.Server(lambda req: {"ok": True})
    first.start()
    second = ipc.Server(lambda req: {"ok": True})
    try:
        with pytest.raises(ipc.CommandError):
            second.start()
    finally:
        first.stop()


def test_lock_is_released_after_stop():
    first = ipc.Server(lambda req: {"ok": True})
    first.start()
    first.stop()
    # a fresh daemon can take over once the first has stopped
    second = ipc.Server(lambda req: {"ok": True})
    second.start()
    try:
        assert ipc.is_alive()
    finally:
        second.stop()


def test_stopping_an_unstarted_server_keeps_the_running_socket():
    running = ipc.Server(lambda req: {"ok": True})
    running.start()
    try:
        idle = ipc.Server(lambda req: {"ok": True})
        idle.stop()  # never started: must be a no-op
        assert ipc.is_alive()
    finally:
        running.stop()
