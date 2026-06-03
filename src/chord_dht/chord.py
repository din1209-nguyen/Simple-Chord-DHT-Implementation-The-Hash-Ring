from __future__ import annotations

import random
from typing import Any

from .identifiers import hash_identifier, hash_resource, in_clockwise_interval
from .models import FingerEntry, LookupResult, Node, ResourceRecord

# Mô phỏng vòng Chord bằng lớp ChordRing
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
        # Lọc và sắp xếp node active theo chiều tăng dần
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

            # Tham gia ring thông qua node khởi tạo
            self.join(node_id, known_node_id=first_id)

            # Chạy protocol để hội tụ qua stabilize/notify/fix_fingers
            self.run_protocol_until_stable()

        # Chạy thêm cho tới khi routing state không đổi sau một chu kỳ finger table
        self.run_protocol_until_stable()

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

    # Chụp snapshot trạng thái routing của tất cả node active để so sánh khi hội tụ
    def _routing_snapshot(self) -> tuple[tuple[int, int | None, int | None, tuple[int, ...]], ...]:
        return tuple(
            (
                node_id,
                self.nodes[node_id].predecessor,
                self.nodes[node_id].successor,
                tuple(entry.node_id for entry in self.nodes[node_id].finger_table),
            )
            for node_id in self.active_node_ids
        )

    # Chạy một tick Chord cho stabilize, check predecessor và fix finger
    def run_protocol_tick(self) -> None:
        # Chụp snapshot danh sách node active
        node_ids = list(self.active_node_ids)

        # Duyệt từng node để stabilize
        for node_id in node_ids:
            self.stabilize_one(node_id)

        # Duyệt từng node để kiểm tra predecessor
        for node_id in node_ids:
            self.check_predecessor_one(node_id)

        # Sửa một finger entry theo vị trí phụ thuộc vào _protocol_ticks % m
        for node_id in node_ids:
            self.fix_fingers_one(node_id)

        # Tăng tick protocol
        self._protocol_ticks += 1

    # Chạy các bước protocol theo nhiều vòng
    def run_protocol(self, *, rounds: int = 1) -> None:
        # Kiểm tra số vòng chạy protocol
        if rounds < 0:
            raise ValueError("rounds must be non-negative")

        # Lặp qua từng vòng hội tụ
        for _ in range(rounds):
            self.run_protocol_tick()

    # Chạy protocol tới khi routing state không đổi; tối thiểu m tick vì finger table có m dòng
    def run_protocol_until_stable(self, *, max_ticks: int | None = None) -> int:
        if not self.active_node_ids:
            return 0

        # Chord có m finger entry, nên cần ít nhất m tick để quét đủ một vòng
        min_ticks = self.m
        tick_limit = (
            max_ticks
            if max_ticks is not None
            else max(min_ticks * 4, len(self.active_node_ids) * self.m * 2)
        )
        if tick_limit < 0:
            raise ValueError("max_ticks must be non-negative")

        ticks = 0

        # Chụp snapshot ban đầu để so sánh khi hội tụ
        previous = self._routing_snapshot()

        # Chạy protocol cho tới khi hội tụ hoặc chạm ngưỡng tick tối đa
        while ticks < tick_limit:
            self.run_protocol_tick()
            ticks += 1
            current = self._routing_snapshot()
            # Dừng sau một chu kỳ finger table khi snapshot không còn thay đổi
            if ticks >= min_ticks and current == previous:
                break
            previous = current
        return ticks

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
            self.nodes[node_id].successor = self._find_active_successor(node_id)
            successor_id = self.nodes[node_id].successor

        # Đọc predecessor của successor
        successor_predecessor = self.nodes[successor_id].predecessor

        # Cập nhật successor khi có node nằm giữa
        if (
            successor_predecessor is not None
            and successor_predecessor in self.nodes
            and self.nodes[successor_predecessor].active
        ):
            if in_clockwise_interval(
                successor_predecessor,
                node_id,
                successor_id,
                include_start=False,
                include_end=False,
            ):
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
        if in_clockwise_interval(
            potential_predecessor,
            current_predecessor,
            node_id,
            include_start=False,
            include_end=False,
        ):
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

        # Định tuyến qua overlay Chord để tìm successor(start)
        successor_id = self._route_key(
            start,
            start_node_id=node_id,
            operation="FixFingers",
            requested_id=str(start),
            collect_trace=False,
        )["owner_id"]

        # Gán finger entry đã cập nhật
        self.nodes[node_id].finger_table[finger_index - 1] = FingerEntry(
            index=finger_index,
            start=start,
            interval_end=(node_id + 2**finger_index) % self.identifier_space,
            node_id=successor_id,
        )

    # Sinh danh sách ID duy nhất từ tiền tố và seed để đảm bảo tính tái lập
    def _generate_unique_ids(self, prefix: str, count: int) -> list[int]:
        generated: list[int] = []
        used: set[int] = set()
        attempt = 0

        # Giới hạn số lần lặp để tránh kẹt khi không gian ID quá hẹp
        limit = max(count * 1000, self.identifier_space * 2)

        # Sinh ID cho đến khi đủ số lượng yêu cầu hoặc chạm ngưỡng giới hạn
        while len(generated) < count and attempt < limit:
            # Tạo chuỗi đầu vào theo attempt
            raw = f"{prefix}:{self.seed}:{attempt}"
            # Băm chuỗi để lấy ID
            candidate = hash_identifier(raw, self.m)
            attempt += 1

            # Bỏ qua nếu ID sinh ra bị trùng với ID đã có
            if candidate in used:
                continue

            # Ghi nhận ID hợp lệ
            used.add(candidate)
            generated.append(candidate)

        # Kiểm tra thoát vòng lặp mà chưa đủ số lượng, báo lỗi hệ thống
        if len(generated) != count:
            raise RuntimeError("Unable to generate enough unique identifiers")
        return generated

    # Tìm successor của key bằng định tuyến Chord qua finger table
    def find_successor(self, key: int, start_node_id: int | None = None) -> int:
        route = self._route_key(
            key,
            start_node_id=start_node_id,
            operation="FindSuccessor",
            requested_id=str(key),
            collect_trace=False,
        )
        return route["owner_id"]

    # Tìm successor active của key bằng snapshot node active trong mô phỏng
    def _active_successor_for_key(self, key: int) -> int:
        active_ids = self.active_node_ids
        if not active_ids:
            raise RuntimeError("No active nodes are available")

        # Chuẩn hóa key vào không gian định danh
        normalized_key = int(key) % self.identifier_space

        # Tìm successor active đầu tiên có ID >= normalized_key
        for node_id in active_ids:
            if normalized_key <= node_id:
                return node_id

        # Nếu không có thì successor là node active đầu tiên (vòng lặp qua điểm 0)
        return active_ids[0]

    # Kiểm tra tính hợp lệ của ID do người dùng nhập vào thông qua UI hoặc API
    def _validate_identifier(self, value: int) -> int:
        node_id = int(value)

        # Kiểm tra node ID nhập tay nằm trong giới hạn không gian định danh
        if not 0 <= node_id < self.identifier_space:
            raise ValueError(
                f"node_id must be between 0 and {self.identifier_space - 1}"
            )
        return node_id

    # Sinh tự động một ID trống khi thêm node mà không chỉ định ID
    def _next_available_node_id(self) -> int:
        # Thử dần các giá trị hash để chọn ra một ID hợp lệ
        for attempt in range(self.identifier_space):
            candidate = hash_identifier(f"manual-node:{self.seed}:{attempt}", self.m)
            # Kiểm tra ID băm ra chưa tồn tại trong danh sách quản lý, sử dụng luôn ID này
            if candidate not in self.nodes:
                return candidate
        raise RuntimeError("No free node identifier is available")

    # Thêm một node mới vào mạng hoặc kích hoạt lại một node đã từng bị tắt (kill)
    def add_node(self, node_id: int | None = None) -> dict[str, Any]:
        # Sinh ID mới hoặc kiểm tra ID do người dùng truyền vào
        new_node_id = (
            self._next_available_node_id()
            if node_id is None
            else self._validate_identifier(node_id)
        )

        # Kiểm tra ID đã tồn tại và node đang chạy, báo lỗi để chặn trùng lặp
        if new_node_id in self.nodes and self.nodes[new_node_id].active:
            raise ValueError(f"Node {new_node_id} already exists")

        active_before_join = [
            node_id for node_id in self.active_node_ids if node_id != new_node_id
        ]

        # Xử lý logic tạo hoặc bật lại node:
        if new_node_id in self.nodes:
            # Kiểm tra node cũ từng bị tắt để bật lại cờ active
            self.nodes[new_node_id].active = True
            self.nodes[new_node_id].predecessor = None
            self.nodes[new_node_id].successor = None
            self.nodes[new_node_id].finger_table = []
            self.nodes[new_node_id].local_resources.clear()
        else:
            # Kiểm tra node hoàn toàn mới để khởi tạo object
            self.nodes[new_node_id] = Node(node_id=new_node_id)

        # Xóa ID này khỏi danh sách node chết (nếu có)
        self.failed_nodes.discard(new_node_id)

        known_node_id = None
        if active_before_join:
            known_node_id = self._rng.choice(active_before_join)
            self.join(new_node_id, known_node_id=known_node_id)
            self.run_protocol_until_stable()
        else:
            # Gán successor về chính node mới khi đây là node active đầu tiên
            self.nodes[new_node_id].successor = new_node_id

            # Gán predecessor về chính node mới khi ring chỉ có một node
            self.nodes[new_node_id].predecessor = new_node_id

            # Chạy một vòng protocol để khởi tạo finger table ban đầu
            self.run_protocol(rounds=1)

        # Nhận primary/replica theo khoảng predecessor-successor mà node mới làm thay đổi
        rebalanced_resources = self._rebalance_resources_after_node_join(new_node_id)

        # Trả về báo cáo join node cho API/UI
        return {
            "node_id": new_node_id,
            "active_nodes": len(self.active_node_ids),
            "known_node_id": known_node_id,
            "rebalanced_resources": rebalanced_resources,
            "message": f"Node {new_node_id} joined the ring successfully.",
        }

    # Thêm resource mới vào ring và gán cho owner phù hợp
    def add_resource(self, resource_id: str) -> dict[str, Any]:
        # Cắt bỏ khoảng trắng dư thừa để định dạng chuẩn
        normalized_id = str(resource_id).strip()

        # Xác thực đầu vào
        if not normalized_id:
            raise ValueError("resource_id is required")

        # Băm resource thành digest SHA-1 và key rồi route Put để tìm owner
        digest, key = hash_resource(normalized_id, self.m)

        # Định tuyến key qua Chord để tìm node owner
        route = self._route_key(key, operation="Put", requested_id=normalized_id)

        # Lấy owner_id từ kết quả định tuyến
        owner_id = route["owner_id"]

        # Lấy node owner để kiểm tra trùng resource trong local storage
        owner_node = self.nodes[owner_id]

        # Chặn tạo resource trùng tại owner hiện tại
        if normalized_id in owner_node.local_resources:
            raise ValueError(f"Resource {normalized_id} already exists")

        # Tạo bản ghi metadata resource theo owner vừa tìm được
        resource = ResourceRecord(normalized_id, digest, key, owner_id)

        # Cập nhật metadata UI sau khi owner thực tế đã được xác định qua route Chord
        self.resources[normalized_id] = resource

        # Ghi resource vào owner và các replica theo cấu hình hiện tại
        self._place_resource_copies(resource)

        # Trả về resource mới cùng trace định tuyến Put
        return {
            "resource": resource.to_dict(),
            "put_path": route["path"],
            "put_hops": route["hops"],
            "put_logs": route["logs"],
            "message": f"Resource {normalized_id} added successfully.",
        }

    # Đổi ID resource, băm lại key mới và chuyển owner nếu cần
    def update_resource(self, old_resource_id: str, new_resource_id: str) -> dict[str, Any]:
        # Chuẩn hóa dữ liệu đầu vào
        old_id = str(old_resource_id).strip()
        new_id = str(new_resource_id).strip()

        # Kiểm tra điều kiện bắt buộc
        if not old_id:
            raise ValueError("old_resource_id is required")
        if not new_id:
            raise ValueError("new_resource_id is required")

        # Route tới owner thực tế của resource cũ thay vì tin vào metadata UI
        _, old_key = hash_resource(old_id, self.m)

        # Định tuyến key cũ để tìm owner đang thật sự giữ resource
        old_route = self._route_key(old_key, operation="UpdateLookup", requested_id=old_id)

        # Lấy owner của resource cũ từ kết quả định tuyến
        old_owner_id = old_route["owner_id"]

        # Lấy node owner cũ để kiểm tra resource tồn tại
        old_owner_node = self.nodes[old_owner_id]

        # Chặn update khi resource cũ không tồn tại tại owner thật
        if old_id not in old_owner_node.local_resources:
            raise ValueError(f"Resource {old_id} does not exist")

        # Bỏ qua các bước xử lý nặng nếu ID không thực sự thay đổi
        if new_id == old_id:
            return {
                "resource": old_owner_node.local_resources[old_id].to_dict(),
                "message": "Resource ID is unchanged.",
            }

        # Kiểm tra ID mới bằng cách route tới owner của key mới
        digest, key = hash_resource(new_id, self.m)

        # Định tuyến key mới để tìm owner mới
        route = self._route_key(key, operation="Put", requested_id=new_id)

        # Lấy owner mới từ kết quả định tuyến
        owner_id = route["owner_id"]

        # Chặn update nếu resource mới đã tồn tại tại owner mới
        if new_id in self.nodes[owner_id].local_resources:
            raise ValueError(f"Resource {new_id} already exists")

        # Xóa record cũ khỏi metadata UI và khỏi mọi bản local/replica cũ
        old_resource = old_owner_node.local_resources[old_id]

        # Xóa metadata resource cũ khỏi bảng trung tâm
        self.resources.pop(old_id, None)

        # Xóa mọi bản copy cũ khỏi owner và replica
        self._remove_resource_copies(old_id, resource=old_resource)

        # Tạo resource mới tại owner được route theo key mới
        resource = ResourceRecord(new_id, digest, key, owner_id)

        # Lưu metadata resource mới
        self.resources[new_id] = resource

        # Ghi resource mới vào owner và replica mới
        self._place_resource_copies(resource)

        # Trả về kết quả update cùng trace Put của key mới
        return {
            "old_resource_id": old_id,
            "resource": resource.to_dict(),
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

        # Route bằng key của resource để tìm owner thực tế trước khi xóa
        _, key = hash_resource(normalized_id, self.m)

        # Định tuyến Delete tới owner hiện tại của resource
        route = self._route_key(key, operation="Delete", requested_id=normalized_id)

        # Lấy owner hiện tại từ kết quả định tuyến
        owner_id = route["owner_id"]

        # Lấy node owner để kiểm tra resource tồn tại
        owner_node = self.nodes[owner_id]

        # Chặn xóa khi owner không thật sự giữ resource
        if normalized_id not in owner_node.local_resources:
            raise ValueError(f"Resource {normalized_id} does not exist")

        # Lấy bản ghi từ owner local vì đây là nguồn dữ liệu thật trong mô phỏng P2P
        removed = owner_node.local_resources[normalized_id]

        # Xóa metadata resource khỏi bảng trung tâm
        self.resources.pop(normalized_id, None)

        # Xóa mọi bản copy khỏi owner và replica
        self._remove_resource_copies(normalized_id, resource=removed)

        # Trả về resource đã xóa cùng trace Delete
        return {
            "resource": removed.to_dict(),
            "delete_path": route["path"],
            "delete_hops": route["hops"],
            "delete_logs": route["logs"],
            "message": f"Resource {normalized_id} deleted successfully.",
        }

    # Chạy hội tụ protocol để cập nhật routing state mà không rebalance dữ liệu toàn cục
    def stabilize(self) -> dict[str, Any]:
        # Lấy danh sách node active hiện tại
        active_ids = self.active_node_ids

        # Trả về sớm khi ring không còn node active
        if not active_ids:
            return {"active_nodes": 0, "message": "No active nodes are available."}

        # Chạy protocol cho tới khi routing state hội tụ
        ticks = self.run_protocol_until_stable()

        # Trả về số node active và số tick đã chạy
        return {
            "active_nodes": len(active_ids),
            "protocol_ticks": ticks,
            "message": "Routing state stabilized successfully.",
        }

    # Cân bằng lại dữ liệu chịu ảnh hưởng trực tiếp khi node mới tham gia ring
    def _rebalance_resources_after_node_join(self, new_node_id: int) -> int:
        # Lấy node mới để đọc predecessor và successor sau join
        new_node = self.nodes[new_node_id]

        # Xử lý trường hợp ring chỉ có node mới đang active
        if new_node.predecessor == new_node_id or len(self.active_node_ids) == 1:
            # Khởi tạo bộ đếm resource được chuyển owner
            moved = 0

            # Duyệt toàn bộ resource còn sống để gán về node duy nhất
            for resource in self._unique_active_local_resources().values():
                # Bỏ qua resource đã thuộc node mới
                if resource.owner_id != new_node_id:
                    # Ghi lại các holder cũ để dọn copy không còn hợp lệ
                    old_holder_ids = self._copy_holder_ids(resource)

                    # Gán owner mới là node duy nhất trong ring
                    resource.owner_id = new_node_id

                    # Đặt lại copy resource theo owner mới
                    self._place_resource_copies(resource, previous_holder_ids=old_holder_ids)

                    # Tăng bộ đếm resource đã chuyển
                    moved += 1
            return moved

        # Bỏ qua cân bằng dữ liệu nếu node mới chưa có predecessor hợp lệ
        if new_node.predecessor is None:
            return 0

        # Chuyển primary cho các key thuộc khoảng node mới nhận
        moved_primary_count = self._adopt_primary_resources_for_joined_node(new_node_id)

        # Cập nhật replica cho các owner lân cận vì node mới chen vào successor chain
        touched_resources = self._refresh_replica_sets_around_joined_node(new_node_id)

        # Trả về tổng số resource primary/replica bị ảnh hưởng
        return moved_primary_count + touched_resources

    # Chuyển primary cho các resource thuộc khoảng mà node mới nhận trách nhiệm
    def _adopt_primary_resources_for_joined_node(self, new_node_id: int) -> int:
        # Lấy node mới để đọc predecessor và successor
        new_node = self.nodes[new_node_id]

        # Lấy predecessor làm biên trái của khoảng key node mới nhận
        predecessor_id = new_node.predecessor

        # Bỏ qua khi predecessor chưa hội tụ
        if predecessor_id is None:
            return 0

        # Khởi tạo bộ đếm resource được chuyển primary
        moved = 0

        # Khởi tạo tập ứng viên resource cần xét
        candidates: dict[str, ResourceRecord] = {}

        # Lấy resource từ successor cũ vì các key đó từng thuộc successor
        successor_id = new_node.successor

        # Chỉ lấy resource từ successor cũ nếu successor còn active
        if successor_id in self.nodes and self.nodes[successor_id].active:
            candidates.update(self.nodes[successor_id].local_resources)

        # Duyệt các resource ứng viên để kiểm tra có thuộc khoảng node mới không
        for resource in candidates.values():
            # Bỏ qua resource không nằm trong khoảng (predecessor, new_node]
            if not in_clockwise_interval(
                resource.key,
                predecessor_id,
                new_node_id,
                include_start=False,
                include_end=True,
            ):
                continue

            # Bỏ qua resource đã có owner là node mới
            if resource.owner_id == new_node_id:
                continue

            # Ghi lại holder cũ trước khi đổi owner
            old_holder_ids = self._copy_holder_ids(resource)

            # Chuyển owner chính sang node mới
            resource.owner_id = new_node_id

            # Cập nhật metadata resource theo owner mới
            self.resources[resource.resource_id] = resource

            # Đồng bộ lại copy tại owner và replica mới
            self._place_resource_copies(resource, previous_holder_ids=old_holder_ids)

            # Tăng số resource đã chuyển primary
            moved += 1

        return moved

    # Làm mới replica của các resource có owner gần node mới trong successor chain
    def _refresh_replica_sets_around_joined_node(self, new_node_id: int) -> int:
        # Khởi tạo tập owner bị ảnh hưởng với node mới
        affected_owner_ids = {new_node_id}

        # Bắt đầu đi ngược predecessor chain từ node mới
        current = new_node_id

        # Chỉ cần xét số predecessor tương ứng replication_count
        for _ in range(self.replication_count):
            # Lấy predecessor hiện tại trong successor chain
            predecessor = self.nodes[current].predecessor

            # Dừng khi predecessor không hợp lệ hoặc đã quay lại node mới
            if (
                predecessor is None
                or predecessor == new_node_id
                or predecessor not in self.nodes
                or not self.nodes[predecessor].active
            ):
                break

            # Đánh dấu owner predecessor có replica set bị ảnh hưởng
            affected_owner_ids.add(predecessor)

            # Tiếp tục đi ngược predecessor chain
            current = predecessor

        # Khởi tạo bộ đếm resource có replica thay đổi
        touched = 0

        # Duyệt resource còn sống để refresh replica set khi cần
        for resource in self._unique_active_local_resources().values():
            # Bỏ qua resource không thuộc owner bị ảnh hưởng và không chứa node mới
            if resource.owner_id not in affected_owner_ids and new_node_id not in resource.replica_node_ids:
                continue

            # Lưu replica cũ để so sánh sau khi đặt lại copy
            old_replicas = list(resource.replica_node_ids)

            # Đặt lại owner/replica copy theo topology mới
            self._place_resource_copies(resource)

            # Cập nhật metadata trung tâm
            self.resources[resource.resource_id] = resource

            # Tăng bộ đếm nếu replica set thật sự thay đổi
            if old_replicas != resource.replica_node_ids:
                touched += 1

        return touched

    # Tính danh sách node replica đứng sau owner trên vòng Chord
    def _replica_nodes_for_owner(self, owner_id: int) -> list[int]:
        # Xác định replica bằng successor pointer thay vì danh sách active toàn cục
        if self.replication_count == 0:
            return []

        # Bỏ qua khi owner không tồn tại hoặc đã inactive
        if owner_id not in self.nodes or not self.nodes[owner_id].active:
            return []

        # Khởi tạo danh sách replica theo thứ tự successor chain
        replicas: list[int] = []

        # Bắt đầu đi từ owner
        current = owner_id

        # Tối đa đi một vòng để tránh lặp vô hạn
        safety = max(1, len(self.active_node_ids) + 1)

        # Lặp tối đa bằng replication_count để lấy đủ số replica yêu cầu
        for _ in range(self.replication_count):
            # Đọc successor hiện tại của node đang xét
            successor = self.nodes[current].successor

            # Route lại successor khi pointer bị thiếu hoặc trỏ tới node inactive
            if successor is None or successor not in self.nodes or not self.nodes[successor].active:
                # Định tuyến qua finger table để tìm successor active kế tiếp
                successor = self._route_key(
                    (current + 1) % self.identifier_space,
                    start_node_id=current,
                    operation="ReplicaSuccessor",
                    requested_id=str((current + 1) % self.identifier_space),
                    collect_trace=False,
                )["owner_id"]

            # Dừng khi successor quay lại owner vì không còn node khác để replica
            if successor == owner_id:
                break

            # Thêm successor vào replica set nếu chưa có
            if successor not in replicas:
                replicas.append(successor)

            # Dịch con trỏ hiện tại sang successor vừa chọn
            current = successor

            # Kiểm tra successor pointer bị hỏng, dừng sớm
            if len(replicas) >= safety:
                break

        return replicas

    # Gom các node đang giữ bản copy của một resource gồm owner và replica
    def _copy_holder_ids(self, resource: ResourceRecord) -> list[int]:
        # Dùng dict.fromkeys để loại trùng nhưng vẫn giữ thứ tự owner trước replica
        holders = [resource.owner_id, *resource.replica_node_ids]

        # Chỉ trả về holder còn tồn tại trong bảng node
        return list(dict.fromkeys(node_id for node_id in holders if node_id in self.nodes))

    # Xóa các bản copy local khỏi đúng owner và replica đã biết của resource
    def _remove_resource_copies(
        self,
        resource_id: str,
        *,
        resource: ResourceRecord | None = None,
    ) -> None:
        # Tìm record resource từ tham số hoặc từ local resource còn sống
        record = resource or self._unique_active_local_resources().get(resource_id)

        # Bỏ qua khi không còn record để xác định holder cần xóa
        if record is None:
            return

        # Duyệt owner và replica đã biết để xóa copy cũ
        for node_id in self._copy_holder_ids(record):
            self.nodes[node_id].local_resources.pop(resource_id, None)

    # Đặt resource vào owner và các replica hiện tại theo cấu hình replication_count
    def _place_resource_copies(
        self,
        resource: ResourceRecord,
        *,
        previous_holder_ids: list[int] | None = None,
    ) -> None:
        # Lấy danh sách holder cũ từ tham số hoặc từ record hiện tại
        old_holder_ids = (
            list(dict.fromkeys(previous_holder_ids))
            if previous_holder_ids is not None
            else self._copy_holder_ids(resource)
        )

        # Tính lại replica set mỗi lần owner thay đổi hoặc topology thay đổi
        resource.replica_node_ids = self._replica_nodes_for_owner(resource.owner_id)

        # Đồng bộ copy local theo owner/replica set mới
        self._sync_resource_copies(resource, previous_holder_ids=old_holder_ids)

    # Đồng bộ dữ liệu local để chỉ owner/replica hợp lệ đang giữ resource
    def _sync_resource_copies(
        self,
        resource: ResourceRecord,
        *,
        previous_holder_ids: list[int],
    ) -> None:
        # Tính danh sách holder hiện tại sau khi replica set đã được cập nhật
        current_holder_ids = self._copy_holder_ids(resource)

        # Xóa bản cũ khỏi node không còn thuộc replica set mới
        for node_id in previous_holder_ids:
            # Bỏ qua node vẫn còn là holder hoặc node không còn tồn tại
            if node_id in current_holder_ids or node_id not in self.nodes:
                continue

            # Xóa bản copy local khỏi holder cũ
            self.nodes[node_id].local_resources.pop(resource.resource_id, None)

        # Ghi lại resource vào owner và các node replica còn active
        for node_id in current_holder_ids:
            # Lấy node holder hiện tại
            node = self.nodes[node_id]

            # Chỉ ghi copy vào node còn active
            if node.active:
                node.local_resources[resource.resource_id] = resource

    # Vô hiệu hóa một node active để mô phỏng lỗi hoặc churn
    def kill_node(self, node_id: int) -> dict[str, Any]:
        # Đánh dấu node failed và lấy báo cáo impact ban đầu
        impact_report = self.mark_node_failed(node_id)

        # Chạy recovery ngay cho luồng kill nội bộ
        return self.recover_failed_node(node_id, impact_report=impact_report)

    # Đánh dấu node lỗi nhưng chưa sửa routing/resource để UI hiển thị impact
    def mark_node_failed(self, node_id: int) -> dict[str, Any]:
        # Kiểm tra node cần kill có tồn tại không
        if node_id not in self.nodes:
            raise ValueError(f"Node {node_id} does not exist")

        # Chặn kill lại một node đã inactive
        if not self.nodes[node_id].active:
            raise ValueError(f"Node {node_id} is already inactive")

        # Chặn kill node active cuối cùng để ring không rỗng hoàn toàn
        if len(self.active_node_ids) <= 1:
            raise ValueError("Cannot kill the last active node")

        # Lưu predecessor cũ để report và recovery
        old_predecessor = self.nodes[node_id].predecessor

        # Lưu successor cũ để report và recovery
        old_successor = self.nodes[node_id].successor

        # Đánh dấu node không còn active
        self.nodes[node_id].active = False

        # Ghi node vào tập failed_nodes để yêu cầu recover
        self.failed_nodes.add(node_id)

        # Tạo báo cáo impact trước khi chạy recovery
        impact = self.failure_impact_report(node_id)
        impact.update(
            {
                "killed_node_id": node_id,
                "node_id": node_id,
                "old_predecessor": old_predecessor,
                "old_successor": old_successor,
                "active_nodes": len(self.active_node_ids),
                "message": "Node marked as failed. Recovery has not been run yet.",
            }
        )
        return impact

    # Thực hiện recovery tập trung và khôi phục resource từ replica sống
    def recover_failed_node(
        self,
        node_id: int,
        *,
        impact_report: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        # Kiểm tra rào cản lỗi
        if node_id not in self.nodes:
            raise ValueError(f"Node {node_id} does not exist")

        # Chỉ cho recover node đã được đánh dấu failed
        if node_id not in self.failed_nodes or self.nodes[node_id].active:
            raise ValueError(f"Node {node_id} is not marked as failed")

        # Chặn recover khi không còn node active nào làm nguồn sửa ring
        if len(self.active_node_ids) < 1:
            raise ValueError("Cannot recover when no active node is available")

        # Giữ impact report trước recovery để frontend hiển thị đối chiếu
        pre_recovery_impact = impact_report or self.failure_impact_report(node_id)

        # Lưu lại láng giềng cũ để có thông tin report
        old_predecessor = self.nodes[node_id].predecessor
        old_successor = self.nodes[node_id].successor

        # Ngắt node chết khỏi view định tuyến của chính nó
        self.nodes[node_id].predecessor = None
        self.nodes[node_id].successor = None
        self.nodes[node_id].finger_table = []

        # Nối predecessor và successor cũ lại với nhau để vá vòng chính
        if old_predecessor is not None and old_predecessor in self.nodes:
            predecessor = self.nodes[old_predecessor]
            if predecessor.active:
                predecessor.successor = old_successor

        if old_successor is not None and old_successor in self.nodes:
            successor = self.nodes[old_successor]
            if successor.active:
                successor.predecessor = old_predecessor

        # Sửa finger table trước recovery dữ liệu để report khớp impact snapshot lúc Kill
        updated_finger_tables, updated_finger_entries = self._repair_fingers_referencing(node_id)

        # Phục hồi resource từ các bản replica còn sống
        recovered_resources, lost_resources, recovery_details = (
            self._recover_resources_after_node_failure(node_id)
        )

        # Sửa lại owner/replica metadata còn lệch sau khi phục hồi dữ liệu
        reconciled_resources, reconciled_resource_ids = self._reconcile_resource_owners_after_recovery()

        # Tính số replica thực tế có thể đặt theo số node active còn lại
        effective_replica_count = min(self.replication_count, max(0, len(self.active_node_ids) - 1))

        # Xóa node khỏi tập pending recovery sau khi recover xong
        self.failed_nodes.discard(node_id)

        # Trả về báo cáo recovery đầy đủ cho API/UI
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
            "ownership_repaired_resource_ids": reconciled_resource_ids[:10],
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
            "ownership_repaired_resources": reconciled_resources,
            "ownership_repaired_resource_sample_count": min(len(reconciled_resource_ids), 10),
            "ownership_repaired_resource_total_count": len(reconciled_resource_ids),
            "active_nodes": len(self.active_node_ids),
            "impact_report": pre_recovery_impact,
            "message": "Node killed, adjacent links repaired, and replicas recovered where available.",
        }

    # Tạo báo cáo các finger/resource đang bị ảnh hưởng bởi tập node lỗi hiện tại
    def failure_impact_report(self, node_id: int | None = None) -> dict[str, Any]:
        # Sao chép tập failed_nodes hiện tại để không mutate trạng thái gốc
        failed_ids = set(self.failed_nodes)

        # Bổ sung node_id truyền vào khi cần xem impact tức thời
        if node_id is not None:
            failed_ids.add(int(node_id))

        # Liệt kê các finger entry đang trỏ tới node failed
        stale_entries = self._stale_finger_entries(failed_ids)

        # Gom danh sách node có finger warning
        finger_warning_nodes = sorted({entry["node_id"] for entry in stale_entries})

        # Liệt kê resource có owner hoặc replica bị ảnh hưởng
        affected_resources = self._affected_resources(failed_ids)

        # Trả về báo cáo impact tổng hợp
        return {
            "failed_nodes": sorted(failed_ids),
            "finger_warning_nodes": finger_warning_nodes,
            "stale_finger_entries": stale_entries,
            "affected_resources": affected_resources,
            "affected_resource_ids": [item["resource_id"] for item in affected_resources],
            "finger_warning_node_count": len(finger_warning_nodes),
            "stale_finger_entry_count": len(stale_entries),
            "affected_resource_count": len(affected_resources),
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
        # Kiểm tra vòng còn node hoạt động trước khi định tuyến
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
        is_fix_fingers = operation in {"FixFingers", "Join", "RefreshFinger", "BuildFinger", "RepairFinger"}

        # Đọc hệ số giới hạn hop
        hop_multiplier = self._max_route_hops_multiplier

        # Tính giới hạn hop an toàn theo số node active và kích thước finger table
        active_count = max(1, sum(1 for node in self.nodes.values() if node.active))
        max_steps = max(1, active_count * (self.m + 1) * hop_multiplier)

        # Giữ giới hạn hop vừa đủ cho thao tác hội tụ để tránh vòng lặp kéo dài
        if is_fix_fingers:
            max_steps = max(max_steps, active_count * (self.m + 1))

        # Khởi tạo số hop đã đi
        hops = 0

        # Bỏ theo dõi visited khi đang hội tụ
        if is_fix_fingers:
            visited = set()

        # Định tuyến tuần tự cho đến khi xác định được owner của key
        while owner_id is None:
            # Dừng định tuyến khi node hiện tại sở hữu key (predecessor, node]
            if self._node_owns_key(current, normalized_key):
                owner_id = current
                if collect_trace:
                    predecessor = self.nodes[current].predecessor
                    logs.append(
                        f"[{hops}] Node {current} owns key {normalized_key} directly "
                        f"(its ownership interval ({predecessor}, {current}] includes the key); "
                        f"routing stops here (no hop taken)."
                    )
                break

            # Dừng khi vượt giới hạn hop
            if hops >= max_steps:
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
                # Sửa view cục bộ của node hiện tại khi route bị lặp
                repair_report = self._repair_node_after_failure(current)

                # Ghi log repair khi caller yêu cầu trace
                if collect_trace:
                    logs.append(
                        f"[{hops}] Loop detected: node {next_node} already visited on this route. "
                        f"Node {current} repairs its view; {repair_report['message']}"
                    )

                # Chọn lại next hop sau khi repair view cục bộ
                next_node, reaches_owner = self._select_next_hop(
                    current,
                    normalized_key,
                    logs,
                    hop=hops,
                    collect_trace=collect_trace,
                )

            # Cưỡng bức tiến tới successor khi không tiến triển
            if next_node == current:
                # Lấy successor hiện tại làm fallback
                successor = self.nodes[current].successor

                # Báo lỗi nếu node không còn successor để tiếp tục route
                if successor is None:
                    raise RuntimeError(f"{operation} cannot make progress from node {current}")

                # Ép next hop sang successor để tránh kẹt tại cùng node
                next_node = successor

                # Ghi log fallback successor khi caller yêu cầu trace
                if collect_trace:
                    logs.append(
                        f"[{hops}] Node {current} has no finger entry closer to key {normalized_key}; "
                        f"fallback to successor node {successor}."
                    )

                # Đánh dấu chưa chắc đã tới owner sau fallback
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
        # Chuẩn hóa input lookup thành requested_id, key và cờ direct_key
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

        # Lấy owner_id từ kết quả route
        owner_id = route["owner_id"]

        # Lấy path định tuyến để trả về cho UI
        path = route["path"]

        # Lấy số hop đã đi trong quá trình lookup
        hops = route["hops"]

        # Kiểm tra resource có tồn tại tại owner không
        owner_node = self.nodes[owner_id]

        # Xác định found theo lookup trực tiếp key hoặc theo resource trong owner local storage
        found = direct_key or requested_id in owner_node.local_resources

        # Ghi log kết quả kiểm tra resource
        if direct_key:
            logs.append(f"[{hops}] Direct key lookup: key {key} maps to node {owner_id}.")
        elif found:
            logs.append(f"[{hops}] Resource '{requested_id}' FOUND at owner node {owner_id}.")
        else:
            logs.append(f"[{hops}] Resource '{requested_id}' NOT FOUND at owner node {owner_id}.")

        # Ghi log replicas dựa trên bản ghi đang nằm tại owner thực tế
        replica_node_ids = []

        # Chỉ đọc replica khi lookup resource thật và resource tồn tại
        if found and not direct_key:
            replica_node_ids = owner_node.local_resources[requested_id].replica_node_ids
            if replica_node_ids:
                logs.append(f"[{hops}] Replica copies stored on node(s): {replica_node_ids}.")

        # Trả về object LookupResult để API có thể jsonify bằng to_dict
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
            replica_node_ids=replica_node_ids,
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

    # Chọn node bắt đầu cho quá trình định tuyến
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

    # Chọn node kế tiếp cho một bước định tuyến và ghi log nếu cần
    def _select_next_hop(
        self,
        current_id: int,
        key: int,
        logs: list[str],
        hop: int = 0,
        collect_trace: bool = True,
    ) -> tuple[int, bool]:
        # Lấy node hiện tại để đọc successor và finger table
        node = self.nodes[current_id]

        # Đọc successor hiện tại của node
        successor = node.successor

        # Sửa view khi successor thiếu hoặc đã chết
        if successor is None or successor not in self.nodes or not self.nodes[successor].active:
            # Xác định failed_id nếu successor có trong bảng node nhưng inactive
            failed_id = successor if successor in self.nodes else None

            # Sửa view cục bộ của node hiện tại sau khi phát hiện successor lỗi
            repair_report = self._repair_node_after_failure(current_id, failed_id)

            # Ghi log repair successor khi caller yêu cầu trace
            if collect_trace:
                logs.append(
                    f"[{hop}] Node {current_id} detected failed successor {successor}; "
                    f"{repair_report['message']}"
                )

            # Đọc lại successor sau khi repair view
            successor = self.nodes[current_id].successor

        # Báo lỗi nếu node vẫn không có successor sau repair
        if successor is None:
            raise RuntimeError("Current node has no successor")

        # Chuyển thẳng tới successor khi successor chịu trách nhiệm cho key
        if successor != current_id and in_clockwise_interval(
            key,
            current_id,
            successor,
            include_start=False,
            include_end=True,
        ):
            if collect_trace:
                logs.append(
                    f"[{hop}] Node {current_id} selects successor [{successor}] "
                    f"because key {key} is in its ownership interval."
                )
            return successor, True

        # Sửa self-loop successor bằng finger table để tránh vòng lặp vô hạn
        if successor == current_id:
            # Tìm finger tốt nhất để thoát self-loop
            finger_entry, _ = self._closest_preceding_finger(current_id, key)

            # Thử dùng predecessor active khi không có finger phù hợp
            if finger_entry is None:
                predecessor = node.predecessor
                if (
                    predecessor is not None
                    and predecessor != current_id
                    and predecessor in self.nodes
                    and self.nodes[predecessor].active
                ):
                    if collect_trace:
                        logs.append(
                            f"[{hop}] Node {current_id} successor is self-loop; "
                            f"local predecessor [{predecessor}] is used while routing state converges."
                        )
                    return predecessor, False

            # Báo lỗi khi node self-loop không biết peer active nào khác
            if finger_entry is None:
                raise RuntimeError(
                    f"Node {current_id} has self-loop successor and no active finger"
                )

            # Ghi log chọn finger để thoát self-loop
            if collect_trace:
                logs.append(
                    f"[{hop}] Node {current_id} successor is self-loop; "
                    f"finger table selects node [{finger_entry.node_id}] for key {key}."
                )
            return finger_entry.node_id, False

        # Tìm finger entry gần key nhất
        finger_entry, first_failed = self._closest_preceding_finger(current_id, key)

        # Sửa view khi finger trỏ tới node chết
        if first_failed is not None:
            # Repair view cục bộ khi finger table chứa node failed
            repair_report = self._repair_node_after_failure(current_id, first_failed)

            # Ghi log repair finger khi caller yêu cầu trace
            if collect_trace:
                logs.append(
                    f"[{hop}] Node {current_id} detected failed finger [{first_failed}]; "
                    f"{repair_report['message']}"
                )

            # Chọn lại finger sau khi repair view
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

    # Chọn finger entry gần key nhất trong finger table của node hiện tại
    def _closest_preceding_finger(
        self, current_id: int, key: int
    ) -> tuple[FingerEntry | None, int | None]:
        # Lấy node hiện tại để duyệt finger table
        node = self.nodes[current_id]

        # Lưu finger failed đầu tiên phát hiện được để caller repair view
        first_failed_finger: int | None = None

        # Duyệt finger table từ xa nhất về gần nhất theo thuật toán Chord
        for entry in reversed(node.finger_table):
            # Lấy node đích của finger entry
            candidate = entry.node_id

            # Bỏ qua chính mình
            if candidate == current_id:
                continue

            # Ghi nhận finger trỏ tới node chết
            if candidate not in self.nodes or not self.nodes[candidate].active:
                if first_failed_finger is None:
                    first_failed_finger = candidate
                continue

            # Chọn finger khi candidate nằm giữa node hiện tại và key theo chiều kim đồng hồ
            if in_clockwise_interval(
                candidate,
                current_id,
                key,
                include_start=False,
                include_end=False,
            ):
                return entry, first_failed_finger

        return None, first_failed_finger

    # Sửa cục bộ view định tuyến của node phát hiện thông tin đã cũ
    def _repair_node_after_failure(
        self,
        node_id: int,
        failed_node_id: int | None = None,
    ) -> dict[str, Any]:
        # Kiểm tra node cần repair phải tồn tại và còn hoạt động
        if node_id not in self.nodes or not self.nodes[node_id].active:
            raise RuntimeError(f"Cannot repair inactive or missing node {node_id}")

        # Lấy node đang phát hiện lỗi để sửa view định tuyến cục bộ
        node = self.nodes[node_id]

        # Cập nhật predecessor cục bộ nếu predecessor hiện tại vẫn còn active
        node.predecessor = self._find_active_predecessor(node_id)

        # Cập nhật successor cục bộ từ những node active mà node hiện tại đang biết
        node.successor = self._find_active_successor(node_id)

        # Sửa finger entry trỏ tới node chết bằng successor trong view cục bộ
        node.finger_table = [
            FingerEntry(
                index=entry.index,
                start=entry.start,
                interval_end=entry.interval_end,
                node_id=self._local_successor_for_key(entry.start, node_id)
                if entry.node_id not in self.nodes or not self.nodes[entry.node_id].active
                else entry.node_id,
            )
            for entry in node.finger_table
        ]

        # Tạo đoạn mô tả node lỗi đã được phát hiện để đưa vào log routing
        detected = (
            f" detected failed node {failed_node_id} and" if failed_node_id is not None else ""
        )

        # Trả về báo cáo repair cục bộ mà không khôi phục dữ liệu
        return {
            "node_id": node_id,
            "failed_node_id": failed_node_id,
            "moved_resources": 0,
            "message": (
                f"Node {node_id}{detected} repaired its local routing view; "
                "data recovery is handled by the recovery workflow."
            ),
        }

    # Tìm successor active kế tiếp từ view cục bộ của node
    def _find_active_successor(self, node_id: int) -> int:
        # Kiểm tra node hiện tại có active không trước khi tìm successor
        if node_id not in self.nodes or not self.nodes[node_id].active:
            raise RuntimeError(f"Node {node_id} is not active")

        # Tìm successor của điểm ngay sau node hiện tại để tránh chọn lại chính node đó
        return self._local_successor_for_key((node_id + 1) % self.identifier_space, node_id)

    # Lấy các node active mà một node biết qua successor, finger table và predecessor
    def _active_known_node_ids(self, node_id: int) -> list[int]:
        # Lấy node hiện tại để đọc successor, predecessor và finger table cục bộ
        node = self.nodes[node_id]

        # Khởi tạo danh sách ứng viên theo đúng những gì node hiện tại đang biết
        candidates: list[int] = []

        # Thêm successor hiện tại vào danh sách ứng viên cục bộ
        if node.successor is not None:
            candidates.append(node.successor)

        # Thêm các node xuất hiện trong finger table vào danh sách ứng viên cục bộ
        candidates.extend(entry.node_id for entry in node.finger_table)

        # Thêm predecessor làm fallback khi successor và finger chưa đủ thông tin
        if node.predecessor is not None:
            candidates.append(node.predecessor)

        # Khởi tạo danh sách node active đã lọc trùng
        active_known_ids: list[int] = []
        for candidate in candidates:
            # Bỏ qua chính node hiện tại để tránh tự chọn mình khi còn peer khác
            if candidate == node_id:
                continue

            # Giữ lại ứng viên còn active và loại trùng theo thứ tự node biết được
            if (
                candidate in self.nodes
                and self.nodes[candidate].active
                and candidate not in active_known_ids
            ):
                active_known_ids.append(candidate)

        return active_known_ids

    # Chọn successor gần nhất của một key trong phạm vi view cục bộ của node
    def _local_successor_for_key(self, key: int, node_id: int) -> int:
        # Lấy các node active mà node hiện tại biết
        candidates = self._active_known_node_ids(node_id)

        # Trả về chính node đó khi view cục bộ chưa biết node active khác
        if not candidates:
            return node_id

        # Chuẩn hóa key vào không gian định danh Chord
        normalized_key = int(key) % self.identifier_space

        # Chọn node active gần key nhất theo chiều kim đồng hồ
        return min(
            candidates,
            key=lambda candidate: (candidate - normalized_key) % self.identifier_space,
        )

    # Tìm predecessor active từ view cục bộ của node
    def _find_active_predecessor(self, node_id: int) -> int | None:
        if node_id not in self.nodes or not self.nodes[node_id].active:
            raise RuntimeError(f"Node {node_id} is not active")

        # Chỉ chọn predecessor khi predecessor còn sống
        predecessor = self.nodes[node_id].predecessor
        if predecessor in self.nodes and self.nodes[predecessor].active:
            return predecessor
        return None

    # Gom các resource duy nhất đang xuất hiện trong local_resources của node active
    def _unique_active_local_resources(self) -> dict[str, ResourceRecord]:
        resources: dict[str, ResourceRecord] = {}

        # Chỉ đọc local storage của node còn sống, không đọc dữ liệu từ node đã chết
        for node_id in self.active_node_ids:
            for resource_id, resource in self.nodes[node_id].local_resources.items():
                if resource_id not in resources or resource.owner_id == node_id:
                    resources[resource_id] = resource

        return resources

    # Xóa metadata UI của resource đã mất vì owner chết và không còn replica sống
    def _drop_lost_resources_from_metadata(self) -> tuple[int, list[str]]:
        # Khởi tạo số resource bị mất
        lost = 0

        # Khởi tạo danh sách ID resource bị mất
        lost_resource_ids: list[str] = []

        # Dọn metadata trung tâm sau khi thuật toán recovery đã chạy
        for resource_id, resource in list(self.resources.items()):
            # Lấy owner hiện tại của resource từ bảng node
            owner = self.nodes.get(resource.owner_id)

            # Bỏ qua resource có owner còn active hoặc owner không có trong bảng node
            if owner is None or owner.active:
                continue

            # Bỏ qua resource vẫn còn bản copy sống để có thể phục hồi
            if self._live_resource_copy_holders(resource):
                continue

            # Xóa các bản copy còn được metadata biết tới
            self._remove_resource_copies(resource_id, resource=resource)

            # Xóa metadata resource khỏi bảng trung tâm
            self.resources.pop(resource_id, None)

            # Tăng số resource bị mất
            lost += 1

            # Ghi nhận ID resource bị mất để report
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
        # Lấy node failed để dọn local resource không còn tin cậy
        failed_node = self.nodes[failed_node_id]

        # Khởi tạo số resource phục hồi được
        recovered = 0

        # Khởi tạo danh sách resource phục hồi được
        recovered_resource_ids: list[str] = []

        # Khởi tạo danh sách resource được sửa replica set
        replica_repaired_resource_ids: list[str] = []

        # Kiểm tra node chết không còn được xem là nguồn dữ liệu hợp lệ
        failed_node.local_resources.clear()

        # Tìm resource cần phục hồi bằng cách đọc replica còn sống trên các node active
        local_resources = self._unique_active_local_resources()

        # Duyệt các resource còn có copy sống
        for resource in local_resources.values():
            # Chỉ phục hồi resource có owner là node failed
            if resource.owner_id != failed_node_id:
                continue

            # Lưu holder cũ để dọn copy stale sau khi đổi owner
            old_holder_ids = self._copy_holder_ids(resource)

            # Tính owner đúng sau khi node chết bằng successor active của key
            # Tránh lookup route vì route có thể tự sửa view và làm lệch report
            new_owner_id = self._active_successor_for_key(resource.key)

            # Kiểm tra xem còn node active nào giữ bản replica thật hay không
            live_copy_holders = self._live_resource_copy_holders(
                resource,
                exclude_ids={failed_node_id},
            )

            # Bỏ qua resource không còn copy sống để promote
            if not live_copy_holders:
                continue

            # Có replica sống thì promote sang owner mới và tạo lại đủ replica
            resource.owner_id = new_owner_id
            self.resources[resource.resource_id] = resource
            self._place_resource_copies(resource, previous_holder_ids=old_holder_ids)
            recovered += 1
            recovered_resource_ids.append(resource.resource_id)

        # Sửa replica set cho resource mà node chết chỉ giữ bản replica
        for resource in list(self._unique_active_local_resources().values()):
            # Bỏ qua resource không chứa failed node trong replica set
            if failed_node_id not in resource.replica_node_ids:
                continue

            # Ghi nhận resource được sửa replica set
            replica_repaired_resource_ids.append(resource.resource_id)

            # Lưu holder cũ để dọn copy stale
            old_holder_ids = self._copy_holder_ids(resource)

            # Loại failed node khỏi replica set
            resource.replica_node_ids = [
                replica_id
                for replica_id in resource.replica_node_ids
                if replica_id != failed_node_id
            ]

            # Cập nhật metadata resource sau khi sửa replica set
            self.resources[resource.resource_id] = resource

            # Đặt lại copy để bù replica thiếu nếu còn node active
            self._place_resource_copies(resource, previous_holder_ids=old_holder_ids)

        # Sau cùng mới dọn metadata UI cho resource không còn replica sống nào để phục hồi
        lost, lost_resource_ids = self._drop_lost_resources_from_metadata()

        return recovered, lost, {
            "recovered_resource_ids": recovered_resource_ids,
            "replica_repaired_resource_ids": replica_repaired_resource_ids,
            "lost_resource_ids": lost_resource_ids,
        }

    # Đồng bộ lại owner/replica còn lệch sau recovery để metadata và local copy thống nhất
    def _reconcile_resource_owners_after_recovery(self) -> tuple[int, list[str]]:
        # Khởi tạo danh sách resource được sửa owner/replica
        repaired_resource_ids: list[str] = []

        # Duyệt các resource còn có bản copy sống
        for resource in list(self._unique_active_local_resources().values()):
            # Gom các holder theo metadata hiện tại
            old_holder_ids = set(self._copy_holder_ids(resource))

            # Bổ sung các holder thật đang có local copy
            old_holder_ids.update(self._live_resource_copy_holders(resource))

            # Bỏ qua resource không có holder nào
            if not old_holder_ids:
                continue

            # Tính owner đúng theo successor(key) sau recovery
            expected_owner_id = self._active_successor_for_key(resource.key)

            # Tính replica set đúng theo owner mới
            expected_replica_ids = self._replica_nodes_for_owner(expected_owner_id)

            # Xác định resource có cần repair owner/replica/local copy không
            needs_repair = (
                resource.owner_id != expected_owner_id
                or resource.replica_node_ids != expected_replica_ids
                or resource.resource_id not in self.nodes[expected_owner_id].local_resources
            )

            # Bỏ qua resource đã đúng hoàn toàn
            if not needs_repair:
                continue

            # Chuyển holder set về list có thứ tự ổn định
            previous_holder_ids = list(dict.fromkeys(old_holder_ids))

            # Cập nhật owner đúng cho resource
            resource.owner_id = expected_owner_id

            # Cập nhật metadata trung tâm
            self.resources[resource.resource_id] = resource

            # Đồng bộ lại copy theo owner/replica đúng
            self._place_resource_copies(resource, previous_holder_ids=previous_holder_ids)

            # Ghi nhận resource đã được repair
            repaired_resource_ids.append(resource.resource_id)

        return len(repaired_resource_ids), repaired_resource_ids

    # Sửa các dòng Finger Table đang trỏ tới node vừa chết
    def _repair_fingers_referencing(self, failed_node_id: int) -> tuple[int, int]:
        # Lấy snapshot các finger entry đang trỏ tới failed node
        stale_entries = self._stale_finger_entries({failed_node_id})

        # Gom index finger stale theo từng node
        stale_indexes_by_node: dict[int, set[int]] = {}

        # Duyệt stale entry để xây map node -> tập index stale
        for entry in stale_entries:
            stale_indexes_by_node.setdefault(entry["node_id"], set()).add(entry["index"])

        # Duyệt theo snapshot stale ban đầu để report không bị lệch do route repair side-effect
        for node_id, stale_indexes in stale_indexes_by_node.items():
            # Lấy node đang có finger stale
            node = self.nodes[node_id]

            # Tính lại node đích theo successor(start) để tránh route qua finger table đang stale
            node.finger_table = [
                FingerEntry(
                    index=entry.index,
                    start=entry.start,
                    interval_end=entry.interval_end,
                    node_id=self._active_successor_for_key(entry.start)
                    if entry.index in stale_indexes and entry.node_id == failed_node_id
                    else entry.node_id,
                )
                for entry in node.finger_table
            ]

        # Trả về số node có finger stale và tổng số entry stale
        return len(stale_indexes_by_node), len(stale_entries)

    # Thống kê số lượng resource đang lưu trên mỗi node active
    def resource_distribution(self) -> dict[int, int]:
        # Tạo map mặc định để UI không bị khuyết node chưa có resource
        distribution = {node_id: 0 for node_id in self.active_node_ids}

        # Đếm trực tiếp từ kho local để phản ánh dữ liệu thật
        for node_id in distribution:
            distribution[node_id] = len(self.nodes[node_id].local_resources)
        return distribution

    # Liệt kê finger entry đang trỏ tới node failed
    def _stale_finger_entries(self, failed_ids: set[int] | None = None) -> list[dict[str, int]]:
        # Lấy tập failed node từ tham số hoặc từ trạng thái ring
        failed = set(self.failed_nodes if failed_ids is None else failed_ids)

        # Khởi tạo danh sách entry stale
        entries: list[dict[str, int]] = []

        # Trả về rỗng khi không có failed node
        if not failed:
            return entries

        # Duyệt toàn bộ node theo thứ tự node_id để report ổn định
        for node_id, node in sorted(self.nodes.items()):
            # Bỏ qua node inactive vì node chết không còn định tuyến
            if not node.active:
                continue

            # Duyệt từng finger entry của node active
            for entry in node.finger_table:
                # Ghi nhận entry nếu target nằm trong failed set
                if entry.node_id in failed:
                    entries.append(
                        {
                            "node_id": node_id,
                            "index": entry.index,
                            "target_node_id": entry.node_id,
                        }
                    )
        return entries

    # Liệt kê resource có owner hoặc replica nằm trên node lỗi
    def _affected_resources(self, failed_ids: set[int] | None = None) -> list[dict[str, Any]]:
        # Lấy tập failed node từ tham số hoặc từ trạng thái ring
        failed = set(self.failed_nodes if failed_ids is None else failed_ids)

        # Khởi tạo danh sách resource bị ảnh hưởng
        affected: list[dict[str, Any]] = []

        # Trả về rỗng khi không có failed node
        if not failed:
            return affected

        # Duyệt resource theo ID để report ổn định
        for resource in sorted(self.resources.values(), key=lambda item: item.resource_id):
            # Kiểm tra owner của resource có failed không
            owner_failed = resource.owner_id in failed

            # Kiểm tra replica set có chứa failed node không
            replica_failed = any(replica_id in failed for replica_id in resource.replica_node_ids)

            # Bỏ qua resource không bị ảnh hưởng
            if not owner_failed and not replica_failed:
                continue

            # Phân loại vai trò bị ảnh hưởng để UI hiển thị
            if owner_failed and replica_failed:
                role = "owner_and_replica"
            elif owner_failed:
                role = "owner"
            else:
                role = "replica"

            # Chuyển resource sang dict để gắn thêm failure_role
            item = resource.to_dict()

            # Gắn vai trò lỗi vào payload resource
            item["failure_role"] = role

            # Thêm resource vào danh sách ảnh hưởng
            affected.append(item)
        return affected

    # Trả về trạng thái chi tiết của một node để API/UI hiển thị
    def node_details(self, node_id: int) -> dict[str, Any]:
        # Kiểm tra node cần xem chi tiết có tồn tại không
        if node_id not in self.nodes:
            raise ValueError(f"Node {node_id} does not exist")

        # Sử dụng hàm to_dict() từ object Node
        return self.nodes[node_id].to_dict()

    # Gom snapshot tổng quan của ring để gửi cho frontend
    def summary(self, *, sample_size: int | None = None) -> dict[str, Any]:
        # Lấy danh sách node active hiện tại
        active_ids = self.active_node_ids

        # Tính danh sách node retired không active nhưng cũng không pending failed
        retired_ids = sorted(
            node_id
            for node_id, node in self.nodes.items()
            if not node.active and node_id not in self.failed_nodes
        )

        # Rút trích resource từ local storage thật của các node active để hiển thị UI
        live_resources = self._unique_active_local_resources()

        # Đồng bộ metadata resource khi không có node đang pending recovery
        if not self.failed_nodes:
            self.resources = dict(live_resources)

        # Sắp xếp resource theo ID để UI hiển thị ổn định
        all_resources = sorted(self.resources.values(), key=lambda r: r.resource_id)

        # Kiểm tra có cắt mẫu (pagination/sampling) thì chỉ lấy theo sample_size
        if sample_size is None:
            picked = all_resources
        else:
            picked = all_resources[: min(sample_size, len(all_resources))]

        sample_resources = [resource.to_dict() for resource in picked]

        # Tính impact hiện tại của failed nodes nếu có
        impact = self.failure_impact_report()

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
            "retired_node_count": len(retired_ids),
            "resource_count": len(all_resources),
            "resource_table_row_count": len(sample_resources),
            "active_nodes": active_ids,
            "retired_nodes": retired_ids,
            "nodes": [
                {
                    "node_id": node.node_id,
                    "active": bool(node.active),
                    "status": (
                        "failed"
                        if node.node_id in self.failed_nodes
                        else "active"
                        if node.active
                        else "retired"
                    ),
                }
                for node in sorted(self.nodes.values(), key=lambda item: item.node_id)
            ],
            "failed_nodes": sorted(self.failed_nodes),
            "finger_warning_nodes": impact["finger_warning_nodes"],
            "stale_finger_entries": impact["stale_finger_entries"],
            "affected_resources": impact["affected_resources"],
            "sample_resources": sample_resources,
            "resource_distribution": distribution,
            "max_resources_on_node": max(distribution.values()) if distribution else 0,
            "min_resources_on_node": min(distribution.values()) if distribution else 0,
        }

    # Xuất finger table của các node active ra dạng JSON
    def export_finger_tables(self) -> dict[int, list[dict[str, int]]]:
        # Dùng dictionary comprehension để map node_id với cấu trúc dict của Finger table
        return {
            node_id: [entry.to_dict() for entry in self.nodes[node_id].finger_table]
            for node_id in self.active_node_ids
        }

    # Kiểm tra resource có owner và replica đúng theo Chord không
    def verify_resource_mapping(self) -> bool:
        # Duyệt các resource còn sống trong local storage của node active
        for resource in self._unique_active_local_resources().values():
            # Tính owner kỳ vọng theo successor(key)
            expected_owner_id = self._active_successor_for_key(resource.key)

            # Báo sai khi owner metadata không khớp owner kỳ vọng
            if expected_owner_id != resource.owner_id:
                return False

            # Báo sai khi owner không thật sự giữ local copy
            if resource.resource_id not in self.nodes[resource.owner_id].local_resources:
                return False

            # Báo sai khi số replica vượt cấu hình
            if len(resource.replica_node_ids) > self.replication_count:
                return False

            # Báo sai khi replica set có node trùng lặp
            if len(resource.replica_node_ids) != len(set(resource.replica_node_ids)):
                return False

            # Báo sai khi owner xuất hiện trong replica set
            if resource.owner_id in resource.replica_node_ids:
                return False

            # Duyệt từng replica để kiểm tra tồn tại và local copy
            for replica_id in resource.replica_node_ids:
                # Báo sai khi replica không tồn tại hoặc inactive
                if replica_id not in self.nodes or not self.nodes[replica_id].active:
                    return False

                # Báo sai khi replica không giữ local copy
                if resource.resource_id not in self.nodes[replica_id].local_resources:
                    return False
        return True

    # Kiểm tra mỗi finger có trỏ tới successor(start) đúng không
    def verify_finger_tables(self) -> bool:
        # Duyệt từng node active
        for node_id in self.active_node_ids:
            # Duyệt từng finger entry của node
            for entry in self.nodes[node_id].finger_table:
                # Tính owner kỳ vọng cho start của finger
                expected_owner_id = self._active_successor_for_key(entry.start)

                # Báo sai khi finger không trỏ tới successor(start)
                if entry.node_id != expected_owner_id:
                    return False
        return True

    # Chọn ngẫu nhiên một resource đang tồn tại
    def choose_random_resource(self) -> str:
        # Lấy các resource còn sống từ local storage node active
        resources = self._unique_active_local_resources()

        # Báo lỗi khi chưa có resource nào để chọn
        if not resources:
            raise RuntimeError("No resources are available")

        # Sử dụng bộ sinh số đã seed để bốc ngẫu nhiên
        return self._rng.choice(list(resources.keys()))

    # Chọn ngẫu nhiên một node active
    def choose_random_node(self) -> int:
        # Lọc node active từ bảng node hiện tại
        candidates = [node_id for node_id, node in self.nodes.items() if node.active]

        # Báo lỗi khi ring không còn node active
        if not candidates:
            raise RuntimeError("No active nodes are available")

        # Chọn node active ngẫu nhiên bằng bộ sinh số đã seed
        return self._rng.choice(candidates)
