"""Best-effort desktop notifications.

Used to warn about clips that were not stored (for example an image above
the size limit). Falls back silently when no notification tool is present,
since the popup shows the same message in its footer.
"""

from __future__ import annotations

import shutil
import subprocess


def send(title: str, body: str, icon: str = "edit-paste-symbolic") -> bool:
    if not shutil.which("notify-send"):
        return False
    try:
        subprocess.Popen(
            ["notify-send", "--app-name=SimpleCopyPaste", f"--icon={icon}", title, body],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return True
    except OSError:
        return False
