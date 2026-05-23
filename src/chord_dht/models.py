# Định nghĩa các dataclass biểu diễn dữ liệu của mô phỏng Chord DHT
# Tách phần model khỏi thuật toán để chord.py tập trung vào logic ring và lookup

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# Biểu diễn một dòng trong Finger Table của node
# Lưu start, interval_end và node successor mà dòng finger trỏ tới
@dataclass(frozen=True)
class FingerEntry:

    index: int
    start: int
    interval_end: int
    node_id: int

    # Chuyển FingerEntry sang dict để Flask jsonify và frontend render được
    def to_dict(self) -> dict[str, int]:
        # Trả về đầy đủ các trường cần hiển thị trong bảng Finger Table
        return {
            "index": self.index,
            "start": self.start,
            "interval_end": self.interval_end,
            "node_id": self.node_id,
        }


# Biểu diễn trạng thái mô phỏng của một peer trong Chord ring
# Lưu cờ active, láng giềng trực tiếp và Finger Table hiện tại của node
@dataclass
class Node:

    node_id: int
    active: bool = True
    predecessor: int | None = None
    successor: int | None = None
    finger_table: list[FingerEntry] = field(default_factory=list)
    local_resources: dict[str, ResourceRecord] = field(default_factory=dict)

    # Chuyển Node sang dict để API trả trạng thái node cho frontend
    def to_dict(self) -> dict[str, Any]:
        # Chuyển từng FingerEntry sang dict vì jsonify không tự serialize dataclass lồng nhau
        finger_rows = [entry.to_dict() for entry in self.finger_table]

        # Trả về snapshot hiện tại của node, gồm cả liên kết predecessor/successor
        return {
            "node_id": self.node_id,
            "active": self.active,
            "predecessor": self.predecessor,
            "successor": self.successor,
            "finger_table": finger_rows,
            "resource_count": len(self.local_resources),
            "resources": [resource.to_dict() for resource in self.local_resources.values()],
        }


# Biểu diễn một resource sau khi được băm vào vòng Chord
# Lưu resource_id gốc, key trên vòng và node owner hiện tại
@dataclass
class ResourceRecord:

    resource_id: str
    key: int
    owner_id: int
    replica_node_ids: list[int] = field(default_factory=list)

    # Chuyển ResourceRecord sang dict để bảng resource hiển thị đúng dữ liệu
    def to_dict(self) -> dict[str, int | str]:
        # Trả về đúng ba trường mà frontend cần: tên resource, key băm và owner
        return {
            "resource_id": self.resource_id,
            "key": self.key,
            "owner_id": self.owner_id,
            "replica_node_ids": self.replica_node_ids,
        }


# Biểu diễn kết quả của một lần lookup trong Chord ring
# Lưu owner, path, số hop và log giải thích từng bước định tuyến
@dataclass
class LookupResult:

    requested_id: str
    key: int
    owner_id: int
    start_node_id: int
    path: list[int]
    hops: int
    logs: list[str]
    found: bool = True
    direct_key: bool = False
    replica_node_ids: list[int] = field(default_factory=list)

    # Chuyển LookupResult sang dict để API trả kết quả lookup cho frontend
    def to_dict(self) -> dict[str, Any]:
        # Giữ nguyên path và logs để UI có thể vẽ route và in từng hop
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
