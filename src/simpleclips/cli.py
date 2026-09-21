"""Command line entry point."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time

from . import __version__, ipc

HOTKEY_DEFAULT = "<Super><Alt>v"


def _spawn_daemon() -> bool:
    """Start the daemon detached and wait for its socket."""
    exe = shutil.which("simpleclips")
    argv = (
        [exe, "daemon"]
        if exe
        else [sys.executable, "-m", "simpleclips", "daemon"]
    )
    try:
        subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as exc:
        print(f"could not start daemon: {exc}", file=sys.stderr)
        return False
    for _ in range(40):
        if ipc.is_alive():
            return True
        time.sleep(0.05)
    return False


def _ensure_daemon() -> bool:
    if ipc.is_alive():
        return True
    return _spawn_daemon()


def _send(cmd: str) -> int:
    try:
        reply = ipc.send({"cmd": cmd})
    except OSError as exc:
        print(f"simpleclips is not running ({exc})", file=sys.stderr)
        return 1
    if not reply.get("ok"):
        print(f"error: {reply.get('error', 'unknown')}", file=sys.stderr)
        return 1
    return 0


def cmd_toggle(_args) -> int:
    if not _ensure_daemon():
        print("could not reach or start the simpleclips daemon", file=sys.stderr)
        return 1
    return _send("toggle")


def cmd_show(_args) -> int:
    if not _ensure_daemon():
        return 1
    return _send("show")


def cmd_hide(_args) -> int:
    return _send("hide")


def cmd_status(_args) -> int:
    if not ipc.is_alive():
        print("simpleclips: not running")
        return 1
    reply = ipc.send({"cmd": "status"})
    print(f"clipboard backend : {reply.get('clipboard')}")
    print(f"paste backend     : {reply.get('paste')}")
    print(
        f"clips stored      : {reply.get('clips')} "
        f"({reply.get('pinned')} pinned, {reply.get('images')} images)"
    )
    print(f"popup visible     : {reply.get('visible')}")
    return 0


def cmd_clear(_args) -> int:
    if not _ensure_daemon():
        return 1
    return _send("clear")


def cmd_stop(_args) -> int:
    if not ipc.is_alive():
        print("simpleclips: not running")
        return 0
    return _send("quit")


def cmd_settings(_args) -> int:
    if not _ensure_daemon():
        print("could not reach or start the simpleclips daemon", file=sys.stderr)
        return 1
    return _send("settings")


def cmd_pick(args) -> int:
    """Copy the Nth clip (1-based) straight to the clipboard."""
    if not _ensure_daemon():
        print("could not reach or start the simpleclips daemon", file=sys.stderr)
        return 1
    try:
        reply = ipc.send({"cmd": "pick", "index": args.index})
    except OSError as exc:
        print(f"simpleclips is not running ({exc})", file=sys.stderr)
        return 1
    if not reply.get("ok"):
        print(f"error: {reply.get('error', 'unknown')}", file=sys.stderr)
        return 1
    return 0


def cmd_list(_args) -> int:
    from .store import Store

    store = Store()
    clips = store.ordered()
    if not clips:
        print("(no clips)")
        return 0
    for i, clip in enumerate(clips, start=1):
        marker = "*" if clip.pinned else " "
        if clip.kind == "image":
            preview = f"[image {clip.width}\u00d7{clip.height} {clip.mime}]"
        else:
            preview = " ".join(clip.text.split())
            if len(preview) > 70:
                preview = preview[:70] + "\u2026"
        print(f"{i:>3} {marker} {preview}")
    return 0


def cmd_install(args) -> int:
    from . import install as installer

    return installer.install(args.hotkey)


def cmd_uninstall(_args) -> int:
    from . import install as installer

    return installer.uninstall()


def _paste_shortcut() -> str:
    from . import config as config_mod

    return config_mod.Config.load().paste_shortcut


def cmd_doctor(_args) -> int:
    from . import config as config_mod
    from . import input_inject
    from .clipboard import Clipboard
    from .pointer import Pointer

    print(f"simpleclips       : {__version__}")
    print(f"python            : {sys.version.split()[0]}")
    print(f"session type      : {os.environ.get('XDG_SESSION_TYPE', '?')}")
    print(f"desktop           : {os.environ.get('XDG_CURRENT_DESKTOP', '?')}")
    print(f"wayland display   : {os.environ.get('WAYLAND_DISPLAY', '-')}")
    print(f"x11 display       : {os.environ.get('DISPLAY', '-')}")
    print(f"clipboard backend : {Clipboard().backend}")
    combo = config_mod.Config.load().paste_shortcut
    print(f"paste backend     : {input_inject.detect(combo)}")
    print(f"paste shortcut    : {combo}")
    pointer = Pointer()
    source = pointer.source()
    print(f"pointer source    : {source}")
    if source == "x11" and os.environ.get("XDG_SESSION_TYPE") == "wayland":
        print(
            "                    (XWayland pointer is stale on Wayland; "
            "install the GNOME extension for exact placement)"
        )
    if os.environ.get("WAYLAND_DISPLAY") and input_inject.detect(combo) == "none":
        print(f"auto-paste hint   : {input_inject.extension_hint()}")
    print(f"config file       : {config_mod.config_file()}")
    print(f"history file      : {config_mod.history_file()}")
    print(f"images dir        : {config_mod.images_dir()}")
    print(f"socket file       : {config_mod.socket_file()}")
    print(f"daemon running    : {ipc.is_alive()}")
    return 0


def cmd_notify(_args) -> int:
    """Internal: called by `wl-paste --watch`; forwards a change to the daemon."""
    try:
        sys.stdin.buffer.read()
    except Exception:
        pass
    try:
        ipc.send({"cmd": "notify"}, timeout=1.0)
    except OSError:
        pass
    return 0


def cmd_daemon(_args) -> int:
    from .daemon import run_daemon

    return run_daemon()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="simpleclips",
        description="A tiny Win+V style clipboard history for Linux desktops.",
    )
    parser.add_argument("--version", action="version", version=f"simpleclips {__version__}")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("daemon", help="run in the foreground (usually via systemd)")
    sub.add_parser("toggle", help="open/close the popup (bind this to a shortcut)")
    sub.add_parser("show", help="open the popup")
    sub.add_parser("hide", help="close the popup")
    sub.add_parser("status", help="show daemon status")
    sub.add_parser("list", help="print stored clips")
    sub.add_parser("clear", help="drop unpinned history")
    sub.add_parser("stop", help="stop a running daemon")
    sub.add_parser("settings", help="open the settings window")
    p_pick = sub.add_parser("pick", help="copy the Nth clip to the clipboard")
    p_pick.add_argument("index", nargs="?", type=int, default=1, help="clip number")
    sub.add_parser("doctor", help="print environment diagnostics")

    p_install = sub.add_parser("install", help="install service + shortcut")
    p_install.add_argument("--hotkey", default=HOTKEY_DEFAULT, help="GNOME accelerator")
    sub.add_parser("uninstall", help="remove service + shortcut")

    sub.add_parser("_notify", help=argparse.SUPPRESS)
    return parser


HANDLERS = {
    "daemon": cmd_daemon,
    "toggle": cmd_toggle,
    "show": cmd_show,
    "hide": cmd_hide,
    "status": cmd_status,
    "list": cmd_list,
    "clear": cmd_clear,
    "stop": cmd_stop,
    "settings": cmd_settings,
    "pick": cmd_pick,
    "install": cmd_install,
    "uninstall": cmd_uninstall,
    "doctor": cmd_doctor,
    "_notify": cmd_notify,
}


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0
    handler = HANDLERS.get(args.command)
    if handler is None:
        parser.print_help()
        return 1
    return handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
