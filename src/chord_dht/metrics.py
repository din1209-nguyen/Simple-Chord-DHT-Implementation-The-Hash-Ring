from __future__ import annotations

import math
import random
import time
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from .chord import ChordRing


# Khởi tạo bộ tích lũy số liệu trống
def _empty_metric_accumulator() -> dict[str, Any]:
    # Tạo cấu trúc chứa danh sách hop
    # Tạo cấu trúc chứa danh sách độ trễ
    # Tạo cấu trúc chứa số lần lookup thành công
    # Tạo cấu trúc chứa số lần lookup thất bại
    # Tạo cấu trúc chứa danh sách lỗi mẫu
    # Tạo cấu trúc chứa trace có hop lớn nhất
    return {
        "hops": [],
        "latencies_ms": [],
        "successful_lookups": 0,
        "failed_lookups": 0,
        "errors": [],
        "max_lookup_trace": None,
    }


# Ghi nhận một lần lookup vào bộ tích lũy
def _record_lookup_sample(
    accumulator: dict[str, Any],
    ring: ChordRing,
    resource_id: str,
    start_node_id: int,
) -> None:
    # Bắt đầu đo thời gian xử lý lookup
    started_at = time.perf_counter()

    # Thực hiện lookup từ node xuất phát
    try:
        result = ring.lookup(resource_id, start_node_id=start_node_id)
    except Exception as exc:
        # Tăng số lần lookup thất bại
        accumulator["failed_lookups"] += 1

        # Lưu lại tối đa một số lỗi mẫu
        if len(accumulator["errors"]) < 5:
            accumulator["errors"].append(str(exc))

        # Dừng ghi nhận khi lookup lỗi
        return

    # Tạo độ trễ mạng giả lập
    simulated_latency = random.uniform(5.0, 30.0)

    # Tính độ trễ tổng và ghi vào danh sách
    accumulator["latencies_ms"].append((time.perf_counter() - started_at) * 1000 + simulated_latency)

    # Ghi số hop của lookup
    accumulator["hops"].append(result.hops)

    # Tăng số lần lookup thành công
    accumulator["successful_lookups"] += 1

    # Đọc trace có hop lớn nhất hiện tại
    current_trace = accumulator["max_lookup_trace"]

    # Cập nhật trace khi phát hiện hop lớn hơn
    if current_trace is None or result.hops > current_trace["hops"]:
        accumulator["max_lookup_trace"] = result.to_dict()


# Tạo một điểm metric từ bộ tích lũy
def _build_metric_point(
    *,
    node_count: int,
    lookups_per_trial: int,
    trial_count: int,
    accumulator: dict[str, Any],
) -> dict[str, Any]:
    # Tính tổng số lookup đã thử
    attempted_lookups = lookups_per_trial * trial_count

    # Lấy số lookup thành công
    successful_lookups = int(accumulator["successful_lookups"])

    # Lấy số lookup thất bại
    failed_lookups = int(accumulator["failed_lookups"])

    # Lấy danh sách hop
    hops = accumulator["hops"]

    # Lấy danh sách độ trễ
    latencies_ms = accumulator["latencies_ms"]

    # Tính tổng overhead message theo số hop
    message_overhead = sum(hops)

    # Tính hop lớn nhất
    max_hops = max(hops) if hops else 0

    # Đọc trace có hop lớn nhất
    max_trace = accumulator["max_lookup_trace"]

    # Chuẩn hóa trace để phục vụ hiển thị
    if max_trace:
        max_trace = {
            **max_trace,
            "key": str(max_trace["key"]),
            "owner_id": str(max_trace["owner_id"]),
            "path": [str(n) for n in max_trace.get("path", [])],
        }

    # Trả về payload metric cho UI
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


# Chạy benchmark trên ring hiện tại
def run_current_ring_metrics(
    ring: ChordRing,
    *,
    trial_count: int = 5,
    lookups_per_trial: int = 100,
    seed: int | None = None,
    output_path: str | Path | None = None,
) -> dict[str, Any]:
    # Kiểm tra số lookup mỗi trial
    if lookups_per_trial < 1:
        raise ValueError("lookups_per_trial must be at least 1")

    # Kiểm tra số trial
    if trial_count < 1:
        raise ValueError("trial_count must be at least 1")

    # Lấy danh sách node đang hoạt động
    active_ids = ring.active_node_ids

    # Lấy danh sách resource hiện có
    resource_ids = list(ring.resources.keys())

    # Chặn benchmark khi không có node
    if not active_ids:
        raise ValueError("metrics require at least one active node")

    # Chặn benchmark khi không có resource
    if not resource_ids:
        raise ValueError("metrics require at least one resource")

    # Tạo bộ sinh ngẫu nhiên độc lập
    rng = random.Random((ring.seed if seed is None else seed) + 2)

    # Khởi tạo bộ tích lũy
    accumulator = _empty_metric_accumulator()

    # Lặp qua từng trial
    for _ in range(trial_count):
        # Lặp qua từng lookup trong trial
        for _ in range(lookups_per_trial):
            # Chọn resource ngẫu nhiên
            resource_id = rng.choice(resource_ids)

            # Chọn node xuất phát ngẫu nhiên
            start_node_id = rng.choice(active_ids)

            # Ghi nhận một mẫu lookup
            _record_lookup_sample(accumulator, ring, resource_id, start_node_id)

    # Tính số node hiện tại
    node_count = len(active_ids)

    # Tạo một điểm metric
    point = _build_metric_point(
        node_count=node_count,
        lookups_per_trial=lookups_per_trial,
        trial_count=trial_count,
        accumulator=accumulator,
    )

    # Khởi tạo đường dẫn ảnh biểu đồ
    chart_path = None

    # Lưu biểu đồ khi có yêu cầu
    if output_path is not None:
        chart_path = _save_metric_chart([point], Path(output_path))

    # Trả về kết quả benchmark
    return {
        "points": [point],
        "chart_path": str(chart_path) if chart_path else None,
        "message": "Metrics completed successfully.",
    }


# Chạy benchmark theo nhiều kích thước mạng
def run_lookup_metrics(
    *,
    node_sizes: tuple[int, ...] | None = None,
    max_node_count: int = 50,
    trial_count: int = 5,
    lookups_per_size: int = 100,
    resource_count: int = 1000,
    m: int = 16,
    seed: int = 61,
    fixed_points: dict[int, dict[str, Any]] | None = None,
    output_path: str | Path | None = None,
) -> dict[str, Any]:
    # Kiểm tra số lookup mỗi kích thước
    if lookups_per_size < 1:
        raise ValueError("lookups_per_size must be at least 1")

    # Kiểm tra số trial
    if trial_count < 1:
        raise ValueError("trial_count must be at least 1")

    # Tạo danh sách kích thước node mặc định
    if node_sizes is None:
        node_sizes = build_growth_node_sizes(max_node_count)

    # Tạo bộ sinh ngẫu nhiên chọn resource và node
    rng = random.Random(seed + 2)

    # Khởi tạo bảng điểm cố định
    fixed_points = fixed_points or {}

    # Khởi tạo danh sách điểm metric
    points: list[dict[str, Any]] = []

    # Duyệt từng kích thước mạng
    for node_count in node_sizes:
        # Dùng điểm cố định nếu đã có sẵn
        if node_count in fixed_points:
            points.append(fixed_points[node_count])
            continue

        # Khởi tạo bộ tích lũy
        accumulator = _empty_metric_accumulator()

        # Chạy nhiều trial để giảm nhiễu topology
        for trial_index in range(trial_count):
            # Tạo ring mới cho trial
            ring = ChordRing(m=m, seed=seed + node_count + trial_index * 997)

            # Khởi tạo network với số node và resource
            ring.initialize_network(node_count=node_count, resource_count=resource_count)

            # Lấy danh sách resource
            resource_ids = list(ring.resources.keys())

            # Lấy danh sách node đang hoạt động
            node_ids = ring.active_node_ids

            # Lặp qua số lookup cần đo
            for _ in range(lookups_per_size):
                # Chọn resource ngẫu nhiên
                resource_id = rng.choice(resource_ids)

                # Chọn node xuất phát ngẫu nhiên
                start_node_id = rng.choice(node_ids)

                # Ghi nhận mẫu lookup
                _record_lookup_sample(accumulator, ring, resource_id, start_node_id)

        # Tạo điểm metric cho kích thước mạng
        points.append(
            _build_metric_point(
                node_count=node_count,
                lookups_per_trial=lookups_per_size,
                trial_count=trial_count,
                accumulator=accumulator,
            )
        )

    # Khởi tạo đường dẫn ảnh biểu đồ
    chart_path = None

    # Lưu biểu đồ khi có yêu cầu
    if output_path is not None:
        chart_path = _save_metric_chart(points, Path(output_path))

    # Trả về kết quả benchmark
    return {
        "points": points,
        "node_counts": [int(p["nodes"]) for p in points],
        "chart_path": str(chart_path) if chart_path else None,
        "message": "Metrics completed successfully.",
    }


# Tạo dãy kích thước node tăng dần
def build_growth_node_sizes(max_node_count: int, row_limit: int = 50) -> tuple[int, ...]:
    # Kiểm tra giới hạn node
    if max_node_count < 1:
        raise ValueError("max_node_count must be at least 1")

    # Kiểm tra giới hạn số dòng
    if row_limit < 1:
        raise ValueError("row_limit must be at least 1")

    # Trả về đầy đủ khi số node nhỏ
    if max_node_count <= row_limit:
        return tuple(range(1, max_node_count + 1))

    # Tạo danh sách kích thước theo bước đều
    sizes = [
        int(round(1 + (max_node_count - 1) * (i / (row_limit - 1))))
        for i in range(row_limit)
    ]

    # Khử trùng và sắp xếp
    unique_sorted = sorted(set(sizes))

    # Bổ sung phần tử khi bị thiếu do làm tròn
    if len(unique_sorted) < row_limit:
        used = set(unique_sorted)
        for candidate in range(1, max_node_count + 1):
            if candidate in used:
                continue
            unique_sorted.append(candidate)
            used.add(candidate)
            if len(unique_sorted) >= row_limit:
                break
        unique_sorted = sorted(unique_sorted)

    # Cắt danh sách về đúng số dòng
    return tuple(unique_sorted[:row_limit])


# Lưu biểu đồ metric ra file ảnh
def _save_metric_chart(points: list[dict[str, Any]], output_path: Path) -> Path:
    # Tạo thư mục đích
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Tách danh sách số node
    node_counts = [int(point["nodes"]) for point in points]

    # Tách danh sách hop trung bình
    average_hops = [float(point["average_hops"]) for point in points]

    # Tách danh sách log2
    log_values = [float(point["log2_nodes"]) for point in points]

    # Tách danh sách độ trễ trung bình
    average_latencies = [float(point["average_latency_ms"]) for point in points]

    # Tách danh sách overhead message
    message_overheads = [int(point["message_overhead"]) for point in points]

    # Tách danh sách message mỗi lookup
    messages_per_lookup = [float(point["messages_per_lookup"]) for point in points]

    # Khởi tạo ticks trục x
    x_ticks = node_counts

    # Giảm mật độ tick khi số điểm quá nhiều
    if len(node_counts) > 15:
        step = max(1, len(node_counts) // 10)
        x_ticks = node_counts[::step]
        if x_ticks[-1] != node_counts[-1]:
            x_ticks.append(node_counts[-1])

    # Tạo figure nhiều subplot
    fig, axes = plt.subplots(1, 3, figsize=(16, 4.8), dpi=140)

    # Vẽ đường hop trung bình
    axes[0].plot(
        node_counts,
        average_hops,
        marker="o",
        linewidth=2,
        label="Average lookup hops",
    )

    # Vẽ đường tham chiếu log2
    axes[0].plot(
        node_counts,
        log_values,
        marker="s",
        linestyle="--",
        label="log2(N) reference",
    )

    # Cập nhật tiêu đề subplot đầu
    axes[0].set_title("Chord Lookup Metrics")

    # Cập nhật nhãn trục x subplot đầu
    axes[0].set_xlabel("Number of Nodes (N)")

    # Cập nhật nhãn trục y subplot đầu
    axes[0].set_ylabel("Hops")

    # Cập nhật danh sách tick
    axes[0].set_xticks(x_ticks)

    # Bật lưới biểu đồ
    axes[0].grid(True, alpha=0.3)

    # Hiển thị chú giải
    axes[0].legend(fontsize=8)

    # Đặt giới hạn trục x khi chỉ có một điểm
    if len(node_counts) == 1:
        axes[0].set_xlim(node_counts[0] - 1, node_counts[0] + 1)

    # Vẽ đường độ trễ
    axes[1].plot(
        node_counts,
        average_latencies,
        marker="^",
        linewidth=2,
        color="#2563eb",
        label="Avg simulated lookup time (ms)",
    )

    # Cập nhật tiêu đề subplot giữa
    axes[1].set_title("Lookup Latency")

    # Cập nhật nhãn trục x subplot giữa
    axes[1].set_xlabel("Number of Nodes (N)")

    # Cập nhật nhãn trục y subplot giữa
    axes[1].set_ylabel("Latency (ms)")

    # Cập nhật danh sách tick
    axes[1].set_xticks(x_ticks)

    # Bật lưới biểu đồ
    axes[1].grid(True, alpha=0.3)

    # Hiển thị chú giải
    axes[1].legend(fontsize=8)

    # Đặt giới hạn trục x khi chỉ có một điểm
    if len(node_counts) == 1:
        axes[1].set_xlim(node_counts[0] - 1, node_counts[0] + 1)

    # Gán trục overhead
    overhead_axis = axes[2]

    # Tạo trục phụ cho messages per lookup
    per_lookup_axis = overhead_axis.twinx()

    # Vẽ cột overhead message
    overhead_axis.bar(
        node_counts,
        message_overheads,
        width=3 if len(node_counts) > 1 else 0.5,
        alpha=0.45,
        color="#64748b",
        label="Message overhead",
    )

    # Vẽ đường messages per lookup
    per_lookup_axis.plot(
        node_counts,
        messages_per_lookup,
        marker="D",
        linewidth=2,
        color="#b45309",
        label="Messages per lookup",
    )

    # Cập nhật tiêu đề subplot cuối
    overhead_axis.set_title("Message Overhead")

    # Cập nhật nhãn trục x subplot cuối
    overhead_axis.set_xlabel("Number of Nodes (N)")

    # Cập nhật nhãn trục y subplot cuối
    overhead_axis.set_ylabel("Total Messages")

    # Cập nhật nhãn trục y phụ subplot cuối
    per_lookup_axis.set_ylabel("Messages / Lookup")

    # Cập nhật tick trục x
    overhead_axis.set_xticks(x_ticks)

    # Bật lưới theo trục y
    overhead_axis.grid(True, axis="y", alpha=0.3)

    # Đặt giới hạn trục x khi chỉ có một điểm
    if len(node_counts) == 1:
        overhead_axis.set_xlim(node_counts[0] - 1, node_counts[0] + 1)

    # Lấy legend của trục trái
    left_handles, left_labels = overhead_axis.get_legend_handles_labels()

    # Lấy legend của trục phải
    right_handles, right_labels = per_lookup_axis.get_legend_handles_labels()

    # Gộp legend cho subplot cuối
    overhead_axis.legend(left_handles + right_handles, left_labels + right_labels, fontsize=8)

    # Tối ưu layout
    fig.tight_layout()

    # Lưu ảnh tổng hợp
    fig.savefig(output_path)

    # Đóng figure để giải phóng bộ nhớ
    plt.close(fig)

    # Tạo đường dẫn ảnh hops
    hops_path = output_path.with_name(f"{output_path.stem}_hops{output_path.suffix}")

    # Tạo đường dẫn ảnh latency
    latency_path = output_path.with_name(f"{output_path.stem}_latency{output_path.suffix}")

    # Tạo đường dẫn ảnh overhead
    overhead_path = output_path.with_name(f"{output_path.stem}_overhead{output_path.suffix}")

    # Tạo figure hops
    hops_fig, hops_axis = plt.subplots(figsize=(5.4, 3.6), dpi=140)

    # Vẽ hops trung bình
    hops_axis.plot(node_counts, average_hops, marker="o", linewidth=2, label="Average lookup hops")

    # Vẽ log2 tham chiếu
    hops_axis.plot(node_counts, log_values, marker="s", linestyle="--", label="log2(N) reference")

    # Cập nhật tiêu đề biểu đồ hops
    hops_axis.set_title("Chord Lookup Hops")

    # Cập nhật nhãn trục x biểu đồ hops
    hops_axis.set_xlabel("Number of Nodes (N)")

    # Cập nhật nhãn trục y biểu đồ hops
    hops_axis.set_ylabel("Hops")

    # Cập nhật tick trục x
    hops_axis.set_xticks(x_ticks)

    # Bật lưới biểu đồ
    hops_axis.grid(True, alpha=0.3)

    # Hiển thị chú giải
    hops_axis.legend(fontsize=8)

    # Đặt giới hạn trục x khi chỉ có một điểm
    if len(node_counts) == 1:
        hops_axis.set_xlim(node_counts[0] - 1, node_counts[0] + 1)

    # Tối ưu layout
    hops_fig.tight_layout()

    # Lưu ảnh hops
    hops_fig.savefig(hops_path)

    # Đóng figure hops
    plt.close(hops_fig)

    # Tạo figure latency
    latency_fig, latency_axis = plt.subplots(figsize=(5.4, 3.6), dpi=140)

    # Vẽ đường latency trung bình
    latency_axis.plot(
        node_counts,
        average_latencies,
        marker="^",
        linewidth=2,
        color="#2563eb",
        label="Avg simulated lookup time (ms)",
    )

    # Cập nhật tiêu đề biểu đồ latency
    latency_axis.set_title("Lookup Latency")

    # Cập nhật nhãn trục x biểu đồ latency
    latency_axis.set_xlabel("Number of Nodes (N)")

    # Cập nhật nhãn trục y biểu đồ latency
    latency_axis.set_ylabel("Latency (ms)")

    # Cập nhật tick trục x
    latency_axis.set_xticks(x_ticks)

    # Bật lưới biểu đồ
    latency_axis.grid(True, alpha=0.3)

    # Hiển thị chú giải
    latency_axis.legend(fontsize=8)

    # Đặt giới hạn trục x khi chỉ có một điểm
    if len(node_counts) == 1:
        latency_axis.set_xlim(node_counts[0] - 1, node_counts[0] + 1)

    # Tối ưu layout
    latency_fig.tight_layout()

    # Lưu ảnh latency
    latency_fig.savefig(latency_path)

    # Đóng figure latency
    plt.close(latency_fig)

    # Tạo figure overhead
    overhead_fig, overhead_axis = plt.subplots(figsize=(5.4, 3.6), dpi=140)

    # Tạo trục phụ overhead
    per_lookup_axis = overhead_axis.twinx()

    # Vẽ cột overhead
    overhead_axis.bar(
        node_counts,
        message_overheads,
        width=3 if len(node_counts) > 1 else 0.5,
        alpha=0.45,
        color="#64748b",
        label="Message overhead",
    )

    # Vẽ đường messages per lookup
    per_lookup_axis.plot(
        node_counts,
        messages_per_lookup,
        marker="D",
        linewidth=2,
        color="#b45309",
        label="Messages per lookup",
    )

    # Cập nhật tiêu đề biểu đồ overhead
    overhead_axis.set_title("Message Overhead")

    # Cập nhật nhãn trục x biểu đồ overhead
    overhead_axis.set_xlabel("Number of Nodes (N)")

    # Cập nhật nhãn trục y biểu đồ overhead
    overhead_axis.set_ylabel("Total Messages")

    # Cập nhật nhãn trục y phụ
    per_lookup_axis.set_ylabel("Messages / Lookup")

    # Cập nhật tick trục x
    overhead_axis.set_xticks(x_ticks)

    # Bật lưới biểu đồ overhead
    overhead_axis.grid(True, axis="y", alpha=0.3)

    # Đặt giới hạn trục x khi chỉ có một điểm
    if len(node_counts) == 1:
        overhead_axis.set_xlim(node_counts[0] - 1, node_counts[0] + 1)

    # Lấy legend trái
    left_handles, left_labels = overhead_axis.get_legend_handles_labels()

    # Lấy legend phải
    right_handles, right_labels = per_lookup_axis.get_legend_handles_labels()

    # Gộp legend
    overhead_axis.legend(left_handles + right_handles, left_labels + right_labels, fontsize=8)

    # Tối ưu layout
    overhead_fig.tight_layout()

    # Lưu ảnh overhead
    overhead_fig.savefig(overhead_path)

    # Đóng figure overhead
    plt.close(overhead_fig)

    # Trả về đường dẫn ảnh tổng hợp
    return output_path
