"""
Manages a capped in-memory queue of clipboard snapshots.
The queue lives only in RAM — it is empty on every session start.

RULES:

    - Max MAX_SIZE items total (pinned + unpinned). (probably MAX_SiZE = 20)
    - Max buffer size, we don't want to kill our ram
    - New items are inserted at position 0 (most-recent first).
    - When the queue is full and a new item arrives:
        · The oldest *unpinned* item is evicted.
        · If ALL items are pinned the new item is discarded and a
            warning is emitted — the user must unpin something first.
    - Pinned items:
        · Cannot be evicted automatically.
        · Cannot be moved below their current index by new arrivals
            (they stay "frozen" in place while unpinned items shift around them).
        · Can only be removed explicitly via remove() after unpinning.
    - Duplicate detection: if the incoming content is identical to the
        item already at index 0 it is ignored (avoids re-adding on paste).

    Memory limits:
        - Max per text item  : 1 MB
        - Max per image item : 5 MB
        - Max total buffer   : 20 MB
    
    When an item exceeds its per-type limit its raw bytes are discarded
    and only a text preview is kept — the item still appears in the UI
    (marked as truncated) but cannot be pasted back as its original type.
"""

from __future__ import annotations

import hashlib
import sys
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

from .manager import ClipboardType

try:
    from PIL import Image as PilImage
    PILLOW_AVAILABLE = True
except ImportError:
    PILLOW_AVAILABLE = False
    print(
        "[ClipboardHistory] Pillow not found — image thumbnails disabled.",
        file=sys.stderr,
    )

MAX_SIZE = 20
MAX_TEXT_BYTES   = 1  * 1024 * 1024 
MAX_IMAGE_BYTES  = 5  * 1024 * 1024
MAX_BUFFER_BYTES = 20 * 1024 * 1024

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class ClipboardItem:
    """A single entry in the clipboard history."""

    content_type: str
    text: Optional[str] = None
    image:        Optional[bytes] = None
    files:        List[str] = field(default_factory=list)

    timestamp: datetime = field(default_factory=datetime.now)
    pinned:    bool     = False
    truncated: bool = False
    item_id:   str      = field(init=False)

    def __post_init__(self):
        self.item_id = self._compute_id()
    
    #Size
    @property
    def size_bytes(self) -> int:
        pass

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _compute_id(self) -> str:
        """
        Hash of content for a quickly duplicates detection 
        """
        h = hashlib.sha256()
        h.update(self.content_type.encode())
        if self.text:
            h.update(self.text.encode())
        if self.image:
            h.update(self.image)
        for f in self.files:
            h.update(f.encode())
        return h.hexdigest()[:16]

    @property
    def preview(self) -> str:
        if self.content_type == ClipboardType.IMAGE:
            size = f"{len(self.image):,} bytes" if self.image else "?"
            return f"[Image - {size}]"
        if self.content_type == ClipboardType.FILE:
            names = [f.split("/")[-1] for f in self.files]
            if len(names) == 1:
                return f"📄 {names[0]}"
            return f"📄 {names[0]}  (+{len(names)-1} more)"
        if self.content_type == ClipboardType.EMOJI:
            return self.text or ""
        
        text = (self.text or "").strip().replace("\n", " ")
        return text[:120] + ("…" if len(text) > 120 else "")

    @classmethod
    def from_snapshot(cls, snapshot: dict) -> "ClipboardItem":
        return cls(
            content_type = snapshot ["type"],
            text = snapshot.get("text"),
            image = snapshot.get("image"),
            files = snapshot.get("files", []),
        ) 
    
    def to_dict(self) -> dict:
        """
        Serialise to a plain dict (for IPC-JSON transport)
        """
        return {
            "item_id":      self.item_id,
            "content_type": self.content_type,
            "text":         self.text,
            "files":        self.files,
            "has_image":    self.image is not None,
            "preview":      self.preview,
            "timestamp":    self.timestamp.isoformat(),
            "pinned":       self.pinned,
        }
    

# ---------------------------------------------------------------------------
# History queue
# ---------------------------------------------------------------------------

class ClipboardHistory:
    pass