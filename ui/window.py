"""
Main Window Module
author: teddyBear
license: MIT

Floating popup window that display the clipboard 
history as a vertical list od cards. Uses gtk4-layer-shell when running under 
Wayland compositors that support it, and falls back to a 
bordeless centered Gtk.Window on Gnome

"""

from __future__ import annotations

import os
import sys
from typing import Callable, Optional

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Gdk, GLib, Gio

# gtk4-layer-shell is optional: only meaningful on wlroots compositors
# (Hyprland, Sway, etc). GNOME's Mutter does not implement layer-shell,
# so we detect availability and degrade gracefully
try:
    gi.require_version("Gtk4LayerShell", "1.0")
    from gi.repository import Gtk4LayerShell as LayerShell
    LAYER_SHELL_AVAILABLE = True
except (ValueError, ImportError):
    LAYER_SHELL_AVAILABLE = False

from clipboard.history import ClipboardHistory, ClipboardItem
from clipboard.manager import ClipboardType
from .card import ClipboardCard
from .toolbar import ClipboardToolbar

WINDOW_WIDTH  = 420
WINDOW_HEIGHT = 560

class ClipboardWindow(Gtk.ApplicationWindow):
    """
    The main floating clipboard popup.
    Responsibilities:
        - Render the current ClipboardHistory as a scrollable list of cards.
        - Host the top toolbar (clear all + type filters).
        - React to filter changes and re-render only the matching items.
        - Forward card actions (select / pin / delete) to callbacks supplied
            by the caller (main.py), which owns the actual ClipboardHistory
            and ClipboardManager instances.
    """

    def __init__(
        self,
        app: Gtk.Application,
        history: ClipboardHistory,
        on_select: Callable[[ClipboardItem], None],
        on_pin_toggle: Callable[[str], None],
        on_delete: Callable[[str], None],
        on_clear_all: Callable[[], None],
    ):
        super().__init__(application=app)

        self.history       = history
        self.on_select      = on_select
        self.on_pin_toggle  = on_pin_toggle
        self.on_delete      = on_delete
        self.on_clear_all   = on_clear_all

        self._active_filter: Optional[str] = None
        self._shutting_down = False

        self.connect("close-request", self._on_close_request)

        self._build_window_shell()
        self._build_layout()
        self._connect_keyboard_shortcuts()
        self.refresh()

    # ------------------------------------------------------------------
    # Window shell — layer-shell on Hyprland, plain floating window elsewhere
    # ------------------------------------------------------------------

    def _build_window_shell(self) -> None:
        self.set_default_size(WINDOW_WIDTH, WINDOW_HEIGHT)
        self.set_resizable(False)
        self.set_decorated(False)        # no titlebar — popup feel
        self.add_css_class("clipboard-popup")

        if (
            LAYER_SHELL_AVAILABLE
            and os.environ.get("XDG_SESSION_DESKTOP") == "Hyprland"
        ):
            self._init_layer_shell()
        else:
            # GNOME / X11 fallback: centered floating window, no layer-shell.
            # Not truly "always on top" without a compositor protocol, but
            # behaves correctly as a transient popup window.
            self.set_modal(False)

    def _init_layer_shell(self) -> None:
        """Configure gtk4-layer-shell so the popup floats above all windows
        and is centered on screen — the Hyprland/wlroots path."""
        LayerShell.init_for_window(self)
        LayerShell.set_layer(self, LayerShell.Layer.OVERLAY)
        LayerShell.set_keyboard_mode(self, LayerShell.KeyboardMode.ON_DEMAND)

        # Center: anchor to no edges, layer-shell centers by default when
        # no anchors are set and exclusive zone is 0.
        for edge in (LayerShell.Edge.LEFT, LayerShell.Edge.RIGHT,
                    LayerShell.Edge.TOP, LayerShell.Edge.BOTTOM):
            LayerShell.set_anchor(self, edge, False)

        LayerShell.set_exclusive_zone(self, 0)

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def _build_layout(self) -> None:
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        root.add_css_class("popup-root")

        # --- Toolbar (clear all + type filters) ---------------------------
        self.toolbar = ClipboardToolbar(
            on_filter_change=self._on_filter_change,
            on_clear_all=self._on_clear_all_clicked,
        )
        root.append(self.toolbar)

        # --- Scrollable card list ------------------------------------------
        self.scroller = Gtk.ScrolledWindow()
        self.scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.scroller.set_vexpand(True)

        self.card_list = Gtk.ListBox()
        self.card_list.add_css_class("card-list")
        self.card_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.scroller.set_child(self.card_list)

        # --- Empty state -----------------------------------------------
        self.empty_state = self._build_empty_state()

        self.content_stack = Gtk.Stack()
        self.content_stack.add_named(self.scroller, "list")
        self.content_stack.add_named(self.empty_state, "empty")
        self.content_stack.set_vexpand(True)
        root.append(self.content_stack)

        self.set_child(root)

    def _build_empty_state(self) -> Gtk.Widget:
        box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=8,
            halign=Gtk.Align.CENTER,
            valign=Gtk.Align.CENTER,
            vexpand=True,
        )
        box.add_css_class("empty-state")

        icon = Gtk.Image.new_from_icon_name("edit-paste-symbolic")
        icon.set_pixel_size(40)
        icon.add_css_class("empty-state-icon")

        label = Gtk.Label(label="Clipboard vacío")
        label.add_css_class("empty-state-title")

        sublabel = Gtk.Label(label="Copia algo para verlo aquí")
        sublabel.add_css_class("empty-state-subtitle")

        box.append(icon)
        box.append(label)
        box.append(sublabel)
        return box

    # ------------------------------------------------------------------
    # Keyboard shortcuts — Escape closes, arrows navigate (future), Enter selects top
    # ------------------------------------------------------------------

    def _connect_keyboard_shortcuts(self) -> None:
        controller = Gtk.EventControllerKey()
        controller.connect("key-pressed", self._on_key_pressed)
        self.add_controller(controller)

    def _on_key_pressed(self, controller, keyval, keycode, state) -> bool:
        if keyval == Gdk.KEY_Escape:
            self.hide()
            return True
        return False
    
    def _on_close_request(self, *_):
        """
        Prevent GTK from destroying the window.
        We only hide it so it can be shown again.
        """
        if self._shutting_down:
            return False

        self.hide()
        return True

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def refresh(self) -> None:
        """Re-render the card list from the current history + active filter."""
        # Clear existing cards
        child = self.card_list.get_first_child()
        while child is not None:
            next_child = child.get_next_sibling()
            self.card_list.remove(child)
            child = next_child

        items = (
            self.history.filter_by_type(self._active_filter)
            if self._active_filter
            else self.history.items
        )

        if not items:
            self.content_stack.set_visible_child_name("empty")
            self.toolbar.set_stats(self.history.stats())
            return

        self.content_stack.set_visible_child_name("list")

        for item in items:
            card = ClipboardCard(
                item=item,
                on_select=self._on_card_selected,
                on_pin_toggle=self._on_card_pin_toggled,
                on_delete=self._on_card_deleted,
            )
            self.card_list.append(card)

        self.toolbar.set_stats(self.history.stats())

    # ------------------------------------------------------------------
    # Event handlers — forward to caller-supplied callbacks
    # ------------------------------------------------------------------

    def _on_card_selected(self, item: ClipboardItem) -> None:
        self.on_select(item)
        self.hide()

    def _on_card_pin_toggled(self, item_id: str) -> None:
        self.on_pin_toggle(item_id)
        self.refresh()

    def _on_card_deleted(self, item_id: str) -> None:
        self.on_delete(item_id)
        self.refresh()

    def _on_clear_all_clicked(self) -> None:
        self.on_clear_all()
        self.refresh()

    def _on_filter_change(self, content_type: Optional[str]) -> None:
        self._active_filter = content_type
        self.refresh()

    # ------------------------------------------------------------------
    # Show / focus helpers — called by main.py when WIN+V is pressed
    # ------------------------------------------------------------------
    def present_popup(self):
        self.present()
        GLib.idle_add(self.refresh)
        