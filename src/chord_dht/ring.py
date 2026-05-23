# Duy trì module tương thích ngược cho code cũ import từ chord_dht.ring
# Re-export public API từ các module mới để test/script cũ không phải đổi import

# Import lại các API chính của phần lõi Chord
from .chord import ChordRing, build_default_ring, validate_lookup_batch

# Import lại các hàm xử lý định danh để module ring cũ vẫn dùng được
from .identifiers import hash_identifier, in_clockwise_interval

# Import lại các dataclass để giữ nguyên surface API trước khi tách package
from .models import FingerEntry, LookupResult, Node, ResourceRecord

# Khai báo public API giống module ring cũ để from chord_dht.ring import * hoạt động rõ ràng
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
