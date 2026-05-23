# Gom API công khai của package mô phỏng Chord DHT vào một điểm import ngắn gọn
# Cho phép nơi khác dùng import ngắn gọn trực tiếp từ chord_dht

# Import phần lõi ring và các hàm tiện ích lookup mặc định
from .chord import ChordRing, build_default_ring, validate_lookup_batch

# Import các hàm xử lý định danh dùng chung cho thuật toán và test
from .identifiers import hash_identifier, in_clockwise_interval

# Import các hàm benchmark để Flask API và script terminal có thể gọi trực tiếp
from .metrics import build_growth_node_sizes, run_current_ring_metrics, run_lookup_metrics

# Import các dataclass dữ liệu để module khác có thể type hint và serialize rõ ràng
from .models import FingerEntry, LookupResult, Node, ResourceRecord

# Import hàm dựng/vẽ topology phục vụ giao diện trực quan hóa
from .visualization import build_topology_graph, save_topology_graph

# Khai báo rõ public API để người đọc biết phần nào được dùng từ bên ngoài package
__all__ = [
    "ChordRing",
    "FingerEntry",
    "LookupResult",
    "Node",
    "ResourceRecord",
    "build_default_ring",
    "build_growth_node_sizes",
    "hash_identifier",
    "in_clockwise_interval",
    "run_current_ring_metrics",
    "run_lookup_metrics",
    "build_topology_graph",
    "save_topology_graph",
    "validate_lookup_batch",
]
