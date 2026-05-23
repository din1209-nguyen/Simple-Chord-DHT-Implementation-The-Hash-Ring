# Tạo đồ thị NetworkX và ảnh PNG mô tả topology của Chord ring
# Hỗ trợ highlight đường đi lookup gần nhất để người học quan sát từng hop định tuyến

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import matplotlib

# Chọn backend không cần GUI để server/test có thể sinh ảnh trong nền
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import networkx as nx

from .chord import ChordRing


# Tạo graph có hướng từ trạng thái ring hiện tại của Chord
# Gắn loại cạnh successor/finger để bước vẽ phân biệt vòng chính và shortcut
def build_topology_graph(ring: ChordRing) -> nx.DiGraph:
    # Khởi tạo graph có hướng vì lookup trong Chord đi theo chiều successor/finger
    graph = nx.DiGraph()

    # Lấy snapshot node active để bỏ qua các node đã bị kill
    active_ids = ring.active_node_ids

    # Thêm node trước để NetworkX vẫn vẽ đủ node kể cả khi cạnh bị trùng hoặc chưa có cạnh
    for node_id in active_ids:
        graph.add_node(node_id)

    # Duyệt từng node active để sinh cạnh successor và các cạnh finger
    for node_id in active_ids:
        node = ring.nodes[node_id]

        # Thêm cạnh successor để biểu diễn vòng Chord cơ bản
        if node.successor is not None and node.successor in active_ids:
            graph.add_edge(node_id, node.successor, edge_type="successor")

        # Thêm cạnh finger để biểu diễn shortcut mà lookup có thể dùng để nhảy xa hơn
        for entry in node.finger_table:
            if entry.node_id in active_ids and entry.node_id != node_id:
                # Đọc loại cạnh hiện có để không làm mất thông tin nếu finger trùng successor
                existing_type = graph.get_edge_data(node_id, entry.node_id, {}).get("edge_type")

                # Đánh dấu both khi cùng một cạnh vừa là successor vừa là finger
                edge_type = "both" if existing_type in {"successor", "both"} else "finger"
                graph.add_edge(node_id, entry.node_id, edge_type=edge_type)

    return graph


# Tính tọa độ node trên đường tròn theo tỉ lệ ID trong không gian định danh
# Giúp hình vẽ giữ đúng thứ tự clockwise của node trên vòng Chord
def circular_identifier_positions(ring: ChordRing) -> dict[int, tuple[float, float]]:
    # Dùng dict node_id -> (x, y) vì NetworkX cần map tọa độ theo ID node
    positions: dict[int, tuple[float, float]] = {}
    radius = 1.0

    # Duyệt node active để đặt từng node lên đường tròn theo vị trí định danh
    for node_id in ring.active_node_ids:
        # Chuyển tỉ lệ node_id / identifier_space thành góc radian trên đường tròn
        angle = -2 * math.pi * (node_id / ring.identifier_space)

        # Đổi góc thành tọa độ Cartesian để matplotlib có thể vẽ
        positions[node_id] = (radius * math.cos(angle), radius * math.sin(angle))

    return positions


# Vẽ topology Chord ra PNG và highlight lookup path nếu hàm gọi truyền path
def save_topology_graph(
    ring: ChordRing,
    output_path: str | Path,
    *,
    lookup_path: list[int] | None = None,
    title: str = "Chord Ring Topology",
) -> dict[str, Any]:
    # Chuẩn hóa đường dẫn output và tạo sẵn thư mục chứa ảnh
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Tạo graph NetworkX từ ring hiện tại để tách phần dữ liệu khỏi phần vẽ
    graph = build_topology_graph(ring)

    # Tính tọa độ node theo vòng định danh để ảnh phản ánh đúng topology Chord
    positions = circular_identifier_positions(ring)

    # Lấy danh sách node active để dùng thống nhất cho màu, label và thống kê
    active_ids = ring.active_node_ids

    # Chuẩn hóa lookup_path thành list rỗng nếu caller không cần highlight
    lookup_path = lookup_path or []

    # Ghép từng cặp node liên tiếp trong path thành cạnh để vẽ route lookup
    lookup_edges = list(zip(lookup_path, lookup_path[1:]))

    # Tạo set để kiểm tra nhanh node nào thuộc path khi tô màu
    path_set = set(lookup_path)

    # Tô node thuộc lookup path bằng màu nổi bật, node thường bằng màu nền ổn định
    node_colors = [
        "#c2410c" if node_id in path_set else "#134e4a" for node_id in active_ids
    ]

    # Lọc các cạnh successor/both để vẽ vòng Chord chính
    successor_edges = [
        (source, target)
        for source, target, data in graph.edges(data=True)
        if data.get("edge_type") in {"successor", "both"}
    ]

    # Lọc các cạnh finger/both để vẽ shortcut định tuyến
    finger_edges = [
        (source, target)
        for source, target, data in graph.edges(data=True)
        if data.get("edge_type") in {"finger", "both"}
    ]

    # Điều chỉnh kích thước ảnh và nét vẽ theo số node để ảnh vẫn đọc được với mạng lớn
    n = len(active_ids)
    side = min(22.0, 13.0 + n * 0.09)
    dpi = 180 if n <= 40 else 150 if n <= 70 else 120
    node_size = max(230.0, 860.0 - 4.6 * n)
    finger_w = max(0.7, 1.55 - 0.006 * n)
    succ_w = max(1.35, 2.15 - 0.007 * n)
    finger_alpha = max(0.2, 0.36 - 0.002 * n)

    # Khởi tạo canvas vuông và tắt trục vì topology là sơ đồ mạng, không phải biểu đồ trục số
    plt.figure(figsize=(side, side), dpi=dpi)
    plt.axis("off")
    plt.margins(0.005)

    # Vẽ finger trước để các shortcut nằm dưới vòng successor chính
    nx.draw_networkx_edges(
        graph,
        positions,
        edgelist=finger_edges,
        edge_color="#64748b",
        alpha=finger_alpha,
        arrows=False,
        width=finger_w,
    )

    # Vẽ successor sau để vòng Chord chính nổi bật hơn các shortcut
    nx.draw_networkx_edges(
        graph,
        positions,
        edgelist=successor_edges,
        edge_color="#1e3a5f",
        arrows=True,
        arrowstyle="-|>",
        arrowsize=max(10, 17 - n // 10),
        width=succ_w,
    )

    # Vẽ toàn bộ node active sau khi cạnh đã được đặt nền
    nx.draw_networkx_nodes(
        graph,
        positions,
        nodelist=active_ids,
        node_color=node_colors,
        node_size=node_size,
        linewidths=max(0.5, 0.95 - 0.004 * n),
        edgecolors="#e2e8f0",
    )

    # Vẽ route lookup thật bằng màu đỏ nếu có ít nhất một cạnh trong path
    if lookup_edges:
        nx.draw_networkx_edges(
            graph,
            positions,
            edgelist=lookup_edges,
            edge_color="#dc2626",
            arrows=True,
            arrowstyle="-|>",
            arrowsize=28,
            width=4.8,
            alpha=0.96,
            connectionstyle="arc3,rad=0.08",
            min_source_margin=14,
            min_target_margin=18,
        )

    # Chỉ vẽ label khi số node không quá lớn để tránh chữ chồng lên nhau
    if n <= 60:
        label_font = 18.0

        # Tạo nền label thường để ID node đọc được trên nhiều màu cạnh
        label_bbox = {
            "boxstyle": "round,pad=0.36",
            "facecolor": "#fafafa",
            "edgecolor": "#1e293b",
            "linewidth": 1.45,
            "alpha": 0.97,
        }

        # Tạo nền label riêng cho node thuộc lookup path để người xem bám theo route dễ hơn
        path_label_bbox = {
            "boxstyle": "round,pad=0.4",
            "facecolor": "#fff7ed",
            "edgecolor": "#dc2626",
            "linewidth": 3.2,
            "alpha": 1.0,
        }

        # Tách label thường khỏi label path để vẽ bằng hai style khác nhau
        path_nodes = set(lookup_path)
        normal_labels = {
            node_id: str(node_id)
            for node_id in active_ids
            if node_id not in path_nodes
        }
        path_labels = {
            node_id: str(node_id)
            for node_id in dict.fromkeys(lookup_path)
            if node_id in positions
        }

        # Vẽ label cho các node không nằm trên route lookup
        nx.draw_networkx_labels(
            graph,
            positions,
            labels=normal_labels,
            font_size=label_font,
            font_color="#020617",
            font_weight="bold",
            bbox=label_bbox,
        )

        # Vẽ label cho các node thuộc route lookup bằng style nổi bật hơn
        nx.draw_networkx_labels(
            graph,
            positions,
            labels=path_labels,
            font_size=label_font,
            font_color="#7f1d1d",
            font_weight="bold",
            bbox=path_label_bbox,
        )

    # Vẽ thêm viền ngoài cho node trên lookup path để route vẫn rõ khi ảnh có nhiều cạnh
    if lookup_edges:
        nx.draw_networkx_nodes(
            graph,
            positions,
            nodelist=list(dict.fromkeys(lookup_path)),
            node_color="none",
            node_size=node_size * 1.9,
            linewidths=5.0,
            edgecolors="#dc2626",
        )

    # Kéo nội dung ra sát biên ảnh để tận dụng diện tích hiển thị trong UI
    plt.subplots_adjust(left=0, right=1, top=1, bottom=0)

    # Lưu PNG rồi đóng figure để tránh rò bộ nhớ khi gọi endpoint topology nhiều lần
    plt.savefig(output_path, bbox_inches="tight", pad_inches=0.01)
    plt.close()

    # Trả report ngắn để frontend hiển thị số node, số cạnh và độ dài path được highlight
    return {
        "node_count": len(active_ids),
        "successor_edges": len(successor_edges),
        "finger_edges": len(finger_edges),
        "path_edges": len(lookup_edges),
        "path_nodes": len(path_set),
        "chart_path": str(output_path),
    }
