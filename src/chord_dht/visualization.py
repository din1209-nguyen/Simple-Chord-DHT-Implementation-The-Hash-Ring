from __future__ import annotations

import math

from pathlib import Path

from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt

import networkx as nx

from .chord import ChordRing

# Dựng đồ thị topology từ trạng thái ring
def build_topology_graph(ring: ChordRing) -> nx.DiGraph:

    # Tạo đồ thị có hướng để biểu diễn quan hệ successor và finger
    graph = nx.DiGraph()

    # Lấy danh sách node active đang tham gia ring
    active_ids = ring.active_node_ids

    # Thêm toàn bộ node active vào đồ thị topology
    for node_id in active_ids:
        graph.add_node(node_id)

    # Duyệt từng node để thêm cạnh successor và finger
    for node_id in active_ids:

        # Lấy node hiện tại từ ring
        node = ring.nodes[node_id]

        # Thêm cạnh successor khi successor còn active
        if node.successor is not None and node.successor in active_ids:
            graph.add_edge(node_id, node.successor, edge_type="successor")

        # Duyệt finger table để thêm cạnh định tuyến nhanh
        for entry in node.finger_table:

            # Bỏ qua finger trỏ tới node chết hoặc trỏ về chính nó
            if entry.node_id in active_ids and entry.node_id != node_id:

                existing_type = graph.get_edge_data(node_id, entry.node_id, {}).get("edge_type")

                # Gộp loại cạnh khi successor cũng đồng thời là finger
                edge_type = "both" if existing_type in {"successor", "both"} else "finger"

                # Thêm cạnh finger hoặc cạnh gộp vào đồ thị
                graph.add_edge(node_id, entry.node_id, edge_type=edge_type)

    # Trả về đồ thị đã gắn node và cạnh successor/finger
    return graph

# Tính tọa độ node trên vòng định danh
def circular_identifier_positions(ring: ChordRing) -> dict[int, tuple[float, float]]:

    # Tạo map tọa độ cho từng node active
    positions: dict[int, tuple[float, float]] = {}

    # Dùng bán kính cố định để đặt node trên vòng tròn đơn vị
    radius = 1.0

    # Duyệt từng node active để tính góc theo không gian định danh
    for node_id in ring.active_node_ids:

        # Tính góc của node dựa trên node_id và kích thước identifier space
        angle = -2 * math.pi * (node_id / ring.identifier_space)

        # Lưu tọa độ Descartes tương ứng với góc trên vòng tròn
        positions[node_id] = (radius * math.cos(angle), radius * math.sin(angle))

    # Trả về map node_id sang tọa độ hình tròn
    return positions

# Lưu ảnh topology graph ra thư mục static
def save_topology_graph(
    ring: ChordRing,
    output_path: str | Path,
    *,
    lookup_path: list[int] | None = None,
    title: str = "Chord Ring Topology",
) -> dict[str, Any]:

    # Chuẩn hóa đường dẫn output thành Path
    output_path = Path(output_path)

    # Tạo thư mục chứa ảnh topology nếu chưa tồn tại
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Dựng đồ thị topology từ ring hiện tại
    graph = build_topology_graph(ring)

    # Tính vị trí vẽ của từng node trên vòng định danh
    positions = circular_identifier_positions(ring)

    # Lấy danh sách node active để vẽ node và tính kích thước ảnh
    active_ids = ring.active_node_ids

    # Chuẩn hóa lookup_path rỗng khi caller không truyền trace
    lookup_path = lookup_path or []

    # Chuyển lookup_path thành danh sách cạnh liên tiếp để highlight
    lookup_edges = list(zip(lookup_path, lookup_path[1:]))

    # Tạo tập node nằm trên đường lookup để tô màu nổi bật
    path_set = set(lookup_path)

    # Chọn màu node theo trạng thái có nằm trên đường lookup hay không
    node_colors = [
        "#c2410c" if node_id in path_set else "#134e4a" for node_id in active_ids
    ]

    # Lọc các cạnh successor từ đồ thị
    successor_edges = [
        (source, target)
        for source, target, data in graph.edges(data=True)
        if data.get("edge_type") in {"successor", "both"}
    ]

    # Lọc các cạnh finger từ đồ thị
    finger_edges = [
        (source, target)
        for source, target, data in graph.edges(data=True)
        if data.get("edge_type") in {"finger", "both"}
    ]

    # Đếm số node để điều chỉnh kích thước hình
    n = len(active_ids)

    # Tính cạnh hình theo số node để giảm chồng lấn khi mạng lớn
    side = min(22.0, 13.0 + n * 0.09)

    # Chọn DPI thấp hơn khi mạng lớn để giảm dung lượng ảnh
    dpi = 180 if n <= 40 else 150 if n <= 70 else 120

    # Tính kích thước node theo mật độ mạng
    node_size = max(230.0, 860.0 - 4.6 * n)

    # Tính độ dày cạnh finger theo mật độ mạng
    finger_w = max(0.7, 1.55 - 0.006 * n)

    # Tính độ dày cạnh successor theo mật độ mạng
    succ_w = max(1.35, 2.15 - 0.007 * n)

    # Tính độ mờ cạnh finger để ảnh bớt rối khi nhiều node
    finger_alpha = max(0.2, 0.36 - 0.002 * n)

    # Tạo figure vuông cho topology ring
    plt.figure(figsize=(side, side), dpi=dpi)

    # Tắt trục tọa độ để ảnh chỉ tập trung vào topology
    plt.axis("off")

    # Giảm lề ngoài của hình
    plt.margins(0.005)

    # Vẽ các cạnh finger bằng màu nhạt
    nx.draw_networkx_edges(
        graph,
        positions,
        edgelist=finger_edges,
        edge_color="#64748b",
        alpha=finger_alpha,
        arrows=False,
        width=finger_w,
    )

    # Vẽ các cạnh successor bằng mũi tên rõ hơn
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

    # Vẽ các node active trên vòng định danh
    nx.draw_networkx_nodes(
        graph,
        positions,
        nodelist=active_ids,
        node_color=node_colors,
        node_size=node_size,
        linewidths=max(0.5, 0.95 - 0.004 * n),
        edgecolors="#e2e8f0",
    )

    # Vẽ nổi bật đường lookup khi có cạnh lookup cần highlight
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

    # Vẽ nhãn node khi số node đủ nhỏ để đọc được
    if n <= 60:

        # Chọn cỡ chữ nhãn node
        label_font = 18.0

        # Tạo nền nhãn cho node thông thường
        label_bbox = {
            "boxstyle": "round,pad=0.36",
            "facecolor": "#fafafa",
            "edgecolor": "#1e293b",
            "linewidth": 1.45,
            "alpha": 0.97,
        }

        # Tạo nền nhãn nổi bật cho node nằm trên lookup path
        path_label_bbox = {
            "boxstyle": "round,pad=0.4",
            "facecolor": "#fff7ed",
            "edgecolor": "#dc2626",
            "linewidth": 3.2,
            "alpha": 1.0,
        }

        # Tạo tập node cần vẽ nhãn highlight
        path_nodes = set(lookup_path)

        # Tạo nhãn cho các node không thuộc lookup path
        normal_labels = {
            node_id: str(node_id)
            for node_id in active_ids
            if node_id not in path_nodes
        }

        # Tạo nhãn cho các node thuộc lookup path theo thứ tự trace
        path_labels = {
            node_id: str(node_id)
            for node_id in dict.fromkeys(lookup_path)
            if node_id in positions
        }

        # Vẽ nhãn node thông thường
        nx.draw_networkx_labels(
            graph,
            positions,
            labels=normal_labels,
            font_size=label_font,
            font_color="#020617",
            font_weight="bold",
            bbox=label_bbox,
        )

        # Vẽ nhãn node nằm trên lookup path
        nx.draw_networkx_labels(
            graph,
            positions,
            labels=path_labels,
            font_size=label_font,
            font_color="#7f1d1d",
            font_weight="bold",
            bbox=path_label_bbox,
        )

    # Khoanh nổi các node nằm trên đường lookup khi có trace
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

    # Căn hình sát khung ảnh để tận dụng diện tích hiển thị
    plt.subplots_adjust(left=0, right=1, top=1, bottom=0)

    # Lưu ảnh topology ra đường dẫn output
    plt.savefig(output_path, bbox_inches="tight", pad_inches=0.01)

    # Đóng figure để giải phóng bộ nhớ matplotlib
    plt.close()

    # Trả về metadata ảnh topology vừa sinh
    return {
        "node_count": len(active_ids),
        "successor_edges": len(successor_edges),
        "finger_edges": len(finger_edges),
        "path_edges": len(lookup_edges),
        "path_nodes": len(path_set),
        "chart_path": str(output_path),
    }
