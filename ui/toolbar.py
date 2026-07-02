"""
Clipboard Toolbar Module
author: teddyBear
license: MIT

Top bar of the popup: type filter icons (text/image/emoji/file) on the
left, buffer usage indicator + "clear all" on the right — matching the
sketch's header concept.
"""

from __future__ import annotations

from typing import Callable, Optional

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

from clipboard.manager import ClipboardType


class ClipboardToolbar(Gtk.Box):
    """
    Header row with:
        - Filter toggle buttons (All / Text / Image / Emoji / File)
        - Buffer usage label (e.g. "8/20 · 3.2 MB")
        - "Clear all" button
    """

    FILTERS = [
        (None,                  "view-grid-symbolic",       "Todo"),
        (ClipboardType.TEXT,    "edit-paste-symbolic",      "Texto"),
        (ClipboardType.IMAGE,   "image-x-generic-symbolic", "Imágenes"),
        (ClipboardType.EMOJI,   "face-smile-symbolic",      "Emojis"),
        (ClipboardType.FILE,    "text-x-generic-symbolic",  "Archivos"),
    ]

    def __init__(
        self,
        on_filter_change: Callable[[Optional[str]], None],
        on_clear_all: Callable[[], None],
    ):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.add_css_class("toolbar")

        self.on_filter_change = on_filter_change
        self.on_clear_all      = on_clear_all
        self._filter_buttons: list[Gtk.ToggleButton] = []

        self._build()

    def _build(self) -> None:
        # --- Row 1: filters + clear all -------------------------------------
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        row.set_margin_top(10)
        row.set_margin_bottom(8)
        row.set_margin_start(12)
        row.set_margin_end(12)

        filter_group = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        filter_group.add_css_class("filter-group")

        group_leader = None
        for content_type, icon_name, tooltip in self.FILTERS:
            btn = Gtk.ToggleButton()
            btn.set_icon_name(icon_name)
            btn.set_tooltip_text(tooltip)
            btn.add_css_class("flat")
            btn.add_css_class("filter-button")

            if group_leader is None:
                group_leader = btn
                btn.set_active(True)
            else:
                btn.set_group(group_leader)

            btn.connect("toggled", self._on_filter_toggled, content_type)
            filter_group.append(btn)
            self._filter_buttons.append(btn)

        row.append(filter_group)

        spacer = Gtk.Box(hexpand=True)
        row.append(spacer)

        self.clear_button = Gtk.Button(label="Vaciar")
        self.clear_button.add_css_class("flat")
        self.clear_button.add_css_class("clear-all-button")
        self.clear_button.connect("clicked", self._on_clear_clicked)
        row.append(self.clear_button)

        self.append(row)

        # --- Row 2: buffer usage stats ---------------------------------------
        self.stats_label = Gtk.Label(label="")
        self.stats_label.set_xalign(0)
        self.stats_label.add_css_class("stats-label")
        self.stats_label.set_margin_start(14)
        self.stats_label.set_margin_bottom(6)
        self.append(self.stats_label)

        separator = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        separator.add_css_class("toolbar-separator")
        self.append(separator)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_stats(self, stats: dict) -> None:
        """Update the buffer usage line, e.g. '8/20 elementos · 3.2/20 MB'."""
        text = (
            f"{stats['count']}/{stats['max_size']} elementos · "
            f"{stats['buffer_mb']:.1f}/{int(stats['max_buffer_bytes']) / 1024 / 1024:.0f} MB"
        )
        if stats.get("pinned"):
            text += f" · {stats['pinned']} fijado{'s' if stats['pinned'] != 1 else ''}"
        self.stats_label.set_text(text)

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    def _on_filter_toggled(self, button: Gtk.ToggleButton, content_type) -> None:
        if button.get_active():
            self.on_filter_change(content_type)

    def _on_clear_clicked(self, button: Gtk.Button) -> None:
        self.on_clear_all()