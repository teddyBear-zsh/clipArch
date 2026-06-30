"""
Clipboard History Module
author: teddyBear
license: MIT

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
from io import BytesIO

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

MAX_SIZE = 20 #max items if the queue
MAX_TEXT_BYTES   = 1  * 1024 * 1024 # 1 mb x text
MAX_IMAGE_BYTES  = 5  * 1024 * 1024 # 5 mb x image
MAX_BUFFER_BYTES = 20 * 1024 * 1024 # 20 mb total buffer

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
            "truncated":    self.truncated,
            "size_bytes":   self.size_bytes,
        }
    

# ---------------------------------------------------------------------------
# History queue
# ---------------------------------------------------------------------------

class ClipboardHistory:
    """
    Ordered list of ClipboardItems, most-recent first.
    """

    def __init__(
        self,
        max_size: int = MAX_SIZE,
        max_text_bytes: int = MAX_TEXT_BYTES,
        max_image_bytes: int = MAX_IMAGE_BYTES,
        max_buffer_bytes: int = MAX_BUFFER_BYTES    
    ):
        self._max_size = max_size
        self._max_text_bytes = max_text_bytes
        self._max_image_bytes = max_image_bytes
        self._max_buffer_bytes = max_buffer_bytes

        self._items: List[ClipboardItem] = []
    

    # ---------------------------------------------------------------------------
    # Read only properties
    # ---------------------------------------------------------------------------

    @property
    def items(self) -> List[ClipboardItem]:
        return list(self._items)
    
    @property
    def count(self) -> int:
        return len(self._items)
    
    @property
    def is_full(self) -> bool:
        return len(self._items) >= self._max_size
    
    @property
    def buffer_bytes(self) -> int:
        """Current total RAM used by all items"""
        return sum(it.size_bytes for it in self._items)
    

    #-------------------------------

    def add(self, snapshot: dict) -> Optional[ClipboardItem]:
        """ Validate, sanitize and insert a new clipboard snapshot"""
        if snapshot.get("type") == ClipboardType.UNKNOWN:
            return None
        
        item = ClipboardItem.from_snapshot(snapshot)

        #avoid duplicated
        if self.items and self.items[0].item_id == item.item_id:
            return None
        
        #per item limits
        item = self._apply_item_limits(item)

        #global buffer ceiling
        if not self._ensure_buffer_space(item.size_bytes):
            print(
                f"[ClipboardHistory] item dropped: buffes full"
                f"({self.buffer_bytes/(1024*1024):.1f} MB used)"
                "and all itemas are pinned.",
                file=sys.stderr,
            )
            return None
        
        #count limit
        if self.is_full:
            evicted = self._evict_oldest_unpinned()
            if evicted is None:
                print(
                    f"[ClipboardHistory] item dropped: queue full"
                    "and all items are pinned. Unpin something first.",
                    file=sys.stderr,
                )
                return None
        self._items.insert(0, item)
        return item

    #-------------------------------
    # Pin / unpin / toggle
    #-------------------------------

    def pin(self, item_id: str) -> bool:
        "Pin an item. True if found"
        item = self._find(item_id)
        if item: 
            item.pinned = True
            return True
        return False
    
    def unpin(self, item_id: str) -> bool:
        """unpin an item. True if found"""
        item = self._find(item_id)
        if item:
            item.pinned = False
            return True
        return False
    
    def toggle_pin(self, item_id: str) -> bool:
        """Toggle pin state. None if not found."""
        item = self._find(item_id)
        if item is None:
            return None
        item.pinned = not item.pinned
        return item.pinned
    
    #-------------------------------
    # Remove / clear
    #-------------------------------

    def remove(self, item_id: str) -> bool:
        """Remove by id. Pinned items can be removed explicitly."""
        for i, item in enumerate(self._items):
            if item.item_id == item_id:
                del self._items[i]
                return True
        return False

    def clear(self, include_pinned: bool = False) -> int:
        """Clear history. By default pinned items are preserved.
        Returns number of items removed."""
        if include_pinned:
            removed = len(self._items)
            self._items.clear()
            return removed
        before = len(self._items)
        self._items = [it for it in self._items if it.pinned]
        return before - len(self._items)

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def get(self, item_id: str) -> Optional[ClipboardItem]:
        return self._find(item_id)

    def filter_by_type(self, content_type: str) -> List[ClipboardItem]:
        return [it for it in self._items if it.content_type == content_type]

    def to_dict_list(self) -> List[dict]:
        return [it.to_dict() for it in self._items]

    def stats(self) -> dict:
        """Buffer usage summary — useful for debugging / status bar."""
        return {
            "count":            self.count,
            "max_size":         self._max_size,
            "buffer_bytes":     self.buffer_bytes,
            "max_buffer_bytes": self._max_buffer_bytes,
            "buffer_mb":        round(self.buffer_bytes / 1024 / 1024, 2),
            "pinned":           sum(1 for it in self._items if it.pinned),
            "truncated":        sum(1 for it in self._items if it.truncated),
        }

    #-------------------------------
    # HELPERS
    #---------------------------------

    def _find(self, item_id: str) -> Optional[ClipboardItem]:
        for item in self._items:
            if item.item_id == item_id:
                return item
        return None
    
    def _ensure_buffer_space(self, incoming_bytes: int) -> bool:
        """
        Evict oldest unpinned items until the buffer has room for
        `incoming_bytes`. 
        """
        while self.buffer_bytes + incoming_bytes > self._max_buffer_bytes:
            evicted = self._evict_oldest_unpinned()
            if evicted is None:
                return False
        return True
    
    def _evict_oldest_unpinned(self) -> Optional[ClipboardItem]:
        """
        Remove the oldest unpinned item from the queue.
        """
        for i in range(len(self._items) -1 -1, -1):
            if not self._items[i].pinned:
                return self._items.pop(i)
        return None
    
    #Thumbnail dimensions for oversized images
    THUMBNAIL_SIZE = (200, 120)

    def _apply_item_limits(self, item: ClipboardItem) -> ClipboardItem:
        """
        Apply per-item size limits
        Truncate the item if it exceeds its per-type limit

        If Pillow is available -> replace raw bytes with a small thumbnail
        """
        if item.content_type == ClipboardType.IMAGE:
            if item.image and len(item.image) > self._max_image_bytes:
                limit_mb = self._max_image_bytes/(1024*1024)
                actual_mb = len(item.image)/(1024*1024)
                print(
                    f"[ClipboardHistory] Image exceeds {limit_mb:.0f} MB limit"
                    f"({actual_mb:.1f} MB)",
                    file=sys.stderr,
                )
                item.image = self._make_thumbnail(item.image)
                item.truncated = True #disable pasting
        
        elif item.content_type in (ClipboardType.TEXT, ClipboardType.EMOJI):
            if item.text and len(item.text.encode("utf-8")) > self._max_text_bytes:
                limit_mb = self._max_text_bytes/(1024*1024)
                print(
                    f"[ClipboardHistory] Text exceeds {limit_mb:.0f} MB limit"
                    "Truncating to preview only",
                    file=sys.stderr,
                )
                item.text = item.text[:500] + "... [truncated]"
                item.truncated = True

        return item

    def _make_thumbnail(self,image_bytes: bytes) -> Optional[bytes]:
        """"
        Generate a small PNG thumbnail from raw image bytes using Pillow.
        Returns the thumbnail bytes, or None if Pillow is unavailable or
        the image cannot be decoded.

        """

        if not PILLOW_AVAILABLE:
            print(
                "[ClipboardHistory] Pillow not available,  thumbnail skipped.",
                file=sys.stderr,
            )
            return  None
        
        try:
            img = PilImage.open(self.THUMBNAIL_SIZE)
            img.thumbnail(self.THUMBNAIL_SIZE)
            out = BytesIO()
            img.save(out, format="PNG")
            thumb_bytes = out.getvalue()
            print(
                f"[ClipboardHistory] Thumbnail generated"
                f"({len(thumb_bytes)/ 1024:.1f} KB)",
                file=sys.stderr,
            )
            return thumb_bytes
        except Exception as e:
            print(
                f"[ClipboardHistory] Failed to generate thumbnail: {e}",
                file=sys.stderr,
            )
            return None
    
    def _ensure_buffer_space(self, incoming_bytes: int) -> bool:
        """
        Evict oldest unpinned items until the buffer has room for
        incoming_bytes. Returns False only if no moere space can be 
        freed (all remaining items are pinned)
        """

        while self.buffer_bytes + incoming_bytes > self._max_buffer_bytes:
            evicted = self._evict_oldest_unpinned()
            if evicted is None:
                return False
        return True
    
    #-------------------------------
    # Dunder helpers
    #------------------------------

    def __len__(self):
        return len(self._items)
    
    def __iter__(self):
        return iter(self._items)
    
    def __repr__(self):
        used_mb = self.buffer_bytes / (1024*1024)
        max_mb = self._max_buffer_bytes / (1024*1024)
        pinned = sum(1 for it in self._items if it.pinned)

        return(
            f"<ClipboardHistory"
            f"count={self.count}/{self._max_size}"
            f"buffer={used_mb:.1f}/{max_mb:.0f} MB)"
            f"pinned={pinned}>"
        )