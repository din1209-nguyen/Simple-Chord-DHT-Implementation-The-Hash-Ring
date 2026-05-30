# Cung cấp wrapper ở thư mục gốc để import nhanh API chính của package chord_dht
# Hỗ trợ môi trường chấm bài hoặc demo chạy trực tiếp từ project root

from __future__ import annotations

# Import sys để chỉnh sửa đường dẫn import
import sys

# Import Path để xác định thư mục dự án
from pathlib import Path

# Xác định thư mục gốc dự án
PROJECT_ROOT = Path(__file__).resolve().parent

# Xác định thư mục src chứa package thật
SRC_DIR = PROJECT_ROOT / "src"

# Thêm src vào sys.path khi chưa có
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

# Import lại public API từ package thật
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

# Khai báo public API để import sao cho rõ ràng
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
