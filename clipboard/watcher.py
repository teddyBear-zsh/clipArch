"""
Clipboard Watcher Module
author: teddyBear
license: MIT

Polls the system clipboard at a fixed interval and feeds new content
into a ClipboardHistory instance. Designed to integrate with GLib's
main loop (GTK4) via GLib.timeout_add(), but also works as a plain
blocking loop for headless/daemon use (e.g. testing without a UI).

Design notes
------------
- Polling, not event-based: X11/Wayland don't expose a portable
    "clipboard changed" signal across both xclip and wl-clipboard, so we
    poll at POLL_INTERVAL_MS and compare hashes to detect changes cheaply.
- The watcher itself does NOT read full content on every tick — it only
    asks for clipboard TYPES first (cheap call) and only fetches full
    content (text/image bytes) when a change is detected. This keeps CPU
    usage near-zero while idle.
- A callback (on_change) is invoked whenever a new item is successfully
    added to history, so the UI layer can refresh its card list reactively.
"""

from __future__ import annotations

import hashlib
import sys
import time
from typing import Callable, Optional

from .manager import ClipboardManager, ClipboardType
from .history import ClipboardHistory, ClipboardItem

POLL_INTERVAL_MS = 500 # Polling interval

class ClipboardWatcher:
    """ 
    Watches the system clipboard for changer and records them into 
    a ClipboardHistory instance.

    Usage standalone:
        watcher = ClipboardWatcher(history)
    """

    def __init__(
        self,
        history: ClipboardHistory,
        manager: Optional[ClipboardManager] = None,
        on_change: Optional[Callable[[ClipboardItem], None]] = None,
        poll_interval_ms: int = POLL_INTERVAL_MS,
        ignore_own_writes: bool = True,
    ):
        self.history = history
        self.manager = manager or ClipboardManager()
        self.on_change = on_change
        self.poll_interval_ms = poll_interval_ms
        self.ignore_own_writes = ignore_own_writes

        self._last_types_hash: Optional[str] = None
        self._running = False

        # Set right after this watcher itself writes to the clipboard
        # (e.g. via "paste" action), so the next tick doesn't re-add
        # the same content as if the user had copied it

        self._suppress_next_change = False

        if not self.manager.is_endpoint_available:
            print(
                "[ClipboardWatcher] No clipboard enpoint available."
                "Watchar will be inactive. (Are you running in a headless environment?)",
                file=sys.stderr,
            )

    #-----------------------------------
    #Public control
    #-----------------------------------

    def suppress_next_change(self) -> None:
        """
        Call this right before the watcher itself writes to the clipboard
        (e.g. when implemmenting 'paste selected item'), so the write
        isn't treated as a new user copy and re-added to history.
        """

        self._suppress_next_change = True

    def run_forever(self) -> None:
        """
        Blocking polling loop for headless/daemon use.
        """

        self._running = True
        print("[ClipboardWatcher] Started polling loop. Press Ctrl+C to exit.", file=sys.stderr)
        try:
            while self._running:
                self.tick()
                time.sleep(self.poll_interval_ms / 1000)
        except KeyboardInterrupt:
            print("[ClipboardWatcher] Stopped polling loop.", file=sys.stderr)
        finally:
            self._running = False
        
    def stop(self) -> None:
        """Stop the polling loop (run_forever). No-op for Glib mode."""
        self._running = False
    
    #-----------------------------------
    #Core tick
    #------------------------------------

    def tick(self) -> None:
        """
        Single polling step:
        -Cheaply Check if clipboard TYPES changed (not full content read)
        -If changed, fetch full content and try to add to history
        -Invoke on_change callback if a new item was added

        Note: Returns True alwas, this is the expected return value for GLib.timeout_add() to keep 
        the timer repeating.        
        """
        if not self.manager.is_endpoint_available:
            return True #keep timer alive but do nothing
        
        types = self.manager.get_clipboard_types()
        types_hash = self._hash_types(types)

        #Nothing changed since last tick - cheap exit
        if types_hash == self._last_types_hash:
            return True
        
        self._last_types_hash = types_hash

        #This change was caused by our own "paste" write, skip it once
        if self._suppress_next_change:
            self._suppress_next_change = False
            return True
        
        if not types:
            return True #clipboard was cleared, nothing to record
        


    #----------------------------------------
    # Helpers
    #----------------------------------------
    
    def _hash_types(types: list) -> str:
        """ Cheep fingerprint of the current clipboard TARGETS list."""
        joined = "|".join(sorted(types))
        return hashlib.md5(joined.encode()).hexdigest()
