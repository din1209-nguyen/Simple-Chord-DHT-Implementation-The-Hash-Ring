from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Mô tả một dòng trong finger table
@dataclass(frozen=True)
class FingerEntry:

    # Lưu vị trí finger trong bảng định tuyến
    index: int

    # Lưu điểm bắt đầu của khoảng định danh finger
    start: int

    # Lưu điểm kết thúc của khoảng định danh finger
    interval_end: int

    # Lưu node_id mà finger trỏ tới
    node_id: int

    # Chuyển đối tượng sang dictionary
    def to_dict(self) -> dict[str, int]:

        # Trả về dữ liệu finger entry dạng dictionary
        return {
            "index": self.index,
            "start": self.start,
            "interval_end": self.interval_end,
            "node_id": self.node_id,
        }

# Mô tả trạng thái một node trong vòng Chord
@dataclass
class Node:

    # Lưu định danh của node trên vòng Chord
    node_id: int

    # Đánh dấu node còn hoạt động hay đã bị lỗi
    active: bool = True

    # Lưu predecessor hiện tại của node
    predecessor: int | None = None

    # Lưu successor hiện tại của node
    successor: int | None = None

    # Lưu bảng finger phục vụ định tuyến nhanh
    finger_table: list[FingerEntry] = field(default_factory=list)

    # Lưu các resource mà node đang giữ cục bộ
    local_resources: dict[str, ResourceRecord] = field(default_factory=dict)

    # Chuyển đối tượng sang dictionary
    def to_dict(self) -> dict[str, Any]:

        # Chuyển từng dòng finger table sang dictionary
        finger_rows = [entry.to_dict() for entry in self.finger_table]

        # Trả về trạng thái node kèm finger table và tài nguyên local
        return {
            "node_id": self.node_id,
            "active": self.active,
            "predecessor": self.predecessor,
            "successor": self.successor,
            "finger_table": finger_rows,
            "resource_count": len(self.local_resources),
            "resources": [resource.to_dict() for resource in self.local_resources.values()],
        }

# Mô tả metadata và replica của tài nguyên
@dataclass
class ResourceRecord:

    # Lưu ID gốc của resource do người dùng hoặc hệ thống tạo
    resource_id: str

    # Lưu giá trị hash đầy đủ của resource_id
    hashed_resource_id: str

    # Lưu khóa resource sau khi đưa vào không gian định danh Chord
    key: int

    # Lưu node owner chịu trách nhiệm chính cho resource
    owner_id: int

    # Lưu danh sách node đang giữ bản sao resource
    replica_node_ids: list[int] = field(default_factory=list)

    # Chuyển đối tượng sang dictionary
    def to_dict(self) -> dict[str, int | str]:

        # Trả về metadata resource kèm owner và danh sách replica
        return {
            "resource_id": self.resource_id,
            "hashed_resource_id": self.hashed_resource_id,
            "key": self.key,
            "owner_id": self.owner_id,
            "replica_node_ids": self.replica_node_ids,
        }

# Mô tả kết quả truy vấn tài nguyên
@dataclass
class LookupResult:

    # Lưu ID resource được yêu cầu lookup
    requested_id: str

    # Lưu khóa định danh đã dùng để route lookup
    key: int

    # Lưu owner được tìm thấy sau khi định tuyến
    owner_id: int

    # Lưu node bắt đầu truy vấn lookup
    start_node_id: int

    # Lưu đường đi qua các node trong quá trình lookup
    path: list[int]

    # Lưu số hop của truy vấn lookup
    hops: int

    # Lưu log chi tiết từng bước định tuyến
    logs: list[str]

    # Đánh dấu resource có được tìm thấy tại owner hay không
    found: bool = True

    # Đánh dấu lookup có dùng trực tiếp khóa số hay không
    direct_key: bool = False

    # Lưu danh sách replica đi kèm kết quả lookup
    replica_node_ids: list[int] = field(default_factory=list)

    # Chuyển đối tượng sang dictionary
    def to_dict(self) -> dict[str, Any]:

        # Trả về kết quả lookup kèm đường đi và log từng hop
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
