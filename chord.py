from __future__ import annotations

import sys

from pathlib import Path

# Xác định thư mục gốc của dự án
PROJECT_ROOT = Path(__file__).resolve().parent

# Xác định thư mục chứa package chord_dht
SRC_DIR = PROJECT_ROOT / "src"

# Thêm thư mục src vào sys.path khi chạy wrapper từ project root
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from chord_dht.chord import (
    ChordRing,
    FingerEntry,
    LookupResult,
    Node,
    ResourceRecord,
    hash_identifier,
    in_clockwise_interval,
)

# Khai báo public API được re-export từ wrapper
__all__ = [
    "ChordRing",
    "FingerEntry",
    "LookupResult",
    "Node",
    "ResourceRecord",
    "hash_identifier",
    "in_clockwise_interval",
]
