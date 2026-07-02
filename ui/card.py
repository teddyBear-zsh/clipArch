"""
Clipboard Card Module
author: teddyBear
license: MIT

A single card widget representing one ClipboardItem in the history list.

Visual language (per design plan):
    - Pinned items get a 3px accent-colored left border instead of a generic
        pin icon badge — distinguishes them without cluttering the card.
    - Text preview uses a monospace face (developer-tool feel).
    - Truncated/oversized items show a warning badge and are not selectable
        for paste (only delete/unpin remain available).
    - Each card has an inline action row (pin / delete) revealed on hover,
        kept hidden otherwise to keep the list visually quiet.
"""

from __future__ import annotations

from io import BytesIO
from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gtk, GdkPixbuf, Gio, GLib

from clipboard.history import ClipboardItem
from clipboard.manager import ClipboardType


class ClipboardCard(Gtk.ListBoxRow):
    """
    Renders one ClipboardItem as a card row inside the history ListBox.
    """

    def __init__(
        self,
        item: ClipboardItem,
        on_select: Callable[[ClipboardItem], None],
        on_pin_toggle: Callable[[str], None],
        on_delete: Callable[[str], None],
    ):
        super().__init__()

        self.item          = item
        self.on_select      = on_select
        self.on_pin_toggle  = on_pin_toggle
        self.on_delete      = on_delete

        self.add_css_class("clipboard-card")
        if item.pinned:
            self.add_css_class("pinned")
        if item.truncated:
            self.add_css_class("truncated")

        self._build()
        self._connect_interactions()

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _build(self) -> None:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        row.add_css_class("card-row")
        row.set_margin_top(8)
        row.set_margin_bottom(8)
        row.set_margin_start(12)
        row.set_margin_end(10)

        # --- Leading visual: thumbnail or type icon ------------------------
        row.append(self._build_leading_visual())

        # --- Middle: preview text + metadata line --------------------------
        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        text_box.set_hexpand(True)
        text_box.set_valign(Gtk.Align.CENTER)

        preview_label = Gtk.Label(label=self.item.preview)
        preview_label.set_xalign(0)
        preview_label.set_wrap(False)
        preview_label.set_ellipsize(3)  # Pango.EllipsizeMode.END
        preview_label.add_css_class("card-preview")
        if self.item.content_type == ClipboardType.TEXT:
            preview_label.add_css_class("monospace")
        text_box.append(preview_label)

        meta_label = Gtk.Label(label=self._meta_text())
        meta_label.set_xalign(0)
        meta_label.add_css_class("card-meta")
        text_box.append(meta_label)

        row.append(text_box)

        # --- Trailing: action buttons (pin / delete) ------------------------
        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        actions.add_css_class("card-actions")
        actions.set_valign(Gtk.Align.CENTER)

        self.pin_button = Gtk.Button()
        self.pin_button.set_icon_name(
            "view-pin-symbolic" if self.item.pinned else "view-pin-outline-symbolic"
        )
        self.pin_button.add_css_class("flat")
        self.pin_button.add_css_class("card-action-button")
        self.pin_button.set_tooltip_text(
            "Desfijar" if self.item.pinned else "Fijar"
        )
        actions.append(self.pin_button)

        self.delete_button = Gtk.Button()
        self.delete_button.set_icon_name("user-trash-symbolic")
        self.delete_button.add_css_class("flat")
        self.delete_button.add_css_class("card-action-button")
        self.delete_button.add_css_class("destructive-hover")
        self.delete_button.set_tooltip_text("Eliminar")
        actions.append(self.delete_button)

        row.append(actions)

        self.set_child(row)

    def _build_leading_visual(self) -> Gtk.Widget:
        """Thumbnail for images, icon for other types."""
        size = 36

        if self.item.content_type == ClipboardType.IMAGE and self.item.image:
            picture = self._image_bytes_to_picture(self.item.image, size)
            if picture:
                picture.add_css_class("card-thumbnail")
                return picture

        # Fallback: symbolic icon per type
        icon_name = {
            ClipboardType.IMAGE: "image-x-generic-symbolic",
            ClipboardType.FILE:  "text-x-generic-symbolic",
            ClipboardType.EMOJI: "face-smile-symbolic",
            ClipboardType.TEXT:  "edit-paste-symbolic",
        }.get(self.item.content_type, "dialog-question-symbolic")

        icon = Gtk.Image.new_from_icon_name(icon_name)
        icon.set_pixel_size(20)
        icon.set_size_request(size, size)
        icon.add_css_class("card-icon")
        return icon

    @staticmethod
    def _image_bytes_to_picture(image_bytes: bytes, size: int) -> Gtk.Widget | None:
        """Decode raw image bytes into a square Gtk.Picture thumbnail."""
        try:
            loader = GdkPixbuf.PixbufLoader()
            loader.write(image_bytes)
            loader.close()
            pixbuf = loader.get_pixbuf()
            if pixbuf is None:
                return None

            scaled = pixbuf.scale_simple(
                size, size, GdkPixbuf.InterpType.BILINEAR
            )
            picture = Gtk.Picture.new_for_pixbuf(scaled)
            picture.set_content_fit(Gtk.ContentFit.COVER)
            picture.set_size_request(size, size)
            return picture
        except GLib.Error:
            return None

    def _meta_text(self) -> str:
        """Type label + relative time, e.g. 'Texto · hace 2 min'."""
        type_labels = {
            ClipboardType.TEXT:  "Texto",
            ClipboardType.IMAGE: "Imagen",
            ClipboardType.EMOJI: "Emoji",
            ClipboardType.FILE:  "Archivo",
        }
        label = type_labels.get(self.item.content_type, "Desconocido")
        relative = self._relative_time(self.item.timestamp)

        if self.item.truncated:
            return f"{label} · {relative} · ⚠ no se puede pegar"
        return f"{label} · {relative}"

    @staticmethod
    def _relative_time(timestamp) -> str:
        from datetime import datetime
        delta = datetime.now() - timestamp
        seconds = int(delta.total_seconds())

        if seconds < 10:
            return "ahora"
        if seconds < 60:
            return f"hace {seconds}s"
        minutes = seconds // 60
        if minutes < 60:
            return f"hace {minutes} min"
        hours = minutes // 60
        if hours < 24:
            return f"hace {hours}h"
        days = hours // 24
        return f"hace {days}d"

    # ------------------------------------------------------------------
    # Interactions
    # ------------------------------------------------------------------

    def _connect_interactions(self) -> None:
        # Click anywhere on the card (except action buttons) = select/paste
        click = Gtk.GestureClick()
        click.connect("released", self._on_card_clicked)
        self.add_controller(click)

        self.pin_button.connect("clicked", self._on_pin_clicked)
        self.delete_button.connect("clicked", self._on_delete_clicked)

    def _on_card_clicked(self, gesture, n_press, x, y) -> None:
        if self.item.truncated:
            return  # non-pasteable — ignore selection clicks
        self.on_select(self.item)

    def _on_pin_clicked(self, button: Gtk.Button) -> None:
        self.on_pin_toggle(self.item.item_id)

    def _on_delete_clicked(self, button: Gtk.Button) -> None:
        self.on_delete(self.item.item_id)