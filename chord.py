# Cung cấp wrapper ở thư mục gốc để import nhanh API chính của package chord_dht
# Hỗ trợ các môi trường chấm bài hoặc demo mở trực tiếp file chord.py từ project root

from __future__ import annotations

import sys
from pathlib import Path

# Xác định thư mục project hiện tại để tìm được thư mục src khi chạy trực tiếp từ root
PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"

# Thêm src vào import path nếu Python chưa nhìn thấy package chord_dht
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

# Import lại public API từ package thật để wrapper này không chứa logic thuật toán
from chord_dht.chord import (
    ChordRing,
    FingerEntry,
    LookupResult,
    Node,
    ResourceRecord,
    build_default_ring,
    hash_identifier,
    in_clockwise_interval,
    validate_lookup_batch,
)

# Khai báo public API để from chord import * vẫn hoạt động rõ ràng
__all__ = [
    "ChordRing",
    "FingerEntry",
    "LookupResult",
    "Node",
    "ResourceRecord",
    "build_default_ring",
    "hash_identifier",
    "in_clockwise_interval",
    "validate_lookup_batch",
]
