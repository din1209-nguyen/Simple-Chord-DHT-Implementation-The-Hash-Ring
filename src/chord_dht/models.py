from __future__ import annotations

# Import dataclass để định nghĩa cấu trúc dữ liệu
from dataclasses import dataclass, field
from typing import Any


# Đóng gói một dòng trong finger table
@dataclass(frozen=True)
class FingerEntry:

    # Lưu chỉ số của finger
    index: int

    # Lưu vị trí start của finger
    start: int

    # Lưu vị trí kết thúc khoảng finger
    interval_end: int

    # Lưu node_id mà finger trỏ tới
    node_id: int

    # Chuyển FingerEntry sang dict để trả về cho API
    def to_dict(self) -> dict[str, int]:
        # Trả về dữ liệu theo dạng dict
        return {
            "index": self.index,
            "start": self.start,
            "interval_end": self.interval_end,
            "node_id": self.node_id,
        }


# Đóng gói trạng thái của một node trong ring
@dataclass
class Node:

    # Lưu định danh node trên vòng
    node_id: int

    # Lưu trạng thái active của node
    active: bool = True

    # Lưu predecessor hiện tại
    predecessor: int | None = None

    # Lưu successor hiện tại
    successor: int | None = None

    # Lưu finger table của node
    finger_table: list[FingerEntry] = field(default_factory=list)

    # Lưu kho resource cục bộ mà node đang giữ
    local_resources: dict[str, ResourceRecord] = field(default_factory=dict)

    # Chuyển Node sang dict để phục vụ hiển thị và API
    def to_dict(self) -> dict[str, Any]:
        # Chuyển finger table sang danh sách dict
        finger_rows = [entry.to_dict() for entry in self.finger_table]

        # Trả về snapshot node theo dạng dict
        return {
            "node_id": self.node_id,
            "active": self.active,
            "predecessor": self.predecessor,
            "successor": self.successor,
            "finger_table": finger_rows,
            "resource_count": len(self.local_resources),
            "resources": [resource.to_dict() for resource in self.local_resources.values()],
        }


# Đóng gói metadata của một tài nguyên trong ring
@dataclass
class ResourceRecord:

    # Lưu id tài nguyên
    resource_id: str

    # Lưu chuỗi SHA-1 digest gốc 40 ký tự hex (resource_id được băm SHA-1)
    hashed_resource_id: str

    # Lưu key băm của tài nguyên (digest mod 2^m, dùng cho Chord routing)
    key: int

    # Lưu owner_id chịu trách nhiệm chính
    owner_id: int

    # Lưu danh sách node giữ bản sao
    replica_node_ids: list[int] = field(default_factory=list)

    # Chuyển ResourceRecord sang dict để trả về cho UI
    def to_dict(self) -> dict[str, int | str]:
        # Trả về metadata dạng dict
        return {
            "resource_id": self.resource_id,
            "hashed_resource_id": self.hashed_resource_id,
            "key": self.key,
            "owner_id": self.owner_id,
            "replica_node_ids": self.replica_node_ids,
        }


# Đóng gói kết quả lookup để trả về UI
@dataclass
class LookupResult:

    # Lưu id người dùng yêu cầu lookup
    requested_id: str

    # Lưu key tương ứng trên vòng
    key: int

    # Lưu owner_id được định tuyến tới
    owner_id: int

    # Lưu node bắt đầu lookup
    start_node_id: int

    # Lưu đường đi qua các node
    path: list[int]

    # Lưu số hop đã đi
    hops: int

    # Lưu log theo từng bước định tuyến
    logs: list[str]

    # Lưu cờ tìm thấy dữ liệu
    found: bool = True

    # Lưu cờ lookup theo key trực tiếp
    direct_key: bool = False

    # Lưu danh sách replica liên quan
    replica_node_ids: list[int] = field(default_factory=list)

    # Chuyển LookupResult sang dict để trả về cho API
    def to_dict(self) -> dict[str, Any]:
        # Trả về dữ liệu lookup theo dạng dict
        return {
            "requested_id": self.requested_id,
            "key": self.key,
            "owner_id": self.owner_id,
            "start_node_id": self.start_node_id,
            "path": self.path,
            "hops": self.hops,
            "logs": self.logs,
            "found": self.found,
            "direct_key": self.direct_key,
            "replica_node_ids": self.replica_node_ids,
        }
