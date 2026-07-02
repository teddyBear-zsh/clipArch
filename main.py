"""
Clipboard Manager — Entry Point (stable GNOME Wayland version)

Fixes applied:
- Removed Gtk.Application.hold() (causes GNOME lifecycle glitches)
- Fixed lock file cleanup (atexit)
- Stale lock file detection (PID liveness check)
- Single UI entry path (SIGUSR1 only)
- Safe clipboard paste fallback

IMPORTANT: The GNOME custom keybinding must NOT invoke this script.
It should send SIGUSR1 directly to the running process, e.g.:

    kill -SIGUSR1 $(cat /tmp/clipboard-manager.lock)

Invoking `python3 main.py` from the keybinding will spawn a short-lived
process on every keypress, which GNOME Shell tracks as an app launch —
causing the flicker/spinner behavior even though the process exits
almost immediately.
"""

from __future__ import annotations

import os
import sys
import signal
import subprocess
import atexit
import shutil
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib, Gio, Gdk

from clipboard.manager import ClipboardManager, ClipboardType
from clipboard.history import ClipboardHistory, ClipboardItem
from clipboard.watcher import ClipboardWatcher
from ui.window import ClipboardWindow


# ---------------------------------------------------------------------------
# Singleton lock (with stale-lock detection)
# ---------------------------------------------------------------------------

LOCK_FILE = Path("/tmp/clipboard-manager.lock")


def is_process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but owned by another user - treat as alive
        return True
    except OSError:
        return False


def acquire_lock() -> None:
    if LOCK_FILE.exists():
        try:
            old_pid = int(LOCK_FILE.read_text().strip())
        except (ValueError, OSError):
            old_pid = None

        if old_pid and is_process_alive(old_pid):
            print(f"[main] Already running (pid={old_pid}) - exit", file=sys.stderr)
            sys.exit(0)
        else:
            print("[main] Stale lock file found - removing", file=sys.stderr)
            try:
                LOCK_FILE.unlink()
            except FileNotFoundError:
                pass

    LOCK_FILE.write_text(str(os.getpid()))


def remove_lock() -> None:
    try:
        # Only remove if it's still our own PID (avoid racing a newer instance)
        if LOCK_FILE.exists() and LOCK_FILE.read_text().strip() == str(os.getpid()):
            LOCK_FILE.unlink()
    except (FileNotFoundError, ValueError, OSError):
        pass


acquire_lock()
atexit.register(remove_lock)


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

class ClipboardApp(Gtk.Application):

    def __init__(self):
        super().__init__(
            application_id="dev.teddybear.clipboardmanager",
            flags=Gio.ApplicationFlags.FLAGS_NONE,
        )

        self.manager = ClipboardManager()
        self.history = ClipboardHistory(
            max_size=20,
            max_text_bytes=1 * 1024 * 1024,
            max_image_bytes=5 * 1024 * 1024,
            max_buffer_bytes=20 * 1024 * 1024,
        )

        self.window = None
        self.watcher = ClipboardWatcher(
            history=self.history,
            manager=self.manager,
            on_change=self._on_clipboard_changed,
        )

        self._watcher_source_id = None
        self._sigusr1_source_id = None

    # ------------------------------------------------------------------
    # Startup
    # ------------------------------------------------------------------

    def do_startup(self):
        Gtk.Application.do_startup(self)

        self.window = ClipboardWindow(
            app=self,
            history=self.history,
            on_select=self._on_item_selected,
            on_pin_toggle=self._on_pin_toggle,
            on_delete=self._on_delete,
            on_clear_all=self._on_clear_all,
        )

        # Persistent clipboard watcher — single wl-paste --watch process,
        # NOT a polling timer (that was spawning wl-paste twice a second
        # and causing the repeated GNOME launch-animation flicker).
        self.watcher.start()
        atexit.register(self.watcher.stop)

        # SIGUSR1 → toggle popup (single entry point for showing/hiding)
        self._sigusr1_source_id = GLib.unix_signal_add_full(
            GLib.PRIORITY_DEFAULT,
            signal.SIGUSR1,
            self._toggle_popup,
        )

    # ------------------------------------------------------------------
    # IMPORTANT: no UI logic here (GNOME-safe)
    # ------------------------------------------------------------------

    def do_activate(self):
        # No UI management here to avoid GNOME lifecycle conflicts.
        # This keeps the app running as a background service; GLib holds
        # a reference via the active timeout/signal sources, so we don't
        # need Gtk.Application.hold().
        return

    # ------------------------------------------------------------------
    # Toggle UI (single entry point)
    # ------------------------------------------------------------------

    def _toggle_popup(self, *args):
        if not self.window:
            return GLib.SOURCE_CONTINUE

        def action():
            if self.window.get_visible():
                self.window.hide()
            else:
                self.window.present_popup()
            return False

        GLib.idle_add(action)
        return GLib.SOURCE_CONTINUE

    # ------------------------------------------------------------------
    # Clipboard updates
    # ------------------------------------------------------------------

    def _on_clipboard_changed(self, item: ClipboardItem) -> None:
        # UI refresh only if visible
        if self.window and self.window.get_visible():
            self.window.refresh()

    # ------------------------------------------------------------------
    # Card actions forwarded from ClipboardWindow
    # NOTE: adjust these method names to match your actual
    # ClipboardHistory API if they differ (e.g. toggle_pin/remove/clear).
    # ------------------------------------------------------------------

    def _on_pin_toggle(self, item_id: str) -> None:
        self.history.toggle_pin(item_id)

    def _on_delete(self, item_id: str) -> None:
        self.history.remove(item_id)

    def _on_clear_all(self) -> None:
        self.history.clear()

    # ------------------------------------------------------------------
    # Paste action
    # ------------------------------------------------------------------

    def _on_item_selected(self, item: ClipboardItem) -> None:
        self.watcher.suppress_next_change()

        if item.content_type == ClipboardType.IMAGE and item.image:
            self.manager.set_image_content(item.image)
        else:
            self.manager.set_text_content(item.text or "")

        GLib.timeout_add(80, self._do_paste)

    def _do_paste(self) -> bool:
        if shutil.which("xdotool"):
            subprocess.Popen(["xdotool", "key", "ctrl+v"])
        else:
            print("[main] xdotool not found - paste skipped", file=sys.stderr)
        return GLib.SOURCE_REMOVE


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    app = ClipboardApp()
    sys.exit(app.run(sys.argv))


if __name__ == "__main__":
    main()