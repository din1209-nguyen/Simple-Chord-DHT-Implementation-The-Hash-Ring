# Đo hiệu năng lookup của Chord theo một hoặc nhiều kích thước mạng
# Vẽ biểu đồ average hops để so sánh với đường tham chiếu log2(N)

from __future__ import annotations

import math
import random
import time
from pathlib import Path
from typing import Any

import matplotlib

# Chọn backend không cần GUI để chạy được trong terminal, test tự động và Flask server
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from .chord import ChordRing


# Tạo bộ gom số liệu rỗng cho một lần benchmark lookup
def _empty_metric_accumulator() -> dict[str, Any]:
    # Mỗi field lưu một nhóm metric để các hàm sau chỉ cần append/cộng dồn
    return {
        "hops": [],
        "latencies_ms": [],
        "successful_lookups": 0,
        "failed_lookups": 0,
        "errors": [],
        "max_lookup_trace": None,
    }


# Ghi nhận kết quả của một lookup vào accumulator
def _record_lookup_sample(
    accumulator: dict[str, Any],
    ring: ChordRing,
    resource_id: str,
    start_node_id: int,
) -> None:
    # Đo thời gian xử lý lookup trong mô phỏng local bằng perf_counter
    started_at = time.perf_counter()
    try:
        result = ring.lookup(resource_id, start_node_id=start_node_id)
    except Exception as exc:
        # Nếu lookup lỗi, tăng failed count và chỉ giữ vài lỗi mẫu để report gọn
        accumulator["failed_lookups"] += 1
        if len(accumulator["errors"]) < 5:
            accumulator["errors"].append(str(exc))
        return

    # Lưu latency, số hop và tăng số lookup thành công
    accumulator["latencies_ms"].append((time.perf_counter() - started_at) * 1000)
    accumulator["hops"].append(result.hops)
    accumulator["successful_lookups"] += 1

    # Giữ lại trace có số hop lớn nhất để UI/báo cáo minh họa worst case trong mẫu đo
    current_trace = accumulator["max_lookup_trace"]
    if current_trace is None or result.hops > current_trace["hops"]:
        accumulator["max_lookup_trace"] = result.to_dict()


# Chuyển accumulator thô thành một dòng metric hoàn chỉnh cho bảng kết quả
def _build_metric_point(
    *,
    node_count: int,
    lookups_per_trial: int,
    trial_count: int,
    accumulator: dict[str, Any],
) -> dict[str, Any]:
    # Tính các số đếm nền tảng trước để tránh lặp công thức trong payload trả về
    attempted_lookups = lookups_per_trial * trial_count
    successful_lookups = int(accumulator["successful_lookups"])
    failed_lookups = int(accumulator["failed_lookups"])
    hops = accumulator["hops"]
    latencies_ms = accumulator["latencies_ms"]
    message_overhead = sum(hops)
    max_hops = max(hops) if hops else 0

    # Trả về cả metric chính và thông tin phụ phục vụ chart, bảng và debug lỗi lookup
    return {
        "nodes": node_count,
        "average_hops": round(message_overhead / successful_lookups, 3) if successful_lookups else 0,
        "max_hops": max_hops,
        "log2_nodes": round(math.log2(node_count), 3),
        "lookups": lookups_per_trial,
        "trials": trial_count,
        "attempted_lookups": attempted_lookups,
        "total_lookups": attempted_lookups,
        "successful_lookups": successful_lookups,
        "failed_lookups": failed_lookups,
        "success_rate": round(successful_lookups / attempted_lookups, 3) if attempted_lookups else 0,
        "average_latency_ms": round(sum(latencies_ms) / len(latencies_ms), 4) if latencies_ms else 0,
        "message_overhead": message_overhead,
        "messages_per_lookup": round(message_overhead / successful_lookups, 3) if successful_lookups else 0,
        "max_lookup_trace": accumulator["max_lookup_trace"],
        "sample_errors": accumulator["errors"],
    }


# Chạy benchmark lookup trực tiếp trên ring hiện tại đang hiển thị trong UI
# Tính metric từ topology, node active và resource thật sau các thao tác add/kill/update
def run_current_ring_metrics(
    ring: ChordRing,
    *,
    trial_count: int = 5,
    lookups_per_trial: int = 100,
    seed: int | None = None,
    output_path: str | Path | None = None,
) -> dict[str, Any]:
    # Kiểm tra tham số để tránh chia trung bình trên tập rỗng
    if lookups_per_trial < 1:
        raise ValueError("lookups_per_trial must be at least 1")
    if trial_count < 1:
        raise ValueError("trial_count must be at least 1")

    # Chụp danh sách node/resource đang thật sự tồn tại trong ring hiện tại
    active_ids = ring.active_node_ids
    resource_ids = list(ring.resources.keys())

    # Chặn benchmark khi ring không đủ dữ liệu để lookup ngẫu nhiên
    if not active_ids:
        raise ValueError("metrics require at least one active node")
    if not resource_ids:
        raise ValueError("metrics require at least one resource")

    # Dùng seed riêng để kết quả benchmark lặp lại được nhưng không làm đổi RNG của ring
    rng = random.Random((ring.seed if seed is None else seed) + 2)
    accumulator = _empty_metric_accumulator()

    # Chạy nhiều trial trên cùng topology hiện tại để đo đúng trạng thái UI đang hiển thị
    for _ in range(trial_count):
        for _ in range(lookups_per_trial):
            # Chọn resource và node bắt đầu từ danh sách thật của ring hiện tại
            resource_id = rng.choice(resource_ids)
            start_node_id = rng.choice(active_ids)

            # Ghi nhận riêng thành công/thất bại để thống kê không bị "đẹp giả" khi có lỗi lookup.
            _record_lookup_sample(accumulator, ring, resource_id, start_node_id)

    # Gom toàn bộ lookup thành một điểm metric duy nhất cho số node hiện tại
    node_count = len(active_ids)
    point = _build_metric_point(
        node_count=node_count,
        lookups_per_trial=lookups_per_trial,
        trial_count=trial_count,
        accumulator=accumulator,
    )

    # Chỉ sinh ảnh biểu đồ khi hàm gọi truyền output_path
    chart_path = None
    if output_path is not None:
        chart_path = _save_metric_chart([point], Path(output_path))

    # Trả một điểm duy nhất vì UI chỉ hiển thị metric của ring hiện tại
    return {
        "points": [point],
        "chart_path": str(chart_path) if chart_path else None,
        "message": "Metrics completed successfully.",
    }


# Chạy benchmark lookup theo danh sách kích thước mạng và trả về số liệu tổng hợp
# UI hiện truyền một mốc duy nhất là số node hiện tại, script vẫn có thể truyền nhiều mốc
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
    # Kiểm tra số lần lookup và số trial để tránh chia trung bình trên tập rỗng
    if lookups_per_size < 1:
        raise ValueError("lookups_per_size must be at least 1")
    if trial_count < 1:
        raise ValueError("trial_count must be at least 1")

    # Tự tạo tối đa 50 mốc node nếu hàm gọi không truyền danh sách node_sizes cụ thể
    if node_sizes is None:
        node_sizes = build_growth_node_sizes(max_node_count)

    # Tách RNG chọn resource/start node khỏi seed tạo topology để kết quả ổn định hơn
    rng = random.Random(seed + 2)
    fixed_points = fixed_points or {}
    points: list[dict[str, Any]] = []

    # Duyệt từng kích thước mạng N để tạo các điểm dữ liệu cho biểu đồ
    for node_count in node_sizes:
        if node_count in fixed_points:
            points.append(fixed_points[node_count])
            continue

        accumulator = _empty_metric_accumulator()

        # Chạy nhiều trial để giảm nhiễu do topology ngẫu nhiên của từng lần sinh ring
        for trial_index in range(trial_count):
            # Tạo ring mới cho từng trial để benchmark không phụ thuộc một topology duy nhất
            ring = ChordRing(m=m, seed=seed + node_count + trial_index * 997)
            ring.initialize_network(node_count=node_count, resource_count=resource_count)

            # Chụp danh sách resource/node active để chọn lookup ngẫu nhiên nhanh hơn
            resource_ids = list(ring.resources.keys())
            node_ids = ring.active_node_ids

            # Thực hiện nhiều lookup trên cùng topology để lấy đủ mẫu thống kê
            for _ in range(lookups_per_size):
                # Chọn resource và start node ngẫu nhiên để tránh lệch kết quả về một vùng của ring
                resource_id = rng.choice(resource_ids)
                start_node_id = rng.choice(node_ids)

                # Ghi lại đủ số lookup thử, thành công và lỗi để các cột thống kê dùng cùng mẫu đo.
                _record_lookup_sample(accumulator, ring, resource_id, start_node_id)

        # Tính số liệu tổng hợp cho toàn bộ lookup của cùng một kích thước mạng
        points.append(
            _build_metric_point(
                node_count=node_count,
                lookups_per_trial=lookups_per_size,
                trial_count=trial_count,
                accumulator=accumulator,
            )
        )

    # Chỉ sinh ảnh biểu đồ khi hàm gọi truyền output_path, giúp test logic chạy nhanh hơn
    chart_path = None
    if output_path is not None:
        chart_path = _save_metric_chart(points, Path(output_path))

    # Trả toàn bộ dữ liệu để API/UI vừa render bảng vừa hiển thị chart nếu có
    return {
        "points": points,
        "chart_path": str(chart_path) if chart_path else None,
        "message": "Metrics completed successfully.",
    }


# Tạo tối đa 50 mốc node tăng dần từ max_node_count cho benchmark mặc định
# Khi max_node_count <= 50, bảng sẽ có đủ từng dòng N = 1..max_node_count
def build_growth_node_sizes(max_node_count: int, row_limit: int = 50) -> tuple[int, ...]:
    # Chặn số node không hợp lệ trước khi sinh mốc benchmark
    if max_node_count < 1:
        raise ValueError("max_node_count must be at least 1")
    if row_limit < 1:
        raise ValueError("row_limit must be at least 1")

    if max_node_count <= row_limit:
        return tuple(range(1, max_node_count + 1))

    # Dùng set để loại mốc trùng nhau khi làm tròn các mốc tăng dần tới N lớn
    sizes = {
        max(1, round(max_node_count * step / row_limit))
        for step in range(1, row_limit + 1)
    }

    # Sắp xếp lại để biểu đồ luôn đi từ ít node đến nhiều node
    return tuple(sorted(sizes))


# Lưu biểu đồ tổng hợp metric ra file PNG
# Gồm hops/log2(N), latency mô phỏng và message overhead để khớp rubric phân tích
def _save_metric_chart(points: list[dict[str, Any]], output_path: Path) -> Path:
    # Tạo thư mục đích trước khi matplotlib ghi file ảnh
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Tách dữ liệu thành các series để matplotlib vẽ nhiều metric trong cùng một ảnh báo cáo
    node_counts = [int(point["nodes"]) for point in points]
    average_hops = [float(point["average_hops"]) for point in points]
    log_values = [float(point["log2_nodes"]) for point in points]
    average_latencies = [float(point["average_latency_ms"]) for point in points]
    message_overheads = [int(point["message_overhead"]) for point in points]
    messages_per_lookup = [float(point["messages_per_lookup"]) for point in points]
    x_ticks = node_counts
    if len(node_counts) > 15:
        step = max(1, len(node_counts) // 10)
        x_ticks = node_counts[::step]
        if x_ticks[-1] != node_counts[-1]:
            x_ticks.append(node_counts[-1])

    # Khởi tạo figure gồm ba vùng: độ phức tạp lookup, latency và overhead message
    fig, axes = plt.subplots(1, 3, figsize=(16, 4.8), dpi=140)

    # Vẽ số hop trung bình đo được từ benchmark
    axes[0].plot(
        node_counts,
        average_hops,
        marker="o",
        linewidth=2,
        label="Average lookup hops",
    )

    # Vẽ log2(N) làm mốc lý thuyết cho độ phức tạp lookup của Chord
    axes[0].plot(
        node_counts,
        log_values,
        marker="s",
        linestyle="--",
        label="log2(N) reference",
    )
    axes[0].set_title("Chord Lookup Metrics")
    axes[0].set_xlabel("Number of Nodes (N)")
    axes[0].set_ylabel("Hops")
    axes[0].set_xticks(x_ticks)
    axes[0].grid(True, alpha=0.3)
    axes[0].legend(fontsize=8)
    if len(node_counts) == 1:
        axes[0].set_xlim(node_counts[0] - 1, node_counts[0] + 1)

    # Vẽ latency mô phỏng local, giúp báo cáo có metric thời gian xử lý lookup
    axes[1].plot(
        node_counts,
        average_latencies,
        marker="^",
        linewidth=2,
        color="#2563eb",
        label="Avg simulated lookup time (ms)",
    )
    axes[1].set_title("Lookup Latency")
    axes[1].set_xlabel("Number of Nodes (N)")
    axes[1].set_ylabel("Latency (ms)")
    axes[1].set_xticks(x_ticks)
    axes[1].grid(True, alpha=0.3)
    axes[1].legend(fontsize=8)
    if len(node_counts) == 1:
        axes[1].set_xlim(node_counts[0] - 1, node_counts[0] + 1)

    # Vẽ tổng overhead message và số message trung bình mỗi lookup
    overhead_axis = axes[2]
    per_lookup_axis = overhead_axis.twinx()
    overhead_axis.bar(
        node_counts,
        message_overheads,
        width=3 if len(node_counts) > 1 else 0.5,
        alpha=0.45,
        color="#64748b",
        label="Message overhead",
    )
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
    if len(node_counts) == 1:
        overhead_axis.set_xlim(node_counts[0] - 1, node_counts[0] + 1)

    # Gom legend của hai trục ở subplot cuối để người xem không nhầm đơn vị
    left_handles, left_labels = overhead_axis.get_legend_handles_labels()
    right_handles, right_labels = per_lookup_axis.get_legend_handles_labels()
    overhead_axis.legend(left_handles + right_handles, left_labels + right_labels, fontsize=8)

    # Gắn nhãn trục dùng chung cho toàn bộ ảnh
    fig.tight_layout()

    # Lưu PNG rồi đóng figure để tránh giữ bộ nhớ giữa nhiều lần benchmark
    fig.savefig(output_path)
    plt.close(fig)

    hops_path = output_path.with_name(f"{output_path.stem}_hops{output_path.suffix}")
    latency_path = output_path.with_name(f"{output_path.stem}_latency{output_path.suffix}")
    overhead_path = output_path.with_name(f"{output_path.stem}_overhead{output_path.suffix}")

    hops_fig, hops_axis = plt.subplots(figsize=(5.4, 3.6), dpi=140)
    hops_axis.plot(node_counts, average_hops, marker="o", linewidth=2, label="Average lookup hops")
    hops_axis.plot(node_counts, log_values, marker="s", linestyle="--", label="log2(N) reference")
    hops_axis.set_title("Chord Lookup Hops")
    hops_axis.set_xlabel("Number of Nodes (N)")
    hops_axis.set_ylabel("Hops")
    hops_axis.set_xticks(x_ticks)
    hops_axis.grid(True, alpha=0.3)
    hops_axis.legend(fontsize=8)
    if len(node_counts) == 1:
        hops_axis.set_xlim(node_counts[0] - 1, node_counts[0] + 1)
    hops_fig.tight_layout()
    hops_fig.savefig(hops_path)
    plt.close(hops_fig)

    latency_fig, latency_axis = plt.subplots(figsize=(5.4, 3.6), dpi=140)
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
    if len(node_counts) == 1:
        latency_axis.set_xlim(node_counts[0] - 1, node_counts[0] + 1)
    latency_fig.tight_layout()
    latency_fig.savefig(latency_path)
    plt.close(latency_fig)

    overhead_fig, overhead_axis = plt.subplots(figsize=(5.4, 3.6), dpi=140)
    per_lookup_axis = overhead_axis.twinx()
    overhead_axis.bar(
        node_counts,
        message_overheads,
        width=3 if len(node_counts) > 1 else 0.5,
        alpha=0.45,
        color="#64748b",
        label="Message overhead",
    )
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
    if len(node_counts) == 1:
        overhead_axis.set_xlim(node_counts[0] - 1, node_counts[0] + 1)
    left_handles, left_labels = overhead_axis.get_legend_handles_labels()
    right_handles, right_labels = per_lookup_axis.get_legend_handles_labels()
    overhead_axis.legend(left_handles + right_handles, left_labels + right_labels, fontsize=8)
    overhead_fig.tight_layout()
    overhead_fig.savefig(overhead_path)
    plt.close(overhead_fig)
    return output_path
