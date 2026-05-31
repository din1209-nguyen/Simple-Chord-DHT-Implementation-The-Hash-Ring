
from __future__ import annotations

import bisect
import random
from typing import Any, Iterable

from .identifiers import hash_identifier, hash_resource, in_clockwise_interval
from .models import FingerEntry, LookupResult, Node, ResourceRecord

# ChordRing là lớp chính để mô phỏng vòng Chord
class ChordRing:

    # Khởi tạo vòng Chord, thiết lập tham số mô phỏng
    def __init__(
        self,
        m: int = 16,
        seed: int = 61,
        replication_count: int = 1,
    ) -> None:
        # Kiểm tra số bit định danh
        if not 1 <= m <= 160:
            raise ValueError("m must be between 1 and 160")

        # Cập nhật số bit định danh
        self.m = m

        # Tính kích thước không gian định danh
        self.identifier_space = 2**m

        # Cập nhật seed mô phỏng
        self.seed = seed

        # Cập nhật số lượng bản sao tài nguyên
        self.replication_count = self._validate_replication_count(replication_count)

        # Cập nhật mô tả lớp truyền thông giả lập
        self.communication_layer = "HTTP/REST via Flask API"

        # Khởi tạo bảng node trong mô phỏng
        self.nodes: dict[int, Node] = {}

        # Khởi tạo tập node lỗi trong mô phỏng
        self.failed_nodes: set[int] = set()

        # Khởi tạo bảng tài nguyên trong mô phỏng
        self.resources: dict[str, ResourceRecord] = {}

        # Khởi tạo bộ sinh số ngẫu nhiên theo seed
        self._rng = random.Random(seed)

        # Khởi tạo bộ đếm tick protocol
        self._protocol_ticks = 0

        # Khởi tạo số vòng hội tụ mặc định
        self._default_convergence_rounds = 8

        # Khởi tạo giới hạn dò successor bằng liên kết
        self._max_successor_walk = 0

        # Khởi tạo hệ số giới hạn hop khi định tuyến
        self._max_route_hops_multiplier = 2

    # Kiểm tra số replica cho mỗi resource
    def _validate_replication_count(self, replication_count: int) -> int:
        # Ép kiểu tham số replica
        replicas = int(replication_count)

        # Kiểm tra replica không âm
        if replicas < 0:
            raise ValueError("replication_count must be non-negative")

        # Trả về số replica hợp lệ
        return replicas

    # Trích xuất danh sách node đang hoạt động
    @property
    def active_node_ids(self) -> list[int]:
        # Lọc các node active
        # Sắp xếp node theo chiều tăng dần
        return sorted(node_id for node_id, node in self.nodes.items() if node.active)

    # Khởi tạo lại toàn bộ mạng Chord
    def initialize_network(
        self,
        node_count: int = 50,
        resource_count: int = 1000,
        *,
        seed: int | None = None,
        replication_count: int | None = None,
    ) -> dict[str, Any]:
        # Cập nhật seed mô phỏng
        if seed is not None:
            self.seed = seed
            self._rng = random.Random(seed)

        # Cập nhật số lượng bản sao tài nguyên
        if replication_count is not None:
            self.replication_count = self._validate_replication_count(replication_count)

        # Kiểm tra số lượng node đầu vào
        if node_count < 1:
            raise ValueError("node_count must be at least 1")

        # Kiểm tra số lượng resource đầu vào
        if resource_count < 0:
            raise ValueError("resource_count must be non-negative")

        # Kiểm tra giới hạn không gian định danh
        if node_count > self.identifier_space:
            raise ValueError("node_count cannot exceed the identifier space")

        # Xóa danh sách node cũ
        self.nodes.clear()

        # Xóa danh sách node lỗi cũ
        self.failed_nodes.clear()

        # Xóa danh sách resource cũ
        self.resources.clear()

        # Sinh danh sách định danh node
        node_ids = self._generate_unique_ids("node", node_count)

        # Lấy node đầu tiên làm node khởi tạo
        first_id = node_ids[0]

        # Tạo node khởi tạo
        self.nodes[first_id] = Node(node_id=first_id)

        # Gán predecessor cho node khởi tạo
        self.nodes[first_id].predecessor = first_id

        # Gán successor cho node khởi tạo
        self.nodes[first_id].successor = first_id

        # Khởi tạo finger table rỗng cho node khởi tạo
        self.nodes[first_id].finger_table = []

        # Duyệt các node còn lại để tham gia ring thông qua protocol Chord
        for node_id in node_ids[1:]:
            # Tạo node mới
            self.nodes[node_id] = Node(node_id=node_id)

            # Tham gia ring thông qua node khởi tạo, không dùng oracle/global lookup
            self.join(node_id, known_node_id=first_id)

            # Chạy protocol để hội tụ
            self.run_protocol(rounds=self._default_convergence_rounds)

        # Chạy thêm vòng hội tụ để ổn định finger table
        self.run_protocol(rounds=self._default_convergence_rounds)

        # Duyệt từng resource để phân phối
        for index in range(1, resource_count + 1):
            # Tạo id resource theo chỉ số
            resource_id = f"resource-{index:04d}"

            # Tạo bản ghi resource
            digest, key = hash_resource(resource_id, self.m)
            route = self._route_key(key, operation="Put", requested_id=resource_id)
            owner_id = route["owner_id"]
            resource = ResourceRecord(resource_id, digest, key, owner_id)

            # Lưu resource vào bảng metadata
            self.resources[resource_id] = resource

            # Đặt bản sao resource vào owner và replica
            self._place_resource_copies(resource)

        # Đồng bộ kho local theo metadata
        self._rebuild_local_resource_storage()

        # Trả về trạng thái tổng quan
        return self.summary(sample_size=None)

    # Tham gia ring thông qua một node đã biết
    def join(self, node_id: int, *, known_node_id: int) -> None:
        # Kiểm tra node tham gia có tồn tại
        if node_id not in self.nodes:
            raise ValueError(f"Node {node_id} does not exist")

        # Kiểm tra node tham gia đang hoạt động
        if not self.nodes[node_id].active:
            raise ValueError(f"Node {node_id} is inactive")

        # Kiểm tra node đã biết có tồn tại
        if known_node_id not in self.nodes:
            raise ValueError(f"Known node {known_node_id} does not exist")

        # Kiểm tra node đã biết đang hoạt động
        if not self.nodes[known_node_id].active:
            raise ValueError(f"Known node {known_node_id} is inactive")

        # Đặt predecessor rỗng trước khi hội tụ
        self.nodes[node_id].predecessor = None

        # Định tuyến để tìm successor ban đầu
        successor_id = self._route_key(
            node_id,
            start_node_id=known_node_id,
            operation="Join",
            requested_id=str(node_id),
        )["owner_id"]

        # Gán successor ban đầu
        self.nodes[node_id].successor = successor_id

        # Khởi tạo finger table rỗng
        self.nodes[node_id].finger_table = []

    # Chạy các bước protocol theo nhiều vòng
    def run_protocol(self, *, rounds: int = 1) -> None:
        # Kiểm tra số vòng chạy protocol
        if rounds < 0:
            raise ValueError("rounds must be non-negative")

        # Lặp qua từng vòng hội tụ
        for _ in range(rounds):
            # Chụp snapshot danh sách node active
            node_ids = list(self.active_node_ids)

            # Duyệt từng node để stabilize
            for node_id in node_ids:
                self.stabilize_one(node_id)

            # Duyệt từng node để kiểm tra predecessor
            for node_id in node_ids:
                self.check_predecessor_one(node_id)

            # Duyệt từng node để fix_fingers
            for node_id in node_ids:
                self.fix_fingers_one(node_id)

            # Tăng tick protocol
            self._protocol_ticks += 1

    # Ổn định liên kết successor và predecessor của một node
    def stabilize_one(self, node_id: int) -> None:
        # Bỏ qua node không còn hoạt động
        if node_id not in self.nodes or not self.nodes[node_id].active:
            return

        # Đọc successor hiện tại
        successor_id = self.nodes[node_id].successor

        # Gán successor về chính nó khi thiếu successor
        if successor_id is None:
            self.nodes[node_id].successor = node_id
            successor_id = node_id

        # Sửa successor khi successor đã chết
        if successor_id not in self.nodes or not self.nodes[successor_id].active:
            self.nodes[node_id].successor = self._find_successor_by_links(node_id, start_node_id=node_id)
            successor_id = self.nodes[node_id].successor

        # Đọc predecessor của successor
        successor_predecessor = self.nodes[successor_id].predecessor

        # Cập nhật successor khi có node nằm giữa
        if successor_predecessor is not None and successor_predecessor in self.nodes and self.nodes[successor_predecessor].active:
            if in_clockwise_interval(successor_predecessor, node_id, successor_id, include_start=False, include_end=False):
                self.nodes[node_id].successor = successor_predecessor
                successor_id = successor_predecessor

        # Gửi notify để cập nhật predecessor của successor
        self.notify(successor_id, potential_predecessor=node_id)

        # Gán predecessor về chính nó khi vòng chỉ có một node
        if self.nodes[node_id].predecessor is None and successor_id == node_id:
            self.nodes[node_id].predecessor = node_id

    # Thông báo cho node đích cập nhật predecessor
    def notify(self, node_id: int, *, potential_predecessor: int) -> None:
        # Bỏ qua notify khi node đích chết
        if node_id not in self.nodes or not self.nodes[node_id].active:
            return

        # Bỏ qua notify khi node nguồn chết
        if potential_predecessor not in self.nodes or not self.nodes[potential_predecessor].active:
            return

        # Đọc predecessor hiện tại
        current_predecessor = self.nodes[node_id].predecessor

        # Gán predecessor khi predecessor đang rỗng
        if current_predecessor is None:
            self.nodes[node_id].predecessor = potential_predecessor
            return

        # Cập nhật predecessor khi node nguồn nằm trong khoảng hợp lệ
        if in_clockwise_interval(potential_predecessor, current_predecessor, node_id, include_start=False, include_end=False):
            self.nodes[node_id].predecessor = potential_predecessor

    # Kiểm tra predecessor có còn sống không
    def check_predecessor_one(self, node_id: int) -> None:
        # Bỏ qua node không còn hoạt động
        if node_id not in self.nodes or not self.nodes[node_id].active:
            return

        # Đọc predecessor hiện tại
        predecessor_id = self.nodes[node_id].predecessor

        # Bỏ qua khi chưa có predecessor
        if predecessor_id is None:
            return

        # Xóa predecessor khi predecessor đã chết
        if predecessor_id not in self.nodes or not self.nodes[predecessor_id].active:
            self.nodes[node_id].predecessor = None

    # Cập nhật một dòng finger table
    def fix_fingers_one(self, node_id: int) -> None:
        # Bỏ qua node không còn hoạt động
        if node_id not in self.nodes or not self.nodes[node_id].active:
            return

        # Khởi tạo finger table khi còn rỗng
        if not self.nodes[node_id].finger_table:
            self.nodes[node_id].finger_table = [
                FingerEntry(
                    index=index,
                    start=(node_id + 2 ** (index - 1)) % self.identifier_space,
                    interval_end=(node_id + 2**index) % self.identifier_space,
                    node_id=node_id,
                )
                for index in range(1, self.m + 1)
            ]

        # Tính chỉ số finger cần cập nhật
        finger_index = (self._protocol_ticks % self.m) + 1

        # Tính vị trí start của finger
        start = (node_id + 2 ** (finger_index - 1)) % self.identifier_space

        # Định tuyến để tìm successor của start
        successor_id = self._route_key(
            start,
            start_node_id=node_id,
            operation="FixFingers",
            requested_id=str(start),
        )["owner_id"]

        # Gán finger entry đã cập nhật
        self.nodes[node_id].finger_table[finger_index - 1] = FingerEntry(
            index=finger_index,
            start=start,
            interval_end=(node_id + 2**finger_index) % self.identifier_space,
            node_id=successor_id,
        )


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
    # Lưu ý: đây là hàm "oracle" dùng global knowledge (active_node_ids + bisect).
    # Với mô phỏng mức 1 (không dùng dữ liệu trung tâm khi route), không nên dùng hàm này cho lookup/put.
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

        active_before_join = [node_id for node_id in self.active_node_ids if node_id != new_node_id]

        # Xử lý logic tạo hoặc bật lại node:
        if new_node_id in self.nodes:
            # Node cũ từng bị tắt -> bật lại cờ active
            self.nodes[new_node_id].active = True
            self.nodes[new_node_id].predecessor = None
            self.nodes[new_node_id].successor = None
            self.nodes[new_node_id].finger_table = []
            self.nodes[new_node_id].local_resources.clear()
        else:
            # Node hoàn toàn mới -> khởi tạo object
            self.nodes[new_node_id] = Node(node_id=new_node_id)
            
        # Xóa ID này khỏi danh sách node chết (nếu có)
        self.failed_nodes.discard(new_node_id)

        known_node_id = None
        if active_before_join:
            known_node_id = self._rng.choice(active_before_join)
            self.join(new_node_id, known_node_id=known_node_id)
            self.run_protocol(rounds=self._default_convergence_rounds)
        else:
            self.nodes[new_node_id].successor = new_node_id
            self.nodes[new_node_id].predecessor = new_node_id
            self.run_protocol(rounds=1)

        for resource in self.resources.values():
            route = self._route_key(
                resource.key,
                start_node_id=new_node_id,
                operation="JoinRebalance",
                requested_id=resource.resource_id,
            )
            resource.owner_id = route["owner_id"]
            resource.replica_node_ids = self._replica_nodes_for_owner(resource.owner_id)

        self._rebuild_local_resource_storage()
        
        return {
            "node_id": new_node_id,
            "active_nodes": len(self.active_node_ids),
            "known_node_id": known_node_id,
            "message": f"Node {new_node_id} joined the ring successfully.",
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

        # Băm tên tài nguyên thành digest SHA-1 và key rồi định tuyến put qua Finger Table để tìm owner
        digest, key = hash_resource(normalized_id, self.m)
        route = self._route_key(key, operation="Put", requested_id=normalized_id)
        owner_id = route["owner_id"]
        resource = ResourceRecord(normalized_id, digest, key, owner_id)
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
        
        # Băm tên mới thành digest SHA-1 và key rồi định tuyến put qua Finger Table để tìm owner mới
        digest, key = hash_resource(new_id, self.m)
        route = self._route_key(key, operation="Put", requested_id=new_id)
        owner_id = route["owner_id"]
        resource = ResourceRecord(new_id, digest, key, owner_id)
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

    # Chạy hội tụ protocol và cập nhật lại resource
    def stabilize(self) -> dict[str, Any]:
        active_ids = self.active_node_ids
        if not active_ids:
            return {"active_nodes": 0, "message": "No active nodes are available."}

        self.run_protocol(rounds=self._default_convergence_rounds)

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
        # Phiên bản mức 1: xác định replica bằng cách đi theo successor pointer,
        # không phụ thuộc vào active_node_ids (global sorted list).
        if self.replication_count == 0:
            return []

        if owner_id not in self.nodes or not self.nodes[owner_id].active:
            return []

        replicas: list[int] = []
        current = owner_id

        # Tối đa đi một vòng để tránh lặp vô hạn
        safety = max(1, len(self.active_node_ids) + 1)
        for _ in range(self.replication_count):
            successor = self.nodes[current].successor
            if successor is None or successor not in self.nodes or not self.nodes[successor].active:
                # fallback: tìm successor bằng link-walk từ current
                successor = self._find_successor_by_links(current + 1, start_node_id=current)
            if successor == owner_id:
                break
            if successor not in replicas:
                replicas.append(successor)
            current = successor

            # Nếu successor pointer bị hỏng, dừng sớm
            if len(replicas) >= safety:
                break

        return replicas

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

            # Tìm successor của start: dùng link-walk trước,
            # fallback sang oracle khi ring chưa ổn định (trong quá trình join/stabilize).
            try:
                finger_node = self._find_successor_by_links(start, start_node_id=node_id)
            except RuntimeError:
                finger_node = self._find_active_successor(start)

            table.append(
                FingerEntry(
                    index=index,
                    start=start,
                    interval_end=interval_end,
                    node_id=finger_node,
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

    # Định tuyến một key qua overlay Chord
    def _route_key(
        self,
        key: int,
        *,
        start_node_id: int | None = None,
        operation: str = "Lookup",
        requested_id: str | None = None,
        collect_trace: bool = True,
    ) -> dict[str, Any]:
        # Kiểm tra vòng còn node hoạt động
        # (UI vẫn có thể dùng active_node_ids, nhưng routing logic không phụ thuộc vào oracle/bisect.)
        if not self.active_node_ids:
            raise RuntimeError("No active nodes are available")

        # Chuẩn hóa key vào không gian định danh
        normalized_key = int(key) % self.identifier_space

        # Khởi tạo danh sách log định tuyến
        logs: list[str] = []

        # Xác định node bắt đầu định tuyến
        current = self._resolve_start_node(start_node_id)

        # Lưu node bắt đầu để trả về
        start_node = current

        # Khởi tạo đường đi ban đầu
        path = [current]

        # Khởi tạo tập node đã thăm
        visited = {current}

        # Khởi tạo owner chưa xác định
        owner_id: int | None = None

        # Tạo nhãn hiển thị cho log
        label = requested_id if requested_id is not None else str(normalized_key)

        # Ghi log bắt đầu thao tác
        if collect_trace:
            logs.append(
                f"[0] {operation} begins: starting from node {current}, searching for key {normalized_key} "
                f"({label})."
            )

        # Xác định thao tác thuộc nhóm hội tụ
        is_fix_fingers = operation in {"FixFingers", "Join"}

        # Đọc hệ số giới hạn hop
        hop_multiplier = self._max_route_hops_multiplier

        # Tính giới hạn hop theo kích thước mạng
        # Dùng số node active để đặt safety limit, không dùng để quyết định route.
        active_count = max(1, sum(1 for node in self.nodes.values() if node.active))
        max_steps = max(1, active_count * (self.m + 1) * hop_multiplier)

        # Nới giới hạn hop cho thao tác hội tụ
        if is_fix_fingers:
            max_steps = max(max_steps, 50000)

        # Khởi tạo số hop đã đi
        hops = 0

        # Bỏ theo dõi visited khi đang hội tụ
        if is_fix_fingers:
            visited = set()

        # Lặp cho đến khi xác định được owner
        while owner_id is None:
            # Dừng định tuyến khi node hiện tại sở hữu key
            if self._node_owns_key(current, normalized_key):
                owner_id = current
                if collect_trace:
                    logs.append(
                        f"[{hops}] Node {current} owns key {normalized_key} directly "
                        f"(its interval [{current}, {self._successor_id(current)})); "
                        f"routing stops here (no hop taken)."
                    )
                break

            # Dừng khi vượt giới hạn hop
            if hops >= max_steps:
                if is_fix_fingers:
                    owner_id = self._find_successor_by_links(normalized_key, start_node_id=current)
                    if collect_trace:
                        logs.append(
                            f"[{hops + 1}] Safety limit reached ({max_steps} hops). "
                            f"Link-walk fallback locates owner node {owner_id} for key {normalized_key}."
                        )
                    break
                raise RuntimeError(f"{operation} exceeded the safety hop limit")

            # Chọn bước nhảy kế tiếp (log được ghi trong hàm)
            next_node, reaches_owner = self._select_next_hop(
                current,
                normalized_key,
                logs,
                hop=hops,
                collect_trace=collect_trace,
            )

            # Phát hiện vòng lặp: node đã thăm lặp lại
            if next_node in visited:
                repair_report = self._repair_node_after_failure(current)
                if collect_trace:
                    logs.append(
                        f"[{hops}] Loop detected: node {next_node} already visited on this route. "
                        f"Node {current} repairs its view; {repair_report['message']}"
                    )
                next_node, reaches_owner = self._select_next_hop(
                    current,
                    normalized_key,
                    logs,
                    hop=hops,
                    collect_trace=collect_trace,
                )

            # Cưỡng bức tiến tới successor khi không tiến triển
            if next_node == current:
                successor = self.nodes[current].successor
                if successor is None:
                    raise RuntimeError(f"{operation} cannot make progress from node {current}")
                next_node = successor
                if collect_trace:
                    logs.append(
                        f"[{hops}] Node {current} has no finger entry closer to key {normalized_key}; "
                        f"fallback to successor node {successor}."
                    )
                reaches_owner = False

            # Tăng số hop đã đi
            hops += 1
            # Cập nhật node hiện tại
            current = next_node

            # Ghi nhận đường đi
            if collect_trace:
                path.append(current)

            # Ghi nhận node đã thăm
            visited.add(current)

            # Dừng khi đã tới owner
            if reaches_owner:
                owner_id = current

        # Ghi log kết thúc định tuyến
        if collect_trace:
            logs.append(
                f"[{hops}] {operation} COMPLETE: owner node = {owner_id}, "
                f"total hops = {hops}, nodes visited = {len(path)}."
            )

        # Trả về kết quả định tuyến
        return {
            "key": normalized_key,
            "owner_id": owner_id,
            "start_node_id": start_node,
            "path": path if collect_trace else [],
            "hops": hops,
            "logs": logs,
        }

    # Tìm chủ sở hữu của một resource theo cơ chế định tuyến nhiều hop
    def lookup(self, resource_id: str | int, start_node_id: int | None = None) -> LookupResult:
        requested_id, key, direct_key = self._resolve_lookup_key(resource_id)

        # Định tuyến lookup để tìm owner
        route = self._route_key(
            key,
            start_node_id=start_node_id,
            operation="Lookup",
            requested_id=requested_id,
        )

        # Logs từ _route_key đã bao gồm log khởi đầu
        logs = route["logs"]

        owner_id = route["owner_id"]
        path = route["path"]
        hops = route["hops"]

        # Kiểm tra resource có tồn tại tại owner không
        owner_node = self.nodes[owner_id]
        found = direct_key or requested_id in owner_node.local_resources

        # Log kết quả kiểm tra resource
        if direct_key:
            logs.append(f"[{hops}] Direct key lookup: key {key} maps to node {owner_id}.")
        elif found:
            logs.append(f"[{hops}] Resource '{requested_id}' FOUND at owner node {owner_id}.")
        else:
            logs.append(f"[{hops}] Resource '{requested_id}' NOT FOUND at owner node {owner_id}.")

        # Log replicas nếu có
        if requested_id in self.resources:
            replica_node_ids = self.resources[requested_id].replica_node_ids
            if replica_node_ids:
                logs.append(f"[{hops}] Replica copies stored on node(s): {replica_node_ids}.")

        return LookupResult(
            requested_id=requested_id,
            key=key,
            owner_id=owner_id,
            start_node_id=route["start_node_id"],
            path=path,
            hops=hops,
            logs=logs,
            found=found,
            direct_key=direct_key,
            replica_node_ids=self.resources[requested_id].replica_node_ids if requested_id in self.resources else [],
        )

    # Chuẩn hóa đầu vào lookup thành bộ ba requested_id, key, direct_key
    def _resolve_lookup_key(self, resource_id: str | int) -> tuple[str, int, bool]:
        # Chuẩn hóa resource_id thành chuỗi
        requested_id = str(resource_id).strip()

        # Nhận diện lookup theo key trực tiếp khi đầu vào là số
        if isinstance(resource_id, int) or requested_id.isdigit():
            return requested_id, int(requested_id) % self.identifier_space, True

        # Băm resource_id để lấy key khi đầu vào là chuỗi
        return requested_id, hash_identifier(requested_id, self.m), False

    # Chọn node bắt đầu cho quá trình định tuyến.
    def _resolve_start_node(self, start_node_id: int | None) -> int:
        # Lấy danh sách node active
        active_ids = self.active_node_ids

        # Chọn node nhỏ nhất khi không chỉ định node bắt đầu
        if start_node_id is None:
            return active_ids[0]

        # Chuẩn hóa node bắt đầu vào không gian định danh
        normalized_start = int(start_node_id) % self.identifier_space

        # Trả về node bắt đầu khi node tồn tại và active
        if normalized_start in self.nodes and self.nodes[normalized_start].active:
            return normalized_start

        # Báo lỗi khi node tồn tại nhưng inactive
        if normalized_start in self.nodes:
            raise ValueError(f"Start node {normalized_start} is failed/inactive")

        # Báo lỗi khi node không tồn tại
        raise ValueError(f"Start node {normalized_start} does not exist")

    # Kiểm tra node hiện tại có sở hữu key không
    def _node_owns_key(self, node_id: int, key: int) -> bool:
        # Đọc trạng thái node
        node = self.nodes[node_id]

        # Bỏ qua khi node chưa có predecessor
        if node.predecessor is None:
            return False

        # Kiểm tra key thuộc khoảng (predecessor, node]
        return in_clockwise_interval(key, node.predecessor, node_id, include_end=True)

    # Lấy successor hiện tại của node để ghi log định tuyến.
    def _successor_id(self, node_id: int) -> int:
        if node_id not in self.nodes:
            raise ValueError(f"Node {node_id} does not exist")

        successor = self.nodes[node_id].successor
        if successor is None:
            raise RuntimeError(f"Node {node_id} has no successor")
        return successor

    # Chọn node kế tiếp cho một bước định tuyến.
    # Trả về tuple (next_node, reaches_owner). Log được ghi trực tiếp vào danh sách logs.
    def _select_next_hop(
        self,
        current_id: int,
        key: int,
        logs: list[str],
        hop: int = 0,
        collect_trace: bool = True,
    ) -> tuple[int, bool]:
        node = self.nodes[current_id]
        successor = node.successor

        # Sửa view khi successor thiếu hoặc đã chết
        if successor is None or successor not in self.nodes or not self.nodes[successor].active:
            failed_id = successor if successor in self.nodes else None
            repair_report = self._repair_node_after_failure(current_id, failed_id)
            if collect_trace:
                logs.append(
                    f"[{hop}] Node {current_id} detected failed successor {successor}; "
                    f"{repair_report['message']}"
                )
            successor = self.nodes[current_id].successor

        if successor is None:
            raise RuntimeError("Current node has no successor")

        # Khi successor trỏ về chính mình (self-loop): dùng link-walk để tìm successor thực sự.
        # Phải advance bằng link-walk result (candidate) chứ không phải successor pointer,
        # vì successor pointer có thể trỏ về chính nó gây infinite loop.
        if successor == current_id:
            real_successor = self._find_successor_by_links(
                (current_id + 1) % self.identifier_space,
                start_node_id=current_id,
            )
            if collect_trace:
                logs.append(
                    f"[{hop}] Node {current_id} successor is self-loop; "
                    f"link-walk finds real successor [{real_successor}] for key {key}."
                )
            return real_successor, False

        # Tìm finger entry gần key nhất
        finger_entry, first_failed = self._closest_preceding_finger(current_id, key)

        # Sửa view khi finger trỏ tới node chết
        if first_failed is not None:
            repair_report = self._repair_node_after_failure(current_id, first_failed)
            if collect_trace:
                logs.append(
                    f"[{hop}] Node {current_id} detected failed finger [{first_failed}]; "
                    f"{repair_report['message']}"
                )
            finger_entry, _ = self._closest_preceding_finger(current_id, key)

        # Không tìm thấy finger entry phù hợp -> nhảy tới successor
        if finger_entry is None:
            if collect_trace:
                logs.append(
                    f"[{hop}] Node {current_id} selects successor [{successor}] "
                    f"(no finger covers key {key})."
                )
            return successor, False

        # Tìm thấy finger entry phù hợp -> nhảy tới node_id của finger
        if collect_trace:
            logs.append(
                f"[{hop}] Node {current_id} selects finger #{finger_entry.index} "
                f"[start={finger_entry.start}] -> node {finger_entry.node_id}."
            )
        return finger_entry.node_id, False

    # Chọn finger entry gần key nhất trong finger table của node hiện tại.
    # Trả về tuple (finger_entry, first_failed_finger) hoặc (None, first_failed_finger).
    # Thuật toán: duyệt từ mũi lớn xuống, chọn entry có start lớn nhất mà start <= key < interval_end.
    def _closest_preceding_finger(
        self, current_id: int, key: int
    ) -> tuple[FingerEntry | None, int | None]:
        node = self.nodes[current_id]
        first_failed_finger: int | None = None

        for entry in reversed(node.finger_table):
            candidate = entry.node_id

            # Bỏ qua chính mình
            if candidate == current_id:
                continue

            # Ghi nhận finger trỏ tới node chết
            if candidate not in self.nodes or not self.nodes[candidate].active:
                if first_failed_finger is None:
                    first_failed_finger = candidate
                continue

            # Chọn finger khi key nằm trong khoảng [start, interval_end)
            if in_clockwise_interval(
                key,
                entry.start,
                entry.interval_end,
                include_start=True,
                include_end=False,
            ):
                return entry, first_failed_finger

        return None, first_failed_finger

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
    
    # Tìm successor kế tiếp đang hoạt động trên vòng định danh.
    # Dùng active_node_ids (danh sách sorted) làm oracle để tìm successor/predecessor đúng nhất.
    # Đây là hàm repair/safety, không phải overlay routing.
    def _find_active_successor(self, node_id: int) -> int:
        active_ids = self.active_node_ids
        if not active_ids:
            raise RuntimeError("No active nodes are available")
        if len(active_ids) == 1:
            return node_id

        # Tìm node nhỏ nhất lớn hơn node_id, wrap về node đầu tiên nếu không có
        for nid in active_ids:
            if nid > node_id:
                return nid
        return active_ids[0]

    # Tìm predecessor kế tiếp đang hoạt động trên vòng định danh.
    def _find_active_predecessor(self, node_id: int) -> int:
        active_ids = self.active_node_ids
        if not active_ids:
            raise RuntimeError("No active nodes are available")
        if len(active_ids) == 1:
            return node_id

        # Tìm node lớn nhất nhỏ hơn node_id, wrap về node cuối cùng nếu không có
        predecessor = None
        for nid in active_ids:
            if nid < node_id:
                predecessor = nid
        return predecessor if predecessor is not None else active_ids[-1]

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
        # Verify bằng cách route lại theo overlay thay vì dùng oracle find_successor().
        # Điều này đảm bảo mô phỏng không dựa vào "danh sách node trung tâm".
        for resource in self.resources.values():
            route = self._route_key(resource.key, operation="VerifyResource", requested_id=resource.resource_id)
            if route["owner_id"] != resource.owner_id:
                return False
            if resource.resource_id not in self.nodes[resource.owner_id].local_resources:
                return False
            if len(resource.replica_node_ids) > self.replication_count:
                return False
            if len(resource.replica_node_ids) != len(set(resource.replica_node_ids)):
                return False
            if resource.owner_id in resource.replica_node_ids:
                return False
            for replica_id in resource.replica_node_ids:
                if replica_id not in self.nodes or not self.nodes[replica_id].active:
                    return False
                if resource.resource_id not in self.nodes[replica_id].local_resources:
                    return False
        return True

    # Kiểm tra tính toàn vẹn của bảng định tuyến: đảm bảo mọi ngón trỏ (finger) trỏ tới đúng successor mong muốn
    def verify_finger_tables(self) -> bool:
        # Verify finger table bằng cách route từ chính node đó tới start.
        # Tránh dùng oracle find_successor() (vốn biết toàn bộ active_node_ids).
        for node_id in self.active_node_ids:
            for entry in self.nodes[node_id].finger_table:
                route = self._route_key(
                    entry.start,
                    start_node_id=node_id,
                    operation="VerifyFinger",
                    requested_id=str(entry.start),
                )
                expected = route["owner_id"]
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
        # Phiên bản mức 1: không dùng active_node_ids (global sorted list).
        candidates = [node_id for node_id, node in self.nodes.items() if node.active]
        if not candidates:
            raise RuntimeError("No active nodes are available")
        return self._rng.choice(candidates)


def build_default_ring() -> ChordRing:
    ring = ChordRing(m=16, seed=61)
    ring.initialize_network(node_count=50, resource_count=1000)
    return ring



def validate_lookup_batch(ring: ChordRing, resources: Iterable[str]) -> list[LookupResult]:
    results: list[LookupResult] = []

    for resource_id in resources:
        start_node = ring.choose_random_node()
        results.append(ring.lookup(resource_id, start_node_id=start_node))

    return results
