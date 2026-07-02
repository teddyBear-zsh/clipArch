"""
Clipboard Watcher — native GDK4 clipboard signal, no external process

Why this rewrite exists:
Both previous approaches (polling wl-paste on a timer, and running
`wl-paste --watch`) spawn or maintain a *separate* Wayland client
(app id "io.github.bugaevc.wl-clipboard") outside the app itself.

- Polling spawned a new client twice a second -> GNOME showed
  repeated "app tries to open but fails" launch animations.
- `--watch` mode depends on the wlr-data-control-unstable-v1 protocol,
  which originated in wlroots (Sway/Hyprland) for clipboard-manager
  use cases. GNOME's Mutter has historically had partial/no support
  for it, which is consistent with the connection failing and
  restarting in a loop.

Fix: use Gdk.Clipboard, the same clipboard API every native GTK app
already uses for ordinary copy/paste. It rides on the standard
Wayland data-device protocol that GNOME fully supports (basic
copy/paste has to work for every app), and it's part of the same
process, in the same Wayland connection the app already has via GTK
- no subprocess, no separate client, no app id for GNOME to track.

Trade-off: this only works while the app's GTK main loop is running
(which it always is here), and it currently reads text content only,
matching the scope of the previous implementation.
"""

from __future__ import annotations

import hashlib
import sys
from typing import Callable, Optional

from gi.repository import Gdk, GLib

from .manager import ClipboardManager, ClipboardType
from .history import ClipboardHistory, ClipboardItem


class ClipboardWatcher:
    def __init__(
        self,
        history: ClipboardHistory,
        manager: Optional[ClipboardManager] = None,
        on_change: Optional[Callable[[ClipboardItem], None]] = None,
        display: Optional[Gdk.Display] = None,
    ):
        self.history = history
        self.manager = manager or ClipboardManager()
        self.on_change = on_change

        self._suppress_next_change = False
        self._last_content_hash: str | None = None

        self._display = display or Gdk.Display.get_default()
        self._clipboard = self._display.get_clipboard() if self._display else None
        self._signal_id: int | None = None

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    def suppress_next_change(self) -> None:
        self._suppress_next_change = True

    def start(self) -> None:
        if not self._clipboard:
            print("[Watcher] No Gdk.Display available - clipboard watching disabled", file=sys.stderr)
            return
        self._signal_id = self._clipboard.connect("changed", self._on_clipboard_changed)

    def stop(self) -> None:
        if self._clipboard and self._signal_id is not None:
            try:
                self._clipboard.disconnect(self._signal_id)
            except Exception:
                pass
            self._signal_id = None

    # ------------------------------------------------------------------
    # event handling
    # ------------------------------------------------------------------

    def _on_clipboard_changed(self, clipboard: Gdk.Clipboard) -> None:
        # Attempt a text read. If the new clipboard content isn't text
        # (e.g. an image), read_text_finish will report failure and
        # we simply skip it - matches the text-only scope of the
        # previous implementation.
        clipboard.read_text_async(None, self._on_text_ready)

    def _on_text_ready(self, clipboard: Gdk.Clipboard, result) -> None:
        try:
            text = clipboard.read_text_finish(result)
        except GLib.Error:
            return

        if not text:
            return

        self._handle_new_content(text)

    def _handle_new_content(self, text: str) -> None:
        new_hash = self._hash(text)

        if new_hash == self._last_content_hash:
            return

        if self._suppress_next_change:
            self._suppress_next_change = False
            self._last_content_hash = new_hash
            return

        self._last_content_hash = new_hash

        snapshot = {
            "type": ClipboardType.TEXT,
            "text": text,
            "image": None,
            "files": [],
        }

        item = self.history.add(snapshot)

        if item and self.on_change:
            self.on_change(item)

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _hash(self, content: str | bytes) -> str:
        if isinstance(content, str):
            content = content.encode("utf-8")
        return hashlib.sha256(content).hexdigest()