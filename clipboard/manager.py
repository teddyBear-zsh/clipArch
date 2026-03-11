"""
Clipboard Manager Module
author: teddyBear
license: MIT
"""
import os
import sys
import subprocess
from typing import List, Optional

try:
    from PIL import Image
    PILLOW_AVAILABLE = True
except ImportError:
    PILLOW_AVAILABLE = False
    print(
        "Pillow library not found. Image clipboard functionality will be disabled.",
        file=sys.stderr
    )


class ClipboardType:
    """Types of clipboard content."""
    TEXT    = "text"
    IMAGE   = "image"
    EMOJI   = "emoji"
    FILE    = "file"
    UNKNOWN = "unknown"


class ClipboardManager:
    """
    Low-level interface to the system clipboard.
    Supports both Wayland (wl-clipboard) and X11 (xclip).
    """

    def __init__(self):
        self.is_wayland = bool(os.environ.get("WAYLAND_DISPLAY"))
        self.is_endpoint_available = self._check_endpoint()

        if not self.is_endpoint_available:
            backend = "wl-copy/wl-paste" if self.is_wayland else "xclip or xsel"
            print(
                f"Warning: clipboard backend not found ({backend}). "
                "Install the required package.",
                file=sys.stderr
            )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _check_endpoint(self) -> bool:
        """Check whether the clipboard CLI tools are available."""
        if self.is_wayland:
            return (
                self._command_exists("wl-paste")
                and self._command_exists("wl-copy")
            )
        return self._command_exists("xclip") or self._command_exists("xsel")

    @staticmethod
    def _command_exists(command: str) -> bool:
        return subprocess.run(
            ["which", command],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode == 0

    # ------------------------------------------------------------------
    # Type detection
    # ------------------------------------------------------------------

    def get_clipboard_types(self) -> List[str]:
        """Return the list of MIME types currently in the clipboard."""
        try:
            if self.is_wayland:
                result = subprocess.run(
                    ["wl-paste", "--list-types"],
                    capture_output=True,
                    text=True,
                    timeout=1,
                )
            else:
                result = subprocess.run(
                    ["xclip", "-selection", "clipboard", "-o", "-t", "TARGETS"],
                    capture_output=True,
                    text=True,
                    timeout=1,
                )

            if result.returncode == 0:
                return [t for t in result.stdout.strip().split("\n") if t]

        except Exception as e:
            print(f"Error getting clipboard types: {e}", file=sys.stderr)

        return []

    def detect_content_type(self) -> str:
        """
        Inspect current clipboard content and return the best-matching
        ClipboardType constant.
        """
        types = self.get_clipboard_types()

        if not types:
            return ClipboardType.UNKNOWN

        image_mime = {"image/png", "image/jpeg", "image/bmp",
                    "image/gif", "image/webp"}
        if image_mime.intersection(types):
            return ClipboardType.IMAGE

        if "text/uri-list" in types or "x-special/gnome-copied-files" in types:
            return ClipboardType.FILE

        #TODO: --- Plain text (may still be an emoji, filter function ---
        text_mime = {"text/plain", "text/plain;charset=utf-8", "UTF8_STRING", "STRING", "TEXT"}
        if text_mime.intersection(types):
            content = self.get_text_content()
            if content and self._is_emoji(content.strip()):
                return ClipboardType.EMOJI
            return ClipboardType.TEXT

        return ClipboardType.UNKNOWN 

    @staticmethod
    def _is_emoji(text: str) -> bool:
        """
        Heuristic: consider it an emoji entry when the entire string consists
        of characters in the emoji Unicode ranges and is short (≤ 8 chars).
        """
        if len(text) > 8:
            return False
        return all(
            "\U0001F300" <= ch <= "\U0001FAFF"   # Misc symbols & pictographs
            or "\u2600"  <= ch <= "\u27BF"        # Misc symbols
            or "\uFE00"  <= ch <= "\uFE0F"        # Variation selectors
            or "\U0001F1E0" <= ch <= "\U0001F1FF" # Regional indicators (flags)
            for ch in text
        )

    # ------------------------------------------------------------------
    # Content readers
    # ------------------------------------------------------------------

    def get_text_content(self) -> Optional[str]:
        """Read plain-text content from the clipboard."""
        try:
            if self.is_wayland:
                result = subprocess.run(
                    ["wl-paste", "--no-newline"],
                    capture_output=True,
                    text=True,
                    timeout=1,
                )
            else:
                result = subprocess.run(
                    ["xclip", "-selection", "clipboard", "-o"],
                    capture_output=True,
                    text=True,
                    timeout=1,
                )

            if result.returncode == 0:
                return result.stdout

        except Exception as e:
            print(f"Error getting text content: {e}", file=sys.stderr)

        return None

    def get_image_content(self) -> Optional[bytes]:
        """Read raw image bytes from the clipboard (PNG preferred)."""
        try:
            if self.is_wayland:
                for fmt in ["image/png", "image/jpeg", "image/bmp",
                            "image/gif", "image/webp"]:
                    result = subprocess.run(
                        ["wl-paste", "--type", fmt],
                        capture_output=True,
                        timeout=3,
                    )
                    if result.returncode == 0 and result.stdout:
                        return result.stdout
            else:
                result = subprocess.run(
                    ["xclip", "-selection", "clipboard", "-t", "image/png", "-o"],
                    capture_output=True,
                    timeout=3,
                )
                if result.returncode == 0:
                    return result.stdout

        except Exception as e:
            print(f"Error reading image: {e}", file=sys.stderr)

        return None

    def get_file_uris(self) -> List[str]:
        """
        Return the list of file URIs currently in the clipboard
        (e.g. ['file:///home/user/photo.png']).
        """
        try:
            if self.is_wayland:
                result = subprocess.run(
                    ["wl-paste", "--no-newline", "--type", "text/uri-list"],
                    capture_output=True,
                    text=True,
                    timeout=1,
                )
            else:
                result = subprocess.run(
                    ["xclip", "-selection", "clipboard", "-t", "text/uri-list", "-o"],
                    capture_output=True,
                    text=True,
                    timeout=1,
                )

            if result.returncode == 0:
                return [
                    line.strip()
                    for line in result.stdout.splitlines()
                    if line.strip() and not line.startswith("#")
                ]

        except Exception as e:
            print(f"Error getting file URIs: {e}", file=sys.stderr)

        return []

    # ------------------------------------------------------------------
    # Content writer
    # ------------------------------------------------------------------

    def set_text_content(self, text: str) -> bool:
        """Write plain text to the clipboard. Returns True on success."""
        try:
            if self.is_wayland:
                result = subprocess.run(
                    ["wl-copy"],
                    input=text,
                    text=True,
                    timeout=2,
                )
            else:
                result = subprocess.run(
                    ["xclip", "-selection", "clipboard"],
                    input=text,
                    text=True,
                    timeout=2,
                )

            return result.returncode == 0

        except Exception as e:
            print(f"Error setting text content: {e}", file=sys.stderr)

        return False

    def set_image_content(self, image_bytes: bytes,
                        mime: str = "image/png") -> bool:
        """Write raw image bytes to the clipboard. Returns True on success."""
        try:
            if self.is_wayland:
                result = subprocess.run(
                    ["wl-copy", "--type", mime],
                    input=image_bytes,
                    timeout=3,
                )
            else:
                result = subprocess.run(
                    ["xclip", "-selection", "clipboard", "-t", mime],
                    input=image_bytes,
                    timeout=3,
                )

            return result.returncode == 0

        except Exception as e:
            print(f"Error setting image content: {e}", file=sys.stderr)

        return False

    def read_current(self) -> dict:
        """
        Snapshot the current clipboard and return a unified dict:

            {
                "type":    ClipboardType.*,
                "text":    str | None,
                "image":   bytes | None,
                "files":   list[str],
            }
        """
        content_type = self.detect_content_type()

        snapshot = {
            "type":  content_type,
            "text":  None,
            "image": None,
            "files": [],
        }

        if content_type in (ClipboardType.TEXT, ClipboardType.EMOJI):
            snapshot["text"] = self.get_text_content()

        elif content_type == ClipboardType.IMAGE:
            snapshot["image"] = self.get_image_content()

        elif content_type == ClipboardType.FILE:
            snapshot["files"] = self.get_file_uris()
            # Also expose the raw URI text for display purposes
            snapshot["text"] = "\n".join(snapshot["files"])

        return snapshot