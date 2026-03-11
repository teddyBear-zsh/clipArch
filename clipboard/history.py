"""
Manages a capped in-memory queue of clipboard snapshots.
The queue lives only in RAM — it is empty on every session start.

RULES:

    - Max MAX_SIZE items total (pinned + unpinned). (probably MAX_SiZE = 20)
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

"""

from __future__ import annotations

import hashlib
import sys
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

from .manager import ClipboardType

MAX_SIZE = 20

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
    item_id:   str      = field(init=False)

    def __post_init__(self):
        self.item_id = self._compute_id()
    

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    #TODO: Define Helper Functions
    """
    posible functions: 
    *compute id
    *preview
    """

    def _compute_id(self) -> str:
        pass

    