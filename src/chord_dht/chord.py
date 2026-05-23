# Phần lõi mô phỏng Chord DHT: quản lý node, resource, Finger Table,
# định tuyến lookup và các thao tác churn như thêm/sửa/kill node

from __future__ import annotations

import bisect
import random
from typing import Any, Iterable

from .identifiers import hash_identifier, in_clockwise_interval
from .models import FingerEntry, LookupResult, Node, ResourceRecord


# Quản lý toàn bộ trạng thái mô phỏng của mạng lưới Chord DHT trong một process
# Gom nhóm toàn bộ dữ liệu (node, resource, failed nodes) để dễ dàng kiểm thử và làm UI
class ChordRing:

    # Khởi tạo vòng Chord, thiết lập không gian định danh và các cấu trúc dữ liệu lưu trữ
    def __init__(
        self,
        m: int = 16,
        seed: int = 61,
        replication_count: int = 3,
    ) -> None:
        # Kiểm tra m bit để đảm bảo không gian định danh hợp lệ (thường từ 1 đến 160 theo SHA-1)
        if not 1 <= m <= 160:
            raise ValueError("m must be between 1 and 160")

        # Lưu trữ cấu hình cơ bản của vòng
        self.m = m
        self.identifier_space = 2**m  # Tổng số vị trí tối đa trên vòng (ví dụ m=16 -> 65536)
        self.seed = seed
        self.replication_count = self._validate_replication_count(replication_count)
        self.communication_layer = "HTTP/REST via Flask API"

        # Khởi tạo các cấu trúc dữ liệu lưu trữ trạng thái mạng
        self.nodes: dict[int, Node] = {}             # Lưu toàn bộ node (cả đang sống và đã chết)
        self.failed_nodes: set[int] = set()          # Tập hợp ID của các node đã chết/tắt
        self.resources: dict[str, ResourceRecord] = {}  # Lưu tài nguyên đang có trong mạng
        
        # Bộ sinh số ngẫu nhiên theo seed để kết quả mô phỏng luôn lặp lại được giống nhau
        self._rng = random.Random(seed)

    # Kiểm tra số replica cấu hình cho mỗi resource
    def _validate_replication_count(self, replication_count: int) -> int:
        # Ép kiểu sang int để nhận được cả giá trị số gửi từ form/API
        replicas = int(replication_count)

        # Không cho phép số replica âm vì không có ý nghĩa trong mô phỏng lưu trữ
        if replicas < 0:
            raise ValueError("replication_count must be non-negative")

        # Trả về số replica hợp lệ để các bước copy dữ liệu dùng thống nhất
        return replicas

    # Lấy danh sách các ID của node đang hoạt động (active), sắp xếp theo thứ tự tăng dần
    @property
    def active_node_ids(self) -> list[int]:
        # Duyệt qua dict nodes, chỉ lấy những node có cờ active=True và sắp xếp chúng
        return sorted(node_id for node_id, node in self.nodes.items() if node.active)

    # Thiết lập lại toàn bộ mạng Chord từ đầu: tạo node, dựng cấu trúc (stabilize) và phân phối resource
    def initialize_network(
        self,
        node_count: int = 50,
        resource_count: int = 1000,
        *,
        seed: int | None = None,
        replication_count: int | None = None,
    ) -> dict[str, Any]:
        # Nếu có truyền seed mới, cập nhật lại bộ sinh số ngẫu nhiên
        if seed is not None:
            self.seed = seed
            self._rng = random.Random(seed)
        if replication_count is not None:
            self.replication_count = self._validate_replication_count(replication_count)

        # Ràng buộc dữ liệu đầu vào để tránh sinh lỗi trước khi xóa state cũ
        if node_count < 1:
            raise ValueError("node_count must be at least 1")
        if resource_count < 0:
            raise ValueError("resource_count must be non-negative")
        if node_count > self.identifier_space:
            raise ValueError("node_count cannot exceed the identifier space")

        # Xóa toàn bộ dữ liệu của phiên chạy trước để lấy không gian sạch
        self.nodes.clear()
        self.failed_nodes.clear()
        self.resources.clear()

        # Sinh ra số lượng ID duy nhất bằng hàm hỗ trợ, sau đó khởi tạo đối tượng Node
        for node_id in self._generate_unique_ids("node", node_count):
            self.nodes[node_id] = Node(node_id=node_id)

        # Ổn định mạng để thiết lập láng giềng (predecessor/successor) và Finger Table
        self.stabilize()

        # Tạo và phân phối tài nguyên ảo vào mạng
        for index in range(1, resource_count + 1):
            # Tạo tên tài nguyên có format chuẩn (vd: resource-0001)
            resource_id = f"resource-{index:04d}"

            # Băm tên ra vị trí (key) trên vòng
            key = hash_identifier(resource_id, self.m)  

            # Định tuyến put qua overlay Chord để tìm owner, không hỏi trực tiếp bảng trung tâm
            route = self._route_key(key, operation="Put", requested_id=resource_id)
            owner_id = route["owner_id"]
            
            # Lưu tài nguyên vào index mô phỏng và kho local của node owner
            resource = ResourceRecord(resource_id, key, owner_id)
            self.resources[resource_id] = resource
            self._place_resource_copies(resource)

        # Trả về bản tóm tắt trạng thái của mạng sau khi khởi tạo xong
        return self.summary(sample_size=None)

    # Sinh ra một danh sách các ID duy nhất dựa trên chuỗi tiền tố và seed để đảm bảo tính tái lập
    def _generate_unique_ids(self, prefix: str, count: int) -> list[int]:
        generated: list[int] = []
        used: set[int] = set()
        attempt = 0

        # Giới hạn số lần lặp tối đa để chống kẹt vòng lặp vô hạn nếu không gian ID quá hẹp
        limit = max(count * 1000, self.identifier_space * 2)

        # Lặp cho đến khi sinh đủ số lượng ID yêu cầu hoặc chạm ngưỡng giới hạn
        while len(generated) < count and attempt < limit:
            raw = f"{prefix}:{self.seed}:{attempt}"  # Tạo chuỗi đầu vào theo attempt
            candidate = hash_identifier(raw, self.m)  # Băm chuỗi để lấy ID
            attempt += 1

            # Bỏ qua nếu ID sinh ra bị trùng với ID đã có
            if candidate in used:
                continue
            
            # Ghi nhận ID hợp lệ
            used.add(candidate)
            generated.append(candidate)

        # Nếu thoát vòng lặp mà chưa đủ số lượng, báo lỗi hệ thống
        if len(generated) != count:
            raise RuntimeError("Unable to generate enough unique identifiers")
        return generated

    # Tìm node kế nhiệm (successor) cho một khóa (key) bất kỳ trên vòng định danh
    def find_successor(self, key: int) -> int:
        active_ids = self.active_node_ids
        if not active_ids:
            raise RuntimeError("No active nodes are available")

        # Chuẩn hóa khóa để đảm bảo nó nằm gọn trong vòng m-bit (0 đến 2^m - 1)
        normalized_key = key % self.identifier_space

        # Dùng thuật toán tìm kiếm nhị phân (bisect_left) để tìm vị trí node >= normalized_key nhanh chóng
        position = bisect.bisect_left(active_ids, normalized_key)
        
        # Nếu position vọt qua độ dài mảng (nghĩa là key nằm sau node lớn nhất),
        # vòng định danh quấn lại và trả về node nhỏ nhất (đầu mảng)
        if position == len(active_ids):
            return active_ids[0]
        
        # Trả về ID của node tìm được
        return active_ids[position]

    # Tìm successor của key bằng cách đi theo các liên kết successor trên vòng
    def _find_successor_by_links(
        self,
        key: int,
        *,
        start_node_id: int | None = None,
    ) -> int:
        active_ids = self.active_node_ids

        # Nếu vòng không có node active thì không thể định tuyến tới successor
        if not active_ids:
            raise RuntimeError("No active nodes are available")

        # Chọn node bắt đầu: nếu không truyền thì dùng node active đầu tiên của mô phỏng
        current = active_ids[0] if start_node_id is None else int(start_node_id)
        if current not in self.nodes or not self.nodes[current].active:
            raise ValueError(f"Start node {current} is not active")

        # Chuẩn hóa key về không gian định danh m-bit trước khi đi trên vòng
        normalized_key = int(key) % self.identifier_space

        # Đi tối đa một vòng để tránh lặp vô hạn nếu successor pointer bị hỏng
        for _ in range(len(active_ids) + 1):
            if self._node_owns_key(current, normalized_key):
                return current

            successor = self.nodes[current].successor
            if successor is None or successor not in self.nodes or not self.nodes[successor].active:
                raise RuntimeError(f"Node {current} has no active successor")

            if in_clockwise_interval(normalized_key, current, successor, include_end=True):
                return successor

            current = successor

        raise RuntimeError("Successor link walk exceeded one full ring")

    # Kiểm tra tính hợp lệ của ID do người dùng nhập vào thông qua UI hoặc API
    def _validate_identifier(self, value: int) -> int:
        node_id = int(value)

        # Node ID nhập tay bắt buộc phải nằm trong giới hạn không gian định danh,
        # không dùng phép chia lấy dư để bắt người dùng phải nhập đúng
        if not 0 <= node_id < self.identifier_space:
            raise ValueError(
                f"node_id must be between 0 and {self.identifier_space - 1}"
            )
        return node_id

    # Sinh tự động một ID trống chưa được sử dụng trong trường hợp thêm node mà không chỉ định ID
    def _next_available_node_id(self) -> int:
        # Thử dần các con số kết hợp với cấu trúc hash để chọn ra một ID ngẫu nhiên hợp lệ
        for attempt in range(self.identifier_space):
            candidate = hash_identifier(f"manual-node:{self.seed}:{attempt}", self.m)
            # Nếu ID băm ra chưa tồn tại trong danh sách quản lý, sử dụng luôn ID này
            if candidate not in self.nodes:
                return candidate
        raise RuntimeError("No free node identifier is available")

    # Thêm một node mới vào mạng hoặc kích hoạt lại một node đã từng bị tắt (kill)
    def add_node(self, node_id: int | None = None) -> dict[str, Any]:
        # Nếu người dùng không truyền ID, tự sinh một ID trống. Nếu có, kiểm tra tính hợp lệ của nó
        new_node_id = (
            self._next_available_node_id()
            if node_id is None
            else self._validate_identifier(node_id)
        )

        # Nếu ID đã tồn tại và node đang chạy, báo lỗi để chặn trùng lặp
        if new_node_id in self.nodes and self.nodes[new_node_id].active:
            raise ValueError(f"Node {new_node_id} already exists")

        # Xử lý logic tạo hoặc bật lại node:
        if new_node_id in self.nodes:
            # Node cũ từng bị tắt -> bật lại cờ active
            self.nodes[new_node_id].active = True
        else:
            # Node hoàn toàn mới -> khởi tạo object
            self.nodes[new_node_id] = Node(node_id=new_node_id)
            
        # Xóa ID này khỏi danh sách node chết (nếu có)
        self.failed_nodes.discard(new_node_id)

        # Mạng thay đổi cấu trúc nên bắt buộc phải gọi stabilize để vẽ lại bản đồ định tuyến
        stabilize_report = self.stabilize()
        
        return {
            "node_id": new_node_id,
            "active_nodes": stabilize_report["active_nodes"],
            "message": f"Node {new_node_id} added and network stabilized successfully.",
        }

    # Cập nhật (đổi) ID của một node đang hoạt động, tương đương với việc di chuyển vị trí node trên vòng
    def update_node(self, old_node_id: int, new_node_id: int) -> dict[str, Any]:
        # Chuẩn hóa đầu vào
        old_id = self._validate_identifier(old_node_id)
        new_id = self._validate_identifier(new_node_id)

        # Các bước xác thực trạng thái trước khi cập nhật
        if old_id not in self.nodes:
            raise ValueError(f"Node {old_id} does not exist")
        if not self.nodes[old_id].active:
            raise ValueError(f"Node {old_id} is inactive")
        if new_id != old_id and new_id in self.nodes and self.nodes[new_id].active:
            raise ValueError(f"Node {new_id} already exists")

        # Trả về kết quả luôn nếu người dùng cập nhật ID mới trùng với ID cũ
        if new_id == old_id:
            return {
                "old_node_id": old_id,
                "new_node_id": new_id,
                "active_nodes": len(self.active_node_ids),
                "message": "Node ID is unchanged.",
            }

        # Cách mô phỏng đổi ID: Xóa node ở vị trí cũ và tạo một node mới hoàn toàn tại vị trí mới
        del self.nodes[old_id]
        self.failed_nodes.discard(old_id)
        self.nodes[new_id] = Node(node_id=new_id)
        self.failed_nodes.discard(new_id)

        # Tái cân bằng lại toàn bộ mạng lưới sau khi dời vị trí
        stabilize_report = self.stabilize()
        
        return {
            "old_node_id": old_id,
            "new_node_id": new_id,
            "active_nodes": stabilize_report["active_nodes"],
            "message": f"Node {old_id} updated to {new_id} and network stabilized successfully.",
        }

    # Thêm một tài nguyên (resource) mới vào mạng và gán cho node quản lý (owner) phù hợp
    def add_resource(self, resource_id: str) -> dict[str, Any]:
        # Cắt bỏ khoảng trắng dư thừa để định dạng chuẩn
        normalized_id = str(resource_id).strip()
        
        # Xác thực đầu vào
        if not normalized_id:
            raise ValueError("resource_id is required")
        if normalized_id in self.resources:
            raise ValueError(f"Resource {normalized_id} already exists")

        # Băm tên tài nguyên thành key rồi định tuyến put qua Finger Table để tìm owner
        key = hash_identifier(normalized_id, self.m)
        route = self._route_key(key, operation="Put", requested_id=normalized_id)
        owner_id = route["owner_id"]
        resource = ResourceRecord(normalized_id, key, owner_id)
        self.resources[normalized_id] = resource
        self._place_resource_copies(resource)
        
        return {
            "resource": self.resources[normalized_id].to_dict(),
            "put_path": route["path"],
            "put_hops": route["hops"],
            "put_logs": route["logs"],
            "message": f"Resource {normalized_id} added successfully.",
        }

    # Đổi tên (ID) của một tài nguyên, băm lại khóa mới và chuyển tài nguyên cho node quản lý mới nếu cần
    def update_resource(self, old_resource_id: str, new_resource_id: str) -> dict[str, Any]:
        # Chuẩn hóa dữ liệu đầu vào
        old_id = str(old_resource_id).strip()
        new_id = str(new_resource_id).strip()

        # Kiểm tra điều kiện bắt buộc
        if not old_id:
            raise ValueError("old_resource_id is required")
        if not new_id:
            raise ValueError("new_resource_id is required")
        if old_id not in self.resources:
            raise ValueError(f"Resource {old_id} does not exist")
        if new_id != old_id and new_id in self.resources:
            raise ValueError(f"Resource {new_id} already exists")

        # Bỏ qua các bước xử lý nặng nếu ID không thực sự thay đổi
        if new_id == old_id:
            return {
                "resource": self.resources[old_id].to_dict(),
                "message": "Resource ID is unchanged.",
            }

        # Xóa record cũ khỏi index mô phỏng và khỏi mọi bản local/replica cũ
        self.resources.pop(old_id)
        self._remove_resource_copies(old_id)
        
        # Băm tên mới rồi định tuyến put qua Finger Table để tìm owner mới
        key = hash_identifier(new_id, self.m)
        route = self._route_key(key, operation="Put", requested_id=new_id)
        owner_id = route["owner_id"]
        resource = ResourceRecord(new_id, key, owner_id)
        self.resources[new_id] = resource
        self._place_resource_copies(resource)
        
        return {
            "old_resource_id": old_id,
            "resource": self.resources[new_id].to_dict(),
            "put_path": route["path"],
            "put_hops": route["hops"],
            "put_logs": route["logs"],
            "message": f"Resource {old_id} updated to {new_id} successfully.",
        }

    # Xóa một tài nguyên khỏi hệ thống lưu trữ của vòng Chord
    def delete_resource(self, resource_id: str) -> dict[str, Any]:
        # Chuẩn hóa và kiểm tra sự tồn tại của resource
        normalized_id = str(resource_id).strip()
        if not normalized_id:
            raise ValueError("resource_id is required")
        if normalized_id not in self.resources:
            raise ValueError(f"Resource {normalized_id} does not exist")

        # Định tuyến delete tới owner hiện tại trước khi xóa dữ liệu khỏi các bản copy
        route = self._route_key(
            self.resources[normalized_id].key,
            operation="Delete",
            requested_id=normalized_id,
        )

        # Hàm pop() vừa giúp xóa phần tử khỏi index, vừa trả về giá trị của nó để in ra message
        removed = self.resources.pop(normalized_id)
        self._remove_resource_copies(normalized_id)
        
        return {
            "resource": removed.to_dict(),
            "delete_path": route["path"],
            "delete_hops": route["hops"],
            "delete_logs": route["logs"],
            "message": f"Resource {normalized_id} deleted successfully.",
        }

    # Ổn định lại toàn bộ mạng lưới: cập nhật láng giềng (pre/succ), xây dựng lại Finger Table và phân chia lại tài nguyên
    def stabilize(self) -> dict[str, Any]:
        # Lấy danh sách ID đã được sắp xếp tăng dần
        active_ids = self.active_node_ids
        if not active_ids:
            return {"active_nodes": 0, "message": "No active nodes are available."}

        # Bước 1: Nối vòng cho tất cả các node
        for position, node_id in enumerate(active_ids):
            node = self.nodes[node_id]
            # Node trước đó trong mảng chính là predecessor
            node.predecessor = active_ids[position - 1]
            # Node kế tiếp là successor, dùng modulo để quấn vòng lại nếu ở cuối mảng
            node.successor = active_ids[(position + 1) % len(active_ids)]

        # Bước 2: Tính Finger Table sau khi toàn bộ successor/predecessor đã ổn định
        for node_id in active_ids:
            node = self.nodes[node_id]
            # Tính toán và gán lại Finger table dựa trên vị trí mới
            node.finger_table = self._build_finger_table(node_id)

        # Bước 3: Cập nhật lại quyền sở hữu tài nguyên cho đúng với topology hiện tại
        for resource in self.resources.values():
            route = self._route_key(
                resource.key,
                operation="Stabilize",
                requested_id=resource.resource_id,
            )
            resource.owner_id = route["owner_id"]
            resource.replica_node_ids = self._replica_nodes_for_owner(resource.owner_id)
        self._rebuild_local_resource_storage()

        return {
            "active_nodes": len(active_ids),
            "message": "Network stabilized successfully.",
        }

    # Đồng bộ kho local của từng node từ index mô phỏng toàn cục.
    # Index toàn cục phục vụ UI/test, còn local_resources mô phỏng dữ liệu thật nằm ở owner node.
    def _rebuild_local_resource_storage(self) -> None:
        for node in self.nodes.values():
            node.local_resources.clear()

        for resource in self.resources.values():
            self._place_resource_copies(resource)

    # Tính danh sách node replica đứng sau owner trên vòng Chord
    def _replica_nodes_for_owner(self, owner_id: int) -> list[int]:
        active_ids = self.active_node_ids

        # Nếu owner không còn active hoặc tắt replication thì không tạo replica
        if owner_id not in active_ids or self.replication_count == 0:
            return []

        # Xác định vị trí owner trong danh sách active đã sắp xếp theo vòng định danh
        owner_position = active_ids.index(owner_id)

        # Giới hạn số replica để không vượt quá số node còn lại trên vòng
        replica_total = min(self.replication_count, max(0, len(active_ids) - 1))

        # Chọn lần lượt các successor kế tiếp làm nơi giữ bản sao
        return [
            active_ids[(owner_position + offset) % len(active_ids)]
            for offset in range(1, replica_total + 1)
        ]

    # Gom các node đang giữ bản copy của một resource gồm owner và replica
    def _copy_holder_ids(self, resource: ResourceRecord) -> list[int]:
        # Dùng dict.fromkeys để loại trùng nhưng vẫn giữ thứ tự owner trước replica
        holders = [resource.owner_id, *resource.replica_node_ids]
        return list(dict.fromkeys(node_id for node_id in holders if node_id in self.nodes))

    # Xóa mọi bản copy local của một resource khỏi tất cả node
    def _remove_resource_copies(self, resource_id: str) -> None:
        # Duyệt cả node active và inactive để dọn sạch dữ liệu cũ trong mô phỏng
        for node in self.nodes.values():
            node.local_resources.pop(resource_id, None)

    # Đặt resource vào owner và các replica hiện tại theo cấu hình replication_count
    def _place_resource_copies(self, resource: ResourceRecord) -> None:
        # Tính lại replica set mỗi lần owner thay đổi hoặc topology thay đổi
        resource.replica_node_ids = self._replica_nodes_for_owner(resource.owner_id)
        self._sync_resource_copies(resource)

    # Đồng bộ dữ liệu local để chỉ owner/replica hợp lệ đang giữ resource
    def _sync_resource_copies(self, resource: ResourceRecord) -> None:
        # Xóa bản cũ trước để tránh node không còn là replica vẫn giữ dữ liệu
        self._remove_resource_copies(resource.resource_id)

        # Ghi lại resource vào owner và các node replica còn active
        for node_id in self._copy_holder_ids(resource):
            node = self.nodes[node_id]
            if node.active:
                node.local_resources[resource.resource_id] = resource

    # Xây dựng bảng định tuyến (Finger Table) cho một node cụ thể dựa trên khoảng nhảy lũy thừa của 2
    def _build_finger_table(self, node_id: int) -> list[FingerEntry]:
        table: list[FingerEntry] = []

        # Chord định nghĩa m dòng (entry) cho Finger Table
        for index in range(1, self.m + 1):
            # Tính bước nhảy theo lũy thừa của 2 (2^0, 2^1, 2^2, ...)
            jump = 2 ** (index - 1)
            # Điểm bắt đầu (start) trên vòng
            start = (node_id + jump) % self.identifier_space
            # Điểm kết thúc của khoảng chịu trách nhiệm cho finger này
            interval_end = (node_id + 2**index) % self.identifier_space

            # Thêm thông tin dòng định tuyến vào mảng
            table.append(
                FingerEntry(
                    index=index,
                    start=start,
                    interval_end=interval_end,
                    # Node đích của finger này chính là successor của điểm start tìm bằng successor links
                    node_id=self._find_successor_by_links(start, start_node_id=node_id),
                )
            )

        return table

    # Vô hiệu hóa một node đang hoạt động để mô phỏng sự cố mạng hoặc node rời đi (churn)
    def kill_node(self, node_id: int) -> dict[str, Any]:
        # Kiểm tra rào cản lỗi
        if node_id not in self.nodes:
            raise ValueError(f"Node {node_id} does not exist")
        if not self.nodes[node_id].active:
            raise ValueError(f"Node {node_id} is already inactive")
        if len(self.active_node_ids) <= 1:
            raise ValueError("Cannot kill the last active node")

        # Lưu lại láng giềng cũ để có thông tin report
        old_predecessor = self.nodes[node_id].predecessor
        old_successor = self.nodes[node_id].successor

        # Đánh dấu node là đã chết, sau đó chỉ sửa các liên kết trực tiếp quanh node này.
        # Không gọi stabilize() vì stabilize sẽ dựng lại toàn bộ vòng.
        self.nodes[node_id].active = False
        
        # Đưa ID này vào tập các node đã hỏng
        self.failed_nodes.add(node_id)

        # Ngắt node chết khỏi view định tuyến của chính nó.
        self.nodes[node_id].predecessor = None
        self.nodes[node_id].successor = None
        self.nodes[node_id].finger_table = []

        # Nối predecessor và successor cũ lại với nhau để vá vòng chính.
        if old_predecessor is not None and old_predecessor in self.nodes:
            predecessor = self.nodes[old_predecessor]
            if predecessor.active:
                predecessor.successor = old_successor

        if old_successor is not None and old_successor in self.nodes:
            successor = self.nodes[old_successor]
            if successor.active:
                successor.predecessor = old_predecessor

        # Finger table chỉ cần sửa những dòng đang trỏ vào node chết trước khi route phục hồi dữ liệu.
        updated_finger_tables, updated_finger_entries = self._repair_fingers_referencing(node_id)

        # Phục hồi resource từ các bản replica còn sống nếu hệ thống vẫn còn bản copy hợp lệ
        recovered_resources, lost_resources, recovery_details = self._recover_resources_after_node_failure(node_id)
        effective_replica_count = min(self.replication_count, max(0, len(self.active_node_ids) - 1))

        return {
            "killed_node_id": node_id,
            "old_predecessor": old_predecessor,
            "old_successor": old_successor,
            "transferred_resources": recovered_resources,
            "recovered_resources": recovered_resources,
            "lost_resources": lost_resources,
            "sample_new_owner": None,
            "updated_finger_tables": updated_finger_tables,
            "updated_finger_entries": updated_finger_entries,
            "replication_count": self.replication_count,
            "effective_replica_count": effective_replica_count,
            "recovery_source": "active local replica copies",
            "recovered_resource_ids": recovery_details["recovered_resource_ids"][:10],
            "replica_repaired_resource_ids": recovery_details["replica_repaired_resource_ids"][:10],
            "lost_resource_ids": recovery_details["lost_resource_ids"][:10],
            "recovered_resource_sample_count": min(
                len(recovery_details["recovered_resource_ids"]),
                10,
            ),
            "recovered_resource_total_count": len(recovery_details["recovered_resource_ids"]),
            "replica_repaired_resources": len(recovery_details["replica_repaired_resource_ids"]),
            "replica_repaired_resource_sample_count": min(
                len(recovery_details["replica_repaired_resource_ids"]),
                10,
            ),
            "replica_repaired_resource_total_count": len(
                recovery_details["replica_repaired_resource_ids"]
            ),
            "lost_resource_sample_count": min(len(recovery_details["lost_resource_ids"]), 10),
            "lost_resource_total_count": len(recovery_details["lost_resource_ids"]),
            "active_nodes": len(self.active_node_ids),
            "message": "Node killed, adjacent links repaired, and replicas recovered where available.",
        }

    # Định tuyến một key qua overlay Chord bằng successor và Finger Table
    def _route_key(
        self,
        key: int,
        *,
        start_node_id: int | None = None,
        operation: str = "Lookup",
        requested_id: str | None = None,
    ) -> dict[str, Any]:
        
        # Nếu vòng không có node active thì không thể định tuyến tới successor
        if not self.active_node_ids:
            raise RuntimeError("No active nodes are available")

        # Chuẩn hóa key về không gian định danh m-bit của vòng Chord
        normalized_key = int(key) % self.identifier_space

        logs: list[str] = []

        # Lấy điểm xuất phát hợp lệ, khởi tạo mảng lịch sử đường đi (path) và tập các node đã thăm (visited)
        current = self._resolve_start_node(start_node_id, logs)
        start_node = current
        path = [current]
        visited = {current}
        owner_id: int | None = None

        label = requested_id if requested_id is not None else str(normalized_key)
        logs.append(
            f"{operation} starts at {self._node_label(current)} for {label} "
            f"with key {normalized_key} over {self.communication_layer}."
        )

        # Thiết lập cơ chế chống lặp vô hạn (safety limit)
        max_steps = max(1, len(self.active_node_ids) * (self.m + 1))
        hops = 0

        # Lặp cho đến khi chính quá trình định tuyến phát hiện node owner.
        # Không dùng find_successor(key) ở đây, vì lookup Chord phải route qua successor/finger table.
        while owner_id is None:
            if self._node_owns_key(current, normalized_key):
                owner_id = current
                logs.append(f"Node {current} owns key {normalized_key}; routing stops locally.")
                break

            if hops >= max_steps:
                raise RuntimeError(f"{operation} exceeded the safety hop limit")

            # Gọi hàm con chọn ra bước nhảy tối ưu tiếp theo.
            # Hàm này có thể tự sửa node hiện tại nếu phát hiện successor/finger đã chết.
            next_node, reason, reaches_owner = self._select_next_hop(
                current,
                normalized_key,
                logs,
            )

            # Phát hiện lặp vòng (node hiện tại trỏ tới một node đã đi qua)
            # Điều này xảy ra khi Finger Table bị cũ do churn, nên sửa view của node hiện tại
            if next_node in visited and not reaches_owner:
                repair_report = self._repair_node_after_failure(current)
                # Sau khi node hiện tại cập nhật lại view cục bộ, tính lại bước nhảy.
                next_node, reason, reaches_owner = self._select_next_hop(
                    current,
                    normalized_key,
                    logs,
                )
                logs.append(
                    "Repair triggered because a repeated node was detected; "
                    f"{repair_report['message']}"
                )

            # Nếu định tuyến bị kẹt không đi tiếp được, báo lỗi hệ thống
            if next_node == current:
                raise RuntimeError(f"{operation} cannot make progress from the current node")

            # Ghi nhận trạng thái nhảy hop thành công
            hops += 1
            logs.append(f"Hop {hops}: {reason}")
            current = next_node
            path.append(current)
            visited.add(current)

            if reaches_owner:
                owner_id = current

        logs.append(
            f"{operation} routed to owner {self._node_label(owner_id)} in {hops} hop(s)."
        )
        return {
            "key": normalized_key,
            "owner_id": owner_id,
            "start_node_id": start_node,
            "path": path,
            "hops": hops,
            "logs": logs,
        }

    # Định tuyến và tìm kiếm chủ sở hữu (owner) của một tài nguyên/khóa thông qua nhiều bước nhảy (hop) bằng Finger Table
    def lookup(self, resource_id: str | int, start_node_id: int | None = None) -> LookupResult:
        # Quy đổi đầu vào thành ID gốc và khóa (key) nguyên số mà client có thể tự tính
        requested_id, key, direct_key = self._resolve_lookup_key(resource_id)

        # Route get qua overlay Chord thay vì dùng bảng trung tâm để tìm owner
        route = self._route_key(
            key,
            start_node_id=start_node_id,
            operation="Lookup",
            requested_id=requested_id,
        )
        owner_id = route["owner_id"]
        logs = route["logs"]
        path = route["path"]
        hops = route["hops"]
        start_node = route["start_node_id"]

        owner_node = self.nodes[owner_id]
        found = direct_key or requested_id in owner_node.local_resources
        replica_node_ids = (
            self.resources[requested_id].replica_node_ids
            if requested_id in self.resources
            else []
        )

        # Kết thúc tìm kiếm
        logs.append(f"Lookup finished at owner node {owner_id} in {hops} hop(s).")
        if direct_key:
            logs.append(f"Node {owner_id} is responsible for numeric key {key}.")
        elif found:
            logs.append(f"Owner node {owner_id} confirms it stores resource {requested_id}.")
            if replica_node_ids:
                logs.append(
                    f"Replica copies are available on successor node(s): {replica_node_ids}."
                )
        else:
            logs.append(
                f"Owner node {owner_id} does not store resource {requested_id}; "
                "the data is unavailable on the current ring."
            )
        return LookupResult(
            requested_id=requested_id,
            key=key,
            owner_id=owner_id,
            start_node_id=start_node,
            path=path,
            hops=hops,
            logs=logs,
            found=found,
            direct_key=direct_key,
            replica_node_ids=replica_node_ids,
        )

    # Chuyển đổi đầu vào của người dùng thành khóa (key) số nguyên chuẩn trên vòng định danh
    def _resolve_lookup_key(self, resource_id: str | int) -> tuple[str, int, bool]:
        requested_id = str(resource_id).strip()

        # Nếu người dùng truyền thẳng một số nguyên, xem đây là lookup trực tiếp theo key
        if isinstance(resource_id, int) or requested_id.isdigit():
            return requested_id, int(requested_id) % self.identifier_space, True

        # Với resource_id dạng chuỗi, client tự băm ID để tạo key mà không cần hỏi metadata trung tâm
        return requested_id, hash_identifier(requested_id, self.m), False

    # Xác định node bắt đầu cho quá trình tìm kiếm
    # Nếu người dùng chỉ định node bắt đầu thì node đó phải tồn tại và đang active
    def _resolve_start_node(self, start_node_id: int | None, logs: list[str]) -> int:
        active_ids = self.active_node_ids
        # Nếu không yêu cầu node cụ thể, tự động chọn node bé nhất mạng làm điểm phát xuất
        if start_node_id is None:
            return active_ids[0]

        # Chuẩn hóa giá trị đầu vào
        normalized_start = int(start_node_id) % self.identifier_space
        
        # Trả về đích danh nếu node đang sống
        if normalized_start in self.nodes and self.nodes[normalized_start].active:
            return normalized_start

        if normalized_start in self.nodes:
            raise ValueError(f"Start node {normalized_start} is failed/inactive")
        raise ValueError(f"Start node {normalized_start} does not exist")

    def _node_label(self, node_id: int) -> str:
        return f"node {node_id}"

    # Lựa chọn bước nhảy tiếp theo cho định tuyến: ưu tiên successor nếu khóa nằm sát, ngược lại dùng Finger Table
    def _node_owns_key(self, node_id: int, key: int) -> bool:
        node = self.nodes[node_id]
        if node.predecessor is None:
            return False
        return in_clockwise_interval(key, node.predecessor, node_id, include_end=True)

    # Chọn node kế tiếp cho một bước lookup dựa trên successor và closest preceding finger
    def _select_next_hop(
        self,
        current_id: int,
        key: int,
        logs: list[str] | None = None,
    ) -> tuple[int, str, bool]:
        node = self.nodes[current_id]
        successor = node.successor

        # Nếu phát hiện successor bị thiếu hoặc đã chết, chỉ sửa view của node hiện tại.
        if successor is None or successor not in self.nodes or not self.nodes[successor].active:
            failed_id = successor if successor in self.nodes else None
            repair_report = self._repair_node_after_failure(current_id, failed_id)
            if logs is not None:
                logs.append(
                    f"Node {current_id} detected failed successor {successor}; "
                    f"{repair_report['message']}"
                )
            successor = self.nodes[current_id].successor

        if successor is None:
            raise RuntimeError("Current node has no successor")

        # Kiểm tra logic khoảng (interval): Nếu Key rơi vào khoảng (current, successor] 
        # thì bước nhảy kế tiếp phải là thẳng tới successor vì nó chính là Owner
        if in_clockwise_interval(key, current_id, successor, include_end=True):
            return (
                successor,
                f"Key {key} is in ({current_id}, {successor}], forwarding to successor {self._node_label(successor)}.",
                True,
            )

        # Nếu khoảng còn quá xa, tìm node gần đích nhất trong Finger Table
        candidate, failed_finger = self._closest_preceding_finger(current_id, key)
        if failed_finger is not None:
            repair_report = self._repair_node_after_failure(current_id, failed_finger)
            if logs is not None:
                logs.append(
                    f"Node {current_id} detected failed finger {failed_finger}; "
                    f"{repair_report['message']}"
                )
            successor = self.nodes[current_id].successor
            candidate, _ = self._closest_preceding_finger(current_id, key)
        
        # Nếu Finger cũng chỉ trả về successor, tiến qua successor để duyệt tiếp vòng kế
        if candidate == successor:
            return (
                successor,
                f"No closer finger is available at {self._node_label(current_id)}; forwarding to successor {self._node_label(successor)}.",
                False,
            )

        # Trả về node tối ưu nhất đã tính
        return (
            candidate,
            f"{self._node_label(current_id)} selects finger {self._node_label(candidate)}, the closest known predecessor of key {key}.",
            False,
        )

    # Tìm node xa nhất trong Finger Table nhưng vẫn nằm trước khóa (key) theo chiều kim đồng hồ
    def _closest_preceding_finger(self, current_id: int, key: int) -> tuple[int, int | None]:
        node = self.nodes[current_id]
        first_failed_finger: int | None = None

        # Duyệt bảng Finger ngược từ cuối lên (vì cuối bảng chứa bước nhảy xa nhất)
        for entry in reversed(node.finger_table):
            candidate = entry.node_id
            
            # Bỏ qua nếu dòng này trỏ về chính node hiện tại
            if candidate == current_id:
                continue
                
            # Ghi nhận nếu finger trỏ đến node chết để hàm gọi sửa view của node hiện tại
            if candidate not in self.nodes or not self.nodes[candidate].active:
                if first_failed_finger is None:
                    first_failed_finger = candidate
                continue
                
            # Kiểm tra khoảng: Node ứng viên phải nằm khắt khe giữa node hiện tại và Khóa (key)
            if in_clockwise_interval(
                candidate,
                current_id,
                key,
                include_start=False,
                include_end=False,
            ):
                return candidate, first_failed_finger

        # Fallback an toàn: Nếu không có cấu hình Finger nào thỏa mãn, buộc phải trả về successor để tịnh tiến
        if node.successor is None:
            raise RuntimeError("Current node has no successor")
        return node.successor, first_failed_finger

    # Sửa cục bộ view của một node khi nó phát hiện thông tin định tuyến đã cũ
    # Không rebuild toàn mạng; chỉ cập nhật predecessor/successor/finger table của node phát hiện lỗi.
    def _repair_node_after_failure(
        self,
        node_id: int,
        failed_node_id: int | None = None,
    ) -> dict[str, Any]:
        if node_id not in self.nodes or not self.nodes[node_id].active:
            raise RuntimeError(f"Cannot repair inactive or missing node {node_id}")

        node = self.nodes[node_id]
        node.predecessor = self._find_active_predecessor(node_id)
        node.successor = self._find_active_successor(node_id)
        node.finger_table = self._build_finger_table(node_id)
        moved_resources = self._adopt_resources_from_failed_nodes()

        detected = (
            f" detected failed node {failed_node_id} and" if failed_node_id is not None else ""
        )
        return {
            "node_id": node_id,
            "failed_node_id": failed_node_id,
            "moved_resources": moved_resources,
            "message": (
                f"Node {node_id}{detected} repaired its local routing view; "
                f"{moved_resources} orphaned resource(s) moved to active owners."
            ),
        }
    
    # Tìm successor kế tiếp đang hoạt động trên vòng định danh
    def _find_active_successor(self, node_id: int) -> int:
        active_ids = self.active_node_ids

        # Nếu không có node nào đang hoạt động, không thể tìm successor
        if not active_ids:
            raise RuntimeError("No active nodes are available")
        
        # Dùng thuật toán tìm kiếm nhị phân (bisect_right) để tìm vị trí node > node_id nhanh chóng
        position = bisect.bisect_right(active_ids, node_id)

        # Nếu position vọt qua độ dài mảng (nghĩa là node_id nằm sau node lớn nhất),
        if position == len(active_ids):
            position = 0

        # Trả về ID của node tìm được
        return active_ids[position]

    # Tìm predecessor kế tiếp đang hoạt động trên vòng định danh
    def _find_active_predecessor(self, node_id: int) -> int:
        active_ids = self.active_node_ids
        if not active_ids:
            raise RuntimeError("No active nodes are available")
        position = bisect.bisect_left(active_ids, node_id) - 1
        return active_ids[position]

    # Nhận lại các resource đang trỏ tới owner đã chết nếu còn replica sống
    def _adopt_resources_from_failed_nodes(self) -> int:
        moved = 0

        # Duyệt các resource thật sự còn bản copy trên node active
        for resource in self._unique_active_local_resources().values():
            owner = self.nodes.get(resource.owner_id)

            # Bỏ qua resource có owner hiện tại vẫn còn active
            if owner is not None and owner.active:
                continue

            old_owner_id = resource.owner_id
            route = self._route_key(
                resource.key,
                operation="Recover",
                requested_id=resource.resource_id,
            )
            new_owner_id = route["owner_id"]

            # Dọn bản local còn sót lại trên owner cũ nếu node đó vẫn nằm trong mô phỏng
            if old_owner_id in self.nodes:
                self.nodes[old_owner_id].local_resources.pop(resource.resource_id, None)

            # Gán owner mới theo route Chord tới successor(key), rồi tạo lại replica set tương ứng
            resource.owner_id = new_owner_id
            self.resources[resource.resource_id] = resource
            self._place_resource_copies(resource)
            moved += 1
        
        # Dọn metadata UI cho các resource có owner chết nhưng không còn bản copy active
        self._drop_lost_resources_from_metadata()
        return moved

    # Gom các resource duy nhất đang xuất hiện trong local_resources của node active
    def _unique_active_local_resources(self) -> dict[str, ResourceRecord]:
        resources: dict[str, ResourceRecord] = {}

        # Chỉ đọc local storage của node còn sống, không đọc dữ liệu từ node đã chết
        for node_id in self.active_node_ids:
            for resource_id, resource in self.nodes[node_id].local_resources.items():
                resources.setdefault(resource_id, resource)

        return resources

    # Xóa metadata UI của resource đã mất vì owner chết và không còn replica sống
    def _drop_lost_resources_from_metadata(self) -> tuple[int, list[str]]:
        lost = 0
        lost_resource_ids: list[str] = []

        # Metadata trung tâm chỉ được dùng để dọn trạng thái hiển thị sau khi thuật toán đã chạy
        for resource_id, resource in list(self.resources.items()):
            owner = self.nodes.get(resource.owner_id)
            if owner is None or owner.active:
                continue
            if self._live_resource_copy_holders(resource):
                continue

            self._remove_resource_copies(resource_id)
            self.resources.pop(resource_id, None)
            lost += 1
            lost_resource_ids.append(resource_id)

        return lost, lost_resource_ids

    # Tìm các node active đang thật sự giữ bản copy local của resource
    def _live_resource_copy_holders(
        self,
        resource: ResourceRecord,
        *,
        exclude_ids: set[int] | None = None,
    ) -> list[int]:
        # Loại trừ node vừa chết hoặc các node không được dùng làm nguồn phục hồi
        excluded = exclude_ids or set()

        # Chỉ tính node active và có resource_id trong local_resources
        return [
            node_id
            for node_id in self.active_node_ids
            if node_id not in excluded
            and resource.resource_id in self.nodes[node_id].local_resources
        ]

    # Phục hồi các resource có owner là node vừa bị kill từ replica còn sống
    def _recover_resources_after_node_failure(
        self,
        failed_node_id: int,
    ) -> tuple[int, int, dict[str, list[str]]]:
        failed_node = self.nodes[failed_node_id]
        recovered = 0
        recovered_resource_ids: list[str] = []
        replica_repaired_resource_ids: list[str] = []

        # Node chết không còn được xem là nguồn dữ liệu hợp lệ
        failed_node.local_resources.clear()

        # Tìm resource cần phục hồi bằng cách đọc replica còn sống trên các node active
        local_resources = self._unique_active_local_resources()
        for resource in local_resources.values():
            if resource.owner_id != failed_node_id:
                continue

            # Owner đúng sau khi node chết được tìm bằng route Chord tới successor mới của key
            route = self._route_key(
                resource.key,
                operation="Recover",
                requested_id=resource.resource_id,
            )
            new_owner_id = route["owner_id"]

            # Kiểm tra xem còn node active nào giữ bản replica thật hay không
            live_copy_holders = self._live_resource_copy_holders(
                resource,
                exclude_ids={failed_node_id},
            )
            if not live_copy_holders:
                continue

            # Có replica sống thì promote sang owner mới và tạo lại đủ replica
            resource.owner_id = new_owner_id
            self.resources[resource.resource_id] = resource
            self._place_resource_copies(resource)
            recovered += 1
            recovered_resource_ids.append(resource.resource_id)

        # Với resource mà node chết chỉ là replica, loại node đó khỏi replica set rồi tạo lại bản sao thiếu
        for resource in list(self._unique_active_local_resources().values()):
            if failed_node_id not in resource.replica_node_ids:
                continue
            replica_repaired_resource_ids.append(resource.resource_id)
            resource.replica_node_ids = [
                replica_id
                for replica_id in resource.replica_node_ids
                if replica_id != failed_node_id
            ]
            self.resources[resource.resource_id] = resource
            self._place_resource_copies(resource)

        # Sau cùng mới dọn metadata UI cho resource không còn replica sống nào để phục hồi
        lost, lost_resource_ids = self._drop_lost_resources_from_metadata()

        return recovered, lost, {
            "recovered_resource_ids": recovered_resource_ids,
            "replica_repaired_resource_ids": replica_repaired_resource_ids,
            "lost_resource_ids": lost_resource_ids,
        }

    # Sửa các dòng Finger Table đang trỏ tới node vừa chết
    def _repair_fingers_referencing(self, failed_node_id: int) -> tuple[int, int]:
        updated_tables = 0
        updated_entries = 0

        # Duyệt toàn bộ node active để tìm finger entry đã cũ
        for node_id in self.active_node_ids:
            node = self.nodes[node_id]
            table_updates = sum(1 for entry in node.finger_table if entry.node_id == failed_node_id)
            if table_updates == 0:
                continue

            # Tính lại node đích cho đúng successor của start nếu entry cũ trỏ vào node chết
            node.finger_table = [
                FingerEntry(
                    index=entry.index,
                    start=entry.start,
                    interval_end=entry.interval_end,
                    node_id=self._find_successor_by_links(entry.start, start_node_id=node_id)
                    if entry.node_id == failed_node_id
                    else entry.node_id,
                )
                for entry in node.finger_table
            ]
            updated_tables += 1
            updated_entries += table_updates

        return updated_tables, updated_entries

    # Thống kê và đếm số lượng tài nguyên đang được lưu trữ trên mỗi node đang hoạt động
    def resource_distribution(self) -> dict[int, int]:
        # Tạo map khởi tạo giá trị 0 cho mọi node để đảm bảo UI/Biểu đồ không bị khuyết dữ liệu
        distribution = {node_id: 0 for node_id in self.active_node_ids}

        # Đếm trực tiếp từ kho local của từng node để phản ánh node đang thật sự giữ dữ liệu
        for node_id in distribution:
            distribution[node_id] = len(self.nodes[node_id].local_resources)
        return distribution

    # Trích xuất và định dạng toàn bộ trạng thái chi tiết của một node cụ thể gửi ra bên ngoài
    def node_details(self, node_id: int) -> dict[str, Any]:
        if node_id not in self.nodes:
            raise ValueError(f"Node {node_id} does not exist")
        # Sử dụng hàm to_dict() từ object Node
        return self.nodes[node_id].to_dict()

    # Gom nhóm toàn bộ số liệu thống kê (snapshot) của vòng mạng gửi cho Frontend/UI hiển thị
    def summary(self, *, sample_size: int | None = None) -> dict[str, Any]:
        active_ids = self.active_node_ids

        # Rút trích và sắp xếp list resource theo ID để chống nhảy lộn xộn dòng trên UI
        all_resources = sorted(self.resources.values(), key=lambda r: r.resource_id)
        
        # Nếu có cắt mẫu (pagination/sampling) thì chỉ lấy theo sample_size
        if sample_size is None:
            picked = all_resources
        else:
            picked = all_resources[: min(sample_size, len(all_resources))]
            
        sample_resources = [resource.to_dict() for resource in picked]
        
        # Lấy map phân bố tài nguyên
        distribution = self.resource_distribution() if active_ids else {}

        # Trả về toàn bộ payload tổng quan
        return {
            "m": self.m,
            "identifier_space": self.identifier_space,
            "communication_layer": self.communication_layer,
            "replication_count": self.replication_count,
            "active_node_count": len(active_ids),
            "failed_node_count": len(self.failed_nodes),
            "resource_count": len(self.resources),
            "resource_table_row_count": len(sample_resources),
            "active_nodes": active_ids,
            "failed_nodes": sorted(self.failed_nodes),
            "sample_resources": sample_resources,
            "resource_distribution": distribution,
            "max_resources_on_node": max(distribution.values()) if distribution else 0,
            "min_resources_on_node": min(distribution.values()) if distribution else 0,
        }

    # Xuất toàn bộ cấu trúc Finger Table của tất cả node đang chạy ra dạng JSON phục vụ vẽ biểu đồ và log test
    def export_finger_tables(self) -> dict[int, list[dict[str, int]]]:
        # Dùng dictionary comprehension để map node_id với cấu trúc dict của Finger table
        return {
            node_id: [entry.to_dict() for entry in self.nodes[node_id].finger_table]
            for node_id in self.active_node_ids
        }

    # Kiểm tra tính toàn vẹn của dữ liệu: đảm bảo mọi tài nguyên đều đang được sở hữu đúng bởi successor của khóa
    def verify_resource_mapping(self) -> bool:
        # Check all để xem có bất kỳ resource nào nằm sai owner_id so với tính toán lý thuyết không
        return all(
            resource.owner_id == self.find_successor(resource.key)
            and resource.resource_id in self.nodes[resource.owner_id].local_resources
            and len(resource.replica_node_ids) <= self.replication_count
            and len(resource.replica_node_ids) == len(set(resource.replica_node_ids))
            and resource.owner_id not in resource.replica_node_ids
            and all(
                replica_id in self.nodes
                and self.nodes[replica_id].active
                and
                resource.resource_id in self.nodes[replica_id].local_resources
                for replica_id in resource.replica_node_ids
            )
            for resource in self.resources.values()
        )

    # Kiểm tra tính toàn vẹn của bảng định tuyến: đảm bảo mọi ngón trỏ (finger) trỏ tới đúng successor mong muốn
    def verify_finger_tables(self) -> bool:
        # Quét qua mọi node và mọi finger, tính toán lại expected node_id để so sánh với cái đang lưu
        for node_id in self.active_node_ids:
            for entry in self.nodes[node_id].finger_table:
                expected = self.find_successor(entry.start)
                if entry.node_id != expected:
                    return False
        return True

    # Chọn ngẫu nhiên một ID tài nguyên đang có trong hệ thống phục vụ cho các module giả lập truy cập
    def choose_random_resource(self) -> str:
        if not self.resources:
            raise RuntimeError("No resources are available")
        # Sử dụng bộ sinh số đã seed để bốc ngẫu nhiên
        return self._rng.choice(list(self.resources.keys()))

    # Chọn ngẫu nhiên một Node ID đang còn sống phục vụ cho các yêu cầu xuất phát ngẫu nhiên
    def choose_random_node(self) -> int:
        # Sử dụng list ID active để bốc ngẫu nhiên
        return self._rng.choice(self.active_node_ids)


# Khởi tạo và thiết lập một mạng Chord mặc định phục vụ cho mục đích demo (50 nodes, 1000 resources)
def build_default_ring() -> ChordRing:
    # Khởi tạo instance với cấu hình m=16 bit
    ring = ChordRing(m=16, seed=61)
    # Bơm thông số thiết lập mạng
    ring.initialize_network(node_count=50, resource_count=1000)
    return ring


# Thực hiện tìm kiếm hàng loạt nhiều tài nguyên bắt đầu từ các node ngẫu nhiên để kiểm thử tốc độ/tính đúng đắn
def validate_lookup_batch(ring: ChordRing, resources: Iterable[str]) -> list[LookupResult]:
    results: list[LookupResult] = []
    
    # Lặp qua các tài nguyên được yêu cầu
    for resource_id in resources:
        # Bốc ngẫu nhiên một node xuất phát để chạy giả lập client request
        start_node = ring.choose_random_node()
        # Lưu kết quả truy vấn vào mảng tổng
        results.append(ring.lookup(resource_id, start_node_id=start_node))
        
    return results
