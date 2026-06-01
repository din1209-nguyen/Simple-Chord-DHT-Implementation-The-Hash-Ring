from __future__ import annotations

import math
import random
import time
import logging
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from .chord import ChordRing
from .models import Node, ResourceRecord

# Khởi tạo logger
logger = logging.getLogger(__name__)

# Tạo bộ gom số liệu metric rỗng
def _empty_metric_accumulator() -> dict[str, Any]:

    # Trả về bộ gom số liệu với các danh sách và bộ đếm ban đầu
    return {
        "hops": [],
        "latencies_ms": [],
        "successful_lookups": 0,
        "failed_lookups": 0,
        "errors": [],
        "max_hops": 0,
        "max_lookup_trace": None,
    }

# Ghi nhận một mẫu lookup vào bộ gom metric
def _record_lookup_sample(
    accumulator: dict[str, Any],
    ring: ChordRing,
    resource: ResourceRecord,
    start_node_id: int,
) -> None:

    # Ghi lại thời điểm bắt đầu để tính độ trễ lookup
    started_at = time.perf_counter()

    # Route thử một lookup để ghi nhận số hop và độ trễ
    try:
        route = ring._route_key(
            resource.key,
            start_node_id=start_node_id,
            operation="MetricLookup",
            requested_id=resource.resource_id,
            collect_trace=False,
        )
    except Exception as exc:

        # Tăng bộ đếm lookup lỗi khi định tuyến thất bại
        accumulator["failed_lookups"] += 1

        # Giới hạn số lỗi mẫu để payload metric không phình quá lớn
        if len(accumulator["errors"]) < 5:
            accumulator["errors"].append(str(exc))

        # Dừng ghi nhận mẫu lookup khi định tuyến lỗi
        return

    # Tạo độ trễ mô phỏng để biểu đồ latency có ý nghĩa trực quan
    simulated_latency = random.uniform(5.0, 30.0)

    # Ghi nhận tổng độ trễ thực thi và độ trễ mô phỏng
    accumulator["latencies_ms"].append((time.perf_counter() - started_at) * 1000 + simulated_latency)

    # Lấy số hop từ kết quả định tuyến
    hops = int(route["hops"])

    # Ghi nhận số hop của lookup hiện tại
    accumulator["hops"].append(hops)

    # Tăng bộ đếm lookup thành công
    accumulator["successful_lookups"] += 1

    # Đọc số hop lớn nhất hiện có để so sánh với mẫu mới
    current_trace = {"hops": int(accumulator["max_hops"])}

    # Cập nhật trace đại diện khi mẫu lookup có số hop lớn nhất
    if accumulator["max_lookup_trace"] is None or hops > current_trace["hops"]:
        accumulator["max_hops"] = hops
        trace = ring._route_key(
            resource.key,
            start_node_id=start_node_id,
            operation="MetricLookup",
            requested_id=resource.resource_id,
            collect_trace=True,
        )

        # Lấy owner node để kiểm tra resource thật sự nằm tại owner
        owner_node = ring.nodes[int(trace["owner_id"])]

        # Lưu trace lookup có số hop lớn nhất làm mẫu minh họa
        accumulator["max_lookup_trace"] = {
            "requested_id": resource.resource_id,
            "key": int(trace["key"]),
            "owner_id": int(trace["owner_id"]),
            "start_node_id": int(trace["start_node_id"]),
            "path": list(trace["path"]),
            "hops": int(trace["hops"]),
            "logs": list(trace["logs"]),
            "found": resource.resource_id in owner_node.local_resources,
            "direct_key": False,
            "replica_node_ids": list(resource.replica_node_ids),
        }

# Sao chép danh sách bản ghi tài nguyên
def _copy_resource_records(resources: list[ResourceRecord]) -> list[ResourceRecord]:
    # Trả về bản sao tách biệt để benchmark không sửa ring gốc
    return [
        ResourceRecord(
            resource.resource_id,
            resource.hashed_resource_id,
            int(resource.key),
            int(resource.owner_id),
            list(resource.replica_node_ids),
        )
        for resource in resources
    ]

# Cho node metric tham gia ring và ổn định topology
def _join_metric_node(ring: ChordRing, node_id: int, *, known_node_id: int) -> None:
    # Chuẩn hóa node_id về số nguyên để dùng làm khóa ring
    numeric_id = int(node_id)

    # Tạo node metric mới trong ring benchmark
    ring.nodes[numeric_id] = Node(node_id=numeric_id)

    # Cho node mới join thông qua node đã biết
    ring.join(numeric_id, known_node_id=known_node_id)

    # Chạy giao thức ổn định để cập nhật successor/predecessor
    ring.run_protocol(rounds=ring._default_convergence_rounds)

    # Làm mới finger table sau khi topology thay đổi
    ring.refresh_all_finger_tables()

# Phân phối lại tài nguyên hiện có trên ring metric
def _place_existing_resources_on_metric_ring(
    ring: ChordRing,
    resources: list[ResourceRecord],
) -> None:
    # Xóa resource local trên từng node để đặt lại trạng thái metric
    for node in ring.nodes.values():
        node.local_resources.clear()

    # Xóa map resource trung tâm trước khi phân phối lại
    ring.resources.clear()

    # Chọn node active đầu tiên làm điểm bắt đầu put resource
    start_node_id = ring.active_node_ids[0]

    # Duyệt từng resource gốc để định tuyến lại owner trên ring metric
    for source in resources:
        # Định tuyến key resource tới owner tương ứng trong ring metric
        route = ring._route_key(
            source.key,
            start_node_id=start_node_id,
            operation="MetricPut",
            requested_id=source.resource_id,
            collect_trace=False,
        )

        # Tạo bản ghi resource mới với owner vừa được định tuyến
        resource = ResourceRecord(
            source.resource_id,
            source.hashed_resource_id,
            int(source.key),
            int(route["owner_id"]),
        )

        # Lưu metadata resource vào map trung tâm của ring metric
        ring.resources[resource.resource_id] = resource

        # Đặt resource lên owner và các replica theo cấu hình replication
        ring._place_resource_copies(resource)

# Tổng hợp một điểm dữ liệu metric từ các mẫu lookup
def _build_metric_point(
    *,
    node_count: int,
    lookups_per_trial: int,
    trial_count: int,
    accumulator: dict[str, Any],
) -> dict[str, Any]:

    # Tính tổng số lookup đã cố gắng chạy
    attempted_lookups = lookups_per_trial * trial_count

    # Đọc số lookup thành công từ bộ gom
    successful_lookups = int(accumulator["successful_lookups"])

    # Đọc số lookup thất bại từ bộ gom
    failed_lookups = int(accumulator["failed_lookups"])

    # Lấy danh sách hop của các lookup thành công
    hops = accumulator["hops"]

    # Lấy danh sách độ trễ đã ghi nhận
    latencies_ms = accumulator["latencies_ms"]

    # Tính tổng message overhead theo tổng số hop
    message_overhead = sum(hops)

    # Lấy số hop lớn nhất trong các mẫu lookup
    max_hops = int(accumulator["max_hops"])

    # Lấy trace đại diện có số hop lớn nhất
    max_trace = accumulator["max_lookup_trace"]

    # Chuẩn hóa trace lớn nhất sang chuỗi để frontend hiển thị ổn định
    if max_trace:
        max_trace = {
            **max_trace,
            "key": str(max_trace["key"]),
            "owner_id": str(max_trace["owner_id"]),
            "path": [str(n) for n in max_trace.get("path", [])],
        }

    # Trả về một điểm metric đã tổng hợp từ bộ gom
    return {
        "nodes": node_count,
        "average_hops": round(message_overhead / successful_lookups, 3) if successful_lookups else 0,
        "log2_nodes": round(math.log2(node_count), 3),
        "attempted_lookups": attempted_lookups,
        "total_lookups": attempted_lookups,
        "successful_lookups": successful_lookups,
        "failed_lookups": failed_lookups,
        "average_latency_ms": round(sum(latencies_ms) / len(latencies_ms), 3) if latencies_ms else 0,
        "message_overhead": message_overhead,
        "messages_per_lookup": round(message_overhead / successful_lookups, 3) if successful_lookups else 0,
        "max_lookup_trace": max_trace,
        "sample_errors": accumulator["errors"],
        "max_hops": max_hops,
    }

# Chạy metric trên trạng thái ring hiện tại
def run_current_ring_metrics(
    ring: ChordRing,
    *,
    trial_count: int = 5,
    lookups_per_trial: int = 100,
    seed: int | None = None,
    output_path: str | Path | None = None,
) -> dict[str, Any]:

    # Kiểm tra số lookup mỗi trial phải dương
    if lookups_per_trial < 1:
        raise ValueError("lookups_per_trial must be at least 1")

    # Kiểm tra số trial phải dương
    if trial_count < 1:
        raise ValueError("trial_count must be at least 1")

    # Lấy danh sách node active của ring hiện tại
    active_ids = ring.active_node_ids

    # Lấy danh sách resource hiện có để chọn mẫu lookup
    resources = list(ring.resources.values())

    # Kiểm tra ring có ít nhất một node active để chạy metric
    if not active_ids:
        raise ValueError("metrics require at least one active node")

    # Kiểm tra ring có ít nhất một resource để lấy mẫu lookup
    if not resources:
        raise ValueError("metrics require at least one resource")

    # Khởi tạo bộ sinh ngẫu nhiên có seed ổn định
    rng = random.Random((ring.seed if seed is None else seed) + 2)

    # Tạo bộ gom số liệu cho toàn bộ lượt chạy
    accumulator = _empty_metric_accumulator()

    # Duyệt từng trial để lấy mẫu lookup ngẫu nhiên
    for _ in range(trial_count):
        # Duyệt từng lookup trong trial hiện tại
        for _ in range(lookups_per_trial):
            start_node_id = rng.choice(active_ids)
            resource = rng.choice(resources)
            _record_lookup_sample(accumulator, ring, resource, start_node_id)

    # Đếm số node active được đo metric
    node_count = len(active_ids)

    # Tổng hợp các mẫu lookup thành một điểm metric
    point = _build_metric_point(
        node_count=node_count,
        lookups_per_trial=lookups_per_trial,
        trial_count=trial_count,
        accumulator=accumulator,
    )

    chart_path = None
    # Lưu biểu đồ metric khi caller truyền output_path
    if output_path is not None:
        chart_path = _save_metric_chart([point], Path(output_path))

    # Trả về metric của ring hiện tại và đường dẫn biểu đồ nếu có
    return {
        "points": [point],
        "chart_path": str(chart_path) if chart_path else None,
        "message": "Metrics completed successfully.",
    }

# Tạo danh sách kích thước node cho thử nghiệm tăng trưởng
def build_growth_node_sizes(max_node_count: int, row_limit: int = 50) -> tuple[int, ...]:
    """Trả về tối đa row_limit kích thước mạng được chia đều từ 1 tới max_node_count"""
    max_node_count = int(max_node_count)
    row_limit = int(row_limit)
    # Trả về danh sách rỗng khi tham số giới hạn không hợp lệ
    if max_node_count < 1 or row_limit < 1:
        # Trả về tuple rỗng vì không có kích thước hợp lệ
        return tuple()

    # Trả về toàn bộ dải kích thước khi số node không vượt row_limit
    if max_node_count <= row_limit:
        # Trả về các kích thước liên tiếp từ 1 tới max_node_count
        return tuple(range(1, max_node_count + 1))

    # Tính khoảng cách giữa các mốc kích thước cần lấy mẫu
    step = (max_node_count - 1) / (row_limit - 1)

    # Tạo danh sách kích thước kết quả
    sizes: list[int] = []

    # Theo dõi các kích thước đã dùng để tránh trùng mốc
    used_sizes: set[int] = set()

    # Sinh các mốc kích thước được chia đều theo row_limit
    for index in range(row_limit):
        # Tính kích thước gần nhất theo vị trí chia đều
        value = int(round(1 + step * index))

        # Kẹp kích thước vào miền hợp lệ
        value = max(1, min(max_node_count, value))

        # Tăng kích thước để tránh trùng mốc nếu còn chỗ phía trên
        while value in used_sizes and value < max_node_count:
            value += 1

        # Giảm kích thước để tránh trùng mốc nếu không thể tăng thêm
        while value in used_sizes and value > 1:
            value -= 1

        # Lưu kích thước đã chọn vào danh sách kết quả
        sizes.append(value)

        # Đánh dấu kích thước đã dùng
        used_sizes.add(value)

    # Ép mốc đầu luôn bắt đầu từ 1 node
    sizes[0] = 1

    # Ép mốc cuối luôn là số node lớn nhất
    sizes[-1] = max_node_count
    # Trả về danh sách kích thước đã loại trùng và sắp xếp
    return tuple(sorted(sizes))

# Chạy benchmark lookup theo nhiều kích thước mạng
def run_lookup_metrics(
    *,
    node_sizes: tuple[int, ...] | None = None,
    max_node_count: int = 50,
    trial_count: int = 5,
    lookups_per_size: int = 100,
    resource_count: int = 1000,
    resource_records: list[ResourceRecord] | None = None,
    node_ids: list[int] | None = None,
    replication_count: int = 1,
    m: int = 16,
    seed: int = 61,
    fixed_points: dict[int, dict[str, Any]] | None = None,
    output_path: str | Path | None = None,
) -> dict[str, Any]:

    # Kiểm tra số lookup trên mỗi kích thước phải dương
    if lookups_per_size < 1:
        raise ValueError("lookups_per_size must be at least 1")

    # Kiểm tra số trial phải dương
    if trial_count < 1:
        raise ValueError("trial_count must be at least 1")

    # Tạo danh sách kích thước mặc định khi caller không truyền node_sizes
    if node_sizes is None:
        node_sizes = build_growth_node_sizes(max_node_count)

    # Lưu tham số trial thực tế để truyền vào điểm metric
    effective_trial_count = trial_count

    # Lưu số lookup thực tế trên mỗi trial
    effective_lookups = lookups_per_size

    # Khởi tạo bộ sinh ngẫu nhiên tái lập cho benchmark
    rng = random.Random(seed + 2)

    # Chuẩn hóa map điểm metric cố định nếu caller truyền vào
    fixed_points = fixed_points or {}

    # Sao chép resource đầu vào để benchmark không sửa dữ liệu gốc
    source_resources = _copy_resource_records(resource_records or [])

    # Khởi tạo resource mẫu khi caller không truyền resource_records
    if not source_resources:
        bootstrap = ChordRing(m=m, seed=seed, replication_count=replication_count)
        bootstrap.initialize_network(
            node_count=max_node_count,
            resource_count=resource_count,
            seed=seed,
            replication_count=replication_count,
        )
        source_resources = _copy_resource_records(list(bootstrap.resources.values()))

    # Chuẩn hóa danh sách node_id đầu vào thành số nguyên
    source_node_ids = [int(node_id) for node_id in (node_ids or [])]

    # Sinh danh sách node mẫu khi caller không truyền node_ids
    if not source_node_ids:
        source_node_ids = ChordRing(m=m, seed=seed)._generate_unique_ids("node", max_node_count)

    # Tạo danh sách chứa các điểm metric sau mỗi kích thước mạng
    points: list[dict[str, Any]] = []

    # Đếm tổng số mốc kích thước để log tiến độ
    total_sizes = len(node_sizes)

    # Sắp xếp và loại bỏ kích thước không hợp lệ
    ordered_sizes = tuple(sorted({int(size) for size in node_sizes if int(size) >= 1}))

    # Xác định số node lớn nhất cần dựng trong ring metric
    max_requested_nodes = max(ordered_sizes) if ordered_sizes else max_node_count

    # Bổ sung node_id khi danh sách ban đầu chưa đủ số node cần benchmark
    if len(source_node_ids) < max_requested_nodes:
        # Tạo generator ID phụ để bù node thiếu
        generator = ChordRing(m=m, seed=seed)

        # Theo dõi ID đã dùng để tránh trùng node
        used = set(source_node_ids)

        # Duyệt ID sinh thêm để bỏ qua ID trùng và giữ đủ số lượng
        for candidate in generator._generate_unique_ids("node", max_requested_nodes * 2):
            # Bỏ qua ID đã có trong danh sách node mẫu
            if candidate in used:
                continue
            source_node_ids.append(candidate)
            used.add(candidate)
            # Dừng sinh thêm khi đã đủ số node cần benchmark
            if len(source_node_ids) >= max_requested_nodes:
                break

    # Khởi tạo ring metric để chạy benchmark
    ring = ChordRing(m=m, seed=seed, replication_count=replication_count)

    # Chọn node đầu tiên làm bootstrap node cho ring metric
    first_id = int(source_node_ids[0])

    # Tạo bootstrap node tự trỏ successor/predecessor
    ring.nodes[first_id] = Node(node_id=first_id, predecessor=first_id, successor=first_id)

    # Làm mới finger table cho ring chỉ có bootstrap node
    ring.refresh_all_finger_tables()

    # Theo dõi số node đã dựng trong ring metric
    built_count = 1

    # Duyệt từng kích thước mạng để benchmark tăng trưởng
    for size_index, node_count in enumerate(ordered_sizes, start=1):
        logger.info(
            "Metrics sweep %s/%s: converging incremental ring to N=%s",
            size_index,
            total_sizes,
            node_count,
        )
        # Ghi thời điểm bắt đầu dựng topology cho kích thước hiện tại
        started_at = time.perf_counter()

        # Thêm node dần cho đến khi ring đạt kích thước cần đo
        while built_count < node_count:
            _join_metric_node(ring, source_node_ids[built_count], known_node_id=first_id)
            built_count += 1

        # Phân phối lại resource theo topology hiện tại trước khi lookup
        _place_existing_resources_on_metric_ring(ring, source_resources)
        logger.info(
            "Metrics sweep %s/%s: N=%s ready in %.3fs",
            size_index,
            total_sizes,
            node_count,
            time.perf_counter() - started_at,
        )

        # Tái sử dụng điểm metric đã có khi caller truyền fixed_points
        if node_count in fixed_points:
            points.append(fixed_points[node_count])
            continue

        # Tạo bộ gom metric riêng cho kích thước mạng hiện tại
        accumulator = _empty_metric_accumulator()

        # Lấy resource của ring metric sau khi phân phối lại
        resources = list(ring.resources.values())

        # Lấy node active làm nguồn lookup ngẫu nhiên
        active_ids = ring.active_node_ids

        # Duyệt từng trial ở kích thước mạng hiện tại
        for trial_index in range(effective_trial_count):
            logger.info(
                "Metrics sweep %s/%s: N=%s trial %s/%s running %s lookup(s)",
                size_index,
                total_sizes,
                node_count,
                trial_index + 1,
                effective_trial_count,
                effective_lookups,
            )
            # Duyệt từng lookup ngẫu nhiên để ghi nhận metric
            for _ in range(effective_lookups):
                _record_lookup_sample(accumulator, ring, rng.choice(resources), rng.choice(active_ids))

        # Thêm điểm metric đã tổng hợp vào kết quả sweep
        points.append(
            _build_metric_point(
                node_count=node_count,
                lookups_per_trial=effective_lookups,
                trial_count=effective_trial_count,
                accumulator=accumulator,
            )
        )

    chart_path = None
    # Lưu bộ biểu đồ tổng hợp khi caller truyền output_path
    if output_path is not None:
        chart_path = _save_metric_chart(points, Path(output_path))

    # Trả về toàn bộ điểm benchmark và đường dẫn biểu đồ nếu có
    return {
        "points": points,
        "node_counts": [int(p["nodes"]) for p in points],
        "chart_path": str(chart_path) if chart_path else None,
        "message": "Metrics completed successfully.",
    }

# Lưu biểu đồ metric ra tệp ảnh
def _save_metric_chart(points: list[dict[str, Any]], output_path: Path) -> Path:

    # Tạo thư mục chứa biểu đồ nếu chưa tồn tại
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Lấy danh sách số node làm trục X chung
    node_counts = [int(point["nodes"]) for point in points]

    # Lấy giá trị hop trung bình cho biểu đồ lookup
    average_hops = [float(point["average_hops"]) for point in points]

    # Lấy giá trị log2(N) làm đường tham chiếu
    log_values = [float(point["log2_nodes"]) for point in points]

    # Lấy độ trễ trung bình cho biểu đồ latency
    average_latencies = [float(point["average_latency_ms"]) for point in points]

    # Lấy tổng message overhead cho biểu đồ cột
    message_overheads = [int(point["message_overhead"]) for point in points]

    # Lấy số message trung bình trên mỗi lookup
    messages_per_lookup = [float(point["messages_per_lookup"]) for point in points]

    # Khởi tạo danh sách tick trục X theo số node
    x_ticks = node_counts

    # Giảm số tick trục X khi có quá nhiều kích thước node
    if len(node_counts) > 15:
        step = max(1, len(node_counts) // 10)
        x_ticks = node_counts[::step]
        # Giữ tick cuối cùng để biểu đồ luôn hiển thị max node
        if x_ticks[-1] != node_counts[-1]:
            x_ticks.append(node_counts[-1])

    # Tạo figure tổng hợp gồm ba biểu đồ metric chính
    fig, axes = plt.subplots(1, 3, figsize=(16, 4.8), dpi=140)

    # Vẽ đường hop trung bình theo số node
    axes[0].plot(
        node_counts,
        average_hops,
        marker="o",
        linewidth=2,
        label="Average lookup hops",
    )

    # Vẽ đường log2(N) để so sánh với lý thuyết Chord
    axes[0].plot(
        node_counts,
        log_values,
        marker="s",
        linestyle="--",
        label="log2(N) reference",
    )

    # Đặt tiêu đề cho biểu đồ hop tổng hợp
    axes[0].set_title("Chord Lookup Metrics")

    # Đặt nhãn trục X cho biểu đồ hop
    axes[0].set_xlabel("Number of Nodes (N)")

    # Đặt nhãn trục Y cho biểu đồ hop
    axes[0].set_ylabel("Hops")

    # Áp dụng tick trục X đã rút gọn nếu cần
    axes[0].set_xticks(x_ticks)

    # Bật lưới nhẹ để đọc giá trị hop
    axes[0].grid(True, alpha=0.3)

    # Hiển thị chú thích cho biểu đồ hop
    axes[0].legend(fontsize=8)

    # Nới giới hạn trục X khi chỉ có một điểm dữ liệu
    if len(node_counts) == 1:
        axes[0].set_xlim(node_counts[0] - 1, node_counts[0] + 1)

    # Vẽ đường độ trễ lookup trung bình
    axes[1].plot(
        node_counts,
        average_latencies,
        marker="^",
        linewidth=2,
        color="#2563eb",
        label="Avg simulated lookup time (ms)",
    )

    # Đặt tiêu đề cho biểu đồ latency
    axes[1].set_title("Lookup Latency")

    # Đặt nhãn trục X cho biểu đồ latency
    axes[1].set_xlabel("Number of Nodes (N)")

    # Đặt nhãn trục Y cho biểu đồ latency
    axes[1].set_ylabel("Latency (ms)")

    # Áp dụng tick trục X cho biểu đồ latency
    axes[1].set_xticks(x_ticks)

    # Bật lưới nhẹ cho biểu đồ latency
    axes[1].grid(True, alpha=0.3)

    # Hiển thị chú thích cho biểu đồ latency
    axes[1].legend(fontsize=8)

    # Nới giới hạn trục latency khi chỉ có một điểm dữ liệu
    if len(node_counts) == 1:
        axes[1].set_xlim(node_counts[0] - 1, node_counts[0] + 1)

    # Chọn trục chính cho tổng message overhead
    overhead_axis = axes[2]

    # Tạo trục phụ để hiển thị message trên mỗi lookup
    per_lookup_axis = overhead_axis.twinx()

    # Vẽ cột tổng message overhead theo số node
    overhead_axis.bar(
        node_counts,
        message_overheads,
        width=3 if len(node_counts) > 1 else 0.5,
        alpha=0.45,
        color="#64748b",
        label="Message overhead",
    )

    # Vẽ đường message trung bình trên mỗi lookup
    per_lookup_axis.plot(
        node_counts,
        messages_per_lookup,
        marker="D",
        linewidth=2,
        color="#b45309",
        label="Messages per lookup",
    )

    # Đặt tiêu đề cho biểu đồ overhead
    overhead_axis.set_title("Message Overhead")

    # Đặt nhãn trục X cho biểu đồ overhead
    overhead_axis.set_xlabel("Number of Nodes (N)")

    # Đặt nhãn trục Y chính cho tổng message
    overhead_axis.set_ylabel("Total Messages")

    # Đặt nhãn trục Y phụ cho message trên mỗi lookup
    per_lookup_axis.set_ylabel("Messages / Lookup")

    # Áp dụng tick trục X cho biểu đồ overhead
    overhead_axis.set_xticks(x_ticks)

    # Bật lưới theo trục Y chính của biểu đồ overhead
    overhead_axis.grid(True, axis="y", alpha=0.3)

    # Nới giới hạn trục overhead khi chỉ có một điểm dữ liệu
    if len(node_counts) == 1:
        overhead_axis.set_xlim(node_counts[0] - 1, node_counts[0] + 1)

    # Lấy chú thích của trục overhead chính
    left_handles, left_labels = overhead_axis.get_legend_handles_labels()

    # Lấy chú thích của trục message trên mỗi lookup
    right_handles, right_labels = per_lookup_axis.get_legend_handles_labels()

    # Gộp chú thích của hai trục vào cùng một legend
    overhead_axis.legend(left_handles + right_handles, left_labels + right_labels, fontsize=8)

    # Căn layout để các nhãn không chồng lên nhau
    fig.tight_layout()

    # Lưu biểu đồ tổng hợp ra tệp chính
    fig.savefig(output_path)

    # Đóng figure tổng hợp để giải phóng bộ nhớ
    plt.close(fig)

    # Tạo đường dẫn biểu đồ hop riêng
    hops_path = output_path.with_name(f"{output_path.stem}_hops{output_path.suffix}")

    # Tạo đường dẫn biểu đồ latency riêng
    latency_path = output_path.with_name(f"{output_path.stem}_latency{output_path.suffix}")

    # Tạo đường dẫn biểu đồ overhead riêng
    overhead_path = output_path.with_name(f"{output_path.stem}_overhead{output_path.suffix}")

    # Tạo figure riêng cho biểu đồ hop
    hops_fig, hops_axis = plt.subplots(figsize=(5.4, 3.6), dpi=140)

    # Vẽ hop trung bình trên biểu đồ riêng
    hops_axis.plot(node_counts, average_hops, marker="o", linewidth=2, label="Average lookup hops")

    # Vẽ log2(N) trên biểu đồ hop riêng
    hops_axis.plot(node_counts, log_values, marker="s", linestyle="--", label="log2(N) reference")

    hops_axis.set_title("Chord Lookup Hops")

    hops_axis.set_xlabel("Number of Nodes (N)")

    hops_axis.set_ylabel("Hops")

    hops_axis.set_xticks(x_ticks)

    hops_axis.grid(True, alpha=0.3)

    hops_axis.legend(fontsize=8)

    # Nới giới hạn biểu đồ hop riêng khi chỉ có một điểm dữ liệu
    if len(node_counts) == 1:
        hops_axis.set_xlim(node_counts[0] - 1, node_counts[0] + 1)

    # Căn layout cho biểu đồ hop riêng
    hops_fig.tight_layout()

    # Lưu biểu đồ hop riêng
    hops_fig.savefig(hops_path)

    # Đóng biểu đồ hop riêng
    plt.close(hops_fig)

    # Tạo figure riêng cho biểu đồ latency
    latency_fig, latency_axis = plt.subplots(figsize=(5.4, 3.6), dpi=140)

    # Vẽ độ trễ trung bình trên biểu đồ riêng
    latency_axis.plot(
        node_counts,
        average_latencies,
        marker="^",
        linewidth=2,
        color="#2563eb",
        label="Avg simulated lookup time (ms)",
    )

    latency_axis.set_title("Lookup Latency")

    latency_axis.set_xlabel("Number of Nodes (N)")

    latency_axis.set_ylabel("Latency (ms)")

    latency_axis.set_xticks(x_ticks)

    latency_axis.grid(True, alpha=0.3)

    latency_axis.legend(fontsize=8)

    # Nới giới hạn biểu đồ latency riêng khi chỉ có một điểm dữ liệu
    if len(node_counts) == 1:
        latency_axis.set_xlim(node_counts[0] - 1, node_counts[0] + 1)

    # Căn layout cho biểu đồ latency riêng
    latency_fig.tight_layout()

    # Lưu biểu đồ latency riêng
    latency_fig.savefig(latency_path)

    # Đóng biểu đồ latency riêng
    plt.close(latency_fig)

    # Tạo figure riêng cho biểu đồ overhead
    overhead_fig, overhead_axis = plt.subplots(figsize=(5.4, 3.6), dpi=140)

    # Tạo trục phụ cho message trên mỗi lookup trong biểu đồ riêng
    per_lookup_axis = overhead_axis.twinx()

    # Vẽ cột tổng message overhead trên biểu đồ riêng
    overhead_axis.bar(
        node_counts,
        message_overheads,
        width=3 if len(node_counts) > 1 else 0.5,
        alpha=0.45,
        color="#64748b",
        label="Message overhead",
    )

    # Vẽ đường message trung bình trên mỗi lookup trong biểu đồ riêng
    per_lookup_axis.plot(
        node_counts,
        messages_per_lookup,
        marker="D",
        linewidth=2,
        color="#b45309",
        label="Messages per lookup",
    )

    overhead_axis.set_title("Message Overhead")

    overhead_axis.set_xlabel("Number of Nodes (N)")

    overhead_axis.set_ylabel("Total Messages")

    per_lookup_axis.set_ylabel("Messages / Lookup")

    overhead_axis.set_xticks(x_ticks)

    overhead_axis.grid(True, axis="y", alpha=0.3)

    # Nới giới hạn biểu đồ overhead riêng khi chỉ có một điểm dữ liệu
    if len(node_counts) == 1:
        overhead_axis.set_xlim(node_counts[0] - 1, node_counts[0] + 1)

    # Lấy chú thích trục chính của biểu đồ overhead riêng
    left_handles, left_labels = overhead_axis.get_legend_handles_labels()

    # Lấy chú thích trục phụ của biểu đồ overhead riêng
    right_handles, right_labels = per_lookup_axis.get_legend_handles_labels()

    # Gộp chú thích hai trục trên biểu đồ overhead riêng
    overhead_axis.legend(left_handles + right_handles, left_labels + right_labels, fontsize=8)

    # Căn layout cho biểu đồ overhead riêng
    overhead_fig.tight_layout()

    # Lưu biểu đồ overhead riêng
    overhead_fig.savefig(overhead_path)

    # Đóng biểu đồ overhead riêng
    plt.close(overhead_fig)

    # Trả về đường dẫn biểu đồ tổng hợp chính
    return output_path
