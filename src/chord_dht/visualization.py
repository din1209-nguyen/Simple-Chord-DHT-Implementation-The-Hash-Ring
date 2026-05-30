# Vẽ đồ thị NetworkX và lưu ảnh PNG mô tả topology của Chord ring
# Hỗ trợ highlight đường đi lookup để quan sát từng hop định tuyến

from __future__ import annotations

# Import math để tính tọa độ tròn
import math

# Import Path để thao tác đường dẫn lưu ảnh
from pathlib import Path

# Import Any để mô tả kiểu dữ liệu trả về
from typing import Any

# Import matplotlib để vẽ ảnh
import matplotlib

# Chọn backend không cần GUI để sinh ảnh trong nền
matplotlib.use("Agg")

# Import pyplot để tạo figure và lưu ảnh
import matplotlib.pyplot as plt

# Import networkx để dựng đồ thị định tuyến
import networkx as nx

# Import ChordRing để lấy trạng thái topology
from .chord import ChordRing


# Dựng graph có hướng từ trạng thái ring hiện tại
def build_topology_graph(ring: ChordRing) -> nx.DiGraph:
    # Khởi tạo graph có hướng
    graph = nx.DiGraph()

    # Lấy danh sách node active
    active_ids = ring.active_node_ids

    # Thêm node trước để đảm bảo node luôn được vẽ
    for node_id in active_ids:
        graph.add_node(node_id)

    # Duyệt từng node để thêm cạnh successor và finger
    for node_id in active_ids:
        # Đọc node từ ring
        node = ring.nodes[node_id]

        # Thêm cạnh successor để biểu diễn vòng chính
        if node.successor is not None and node.successor in active_ids:
            graph.add_edge(node_id, node.successor, edge_type="successor")

        # Duyệt finger table để thêm cạnh shortcut
        for entry in node.finger_table:
            # Bỏ qua finger trỏ về chính nó
            # Bỏ qua finger trỏ tới node không active
            if entry.node_id in active_ids and entry.node_id != node_id:
                # Đọc edge_type hiện tại nếu cạnh đã tồn tại
                existing_type = graph.get_edge_data(node_id, entry.node_id, {}).get("edge_type")

                # Đánh dấu both khi cạnh vừa là successor vừa là finger
                edge_type = "both" if existing_type in {"successor", "both"} else "finger"

                # Thêm cạnh finger vào graph
                graph.add_edge(node_id, entry.node_id, edge_type=edge_type)

    # Trả về graph đã dựng
    return graph


# Tính tọa độ node trên đường tròn theo tỉ lệ id trong không gian định danh
def circular_identifier_positions(ring: ChordRing) -> dict[int, tuple[float, float]]:
    # Khởi tạo dict lưu vị trí theo node_id
    positions: dict[int, tuple[float, float]] = {}

    # Cố định bán kính vòng tròn
    radius = 1.0

    # Duyệt node active để tính vị trí
    for node_id in ring.active_node_ids:
        # Tính góc theo tỉ lệ node_id trên vòng
        angle = -2 * math.pi * (node_id / ring.identifier_space)

        # Đổi góc sang tọa độ x y
        positions[node_id] = (radius * math.cos(angle), radius * math.sin(angle))

    # Trả về bảng vị trí
    return positions


# Vẽ topology ra PNG và highlight lookup path nếu được truyền vào
def save_topology_graph(
    ring: ChordRing,
    output_path: str | Path,
    *,
    lookup_path: list[int] | None = None,
    title: str = "Chord Ring Topology",
) -> dict[str, Any]:
    # Chuẩn hóa output_path sang Path
    output_path = Path(output_path)

    # Tạo thư mục chứa ảnh nếu chưa có
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Dựng graph từ ring
    graph = build_topology_graph(ring)

    # Tính vị trí node theo vòng
    positions = circular_identifier_positions(ring)

    # Lấy danh sách node active
    active_ids = ring.active_node_ids

    # Chuẩn hóa lookup_path thành list rỗng
    lookup_path = lookup_path or []

    # Tạo danh sách cạnh trong lookup path
    lookup_edges = list(zip(lookup_path, lookup_path[1:]))

    # Tạo set node thuộc path
    path_set = set(lookup_path)

    # Tô màu node thuộc path
    node_colors = [
        "#c2410c" if node_id in path_set else "#134e4a" for node_id in active_ids
    ]

    # Lọc các cạnh successor để vẽ vòng chính
    successor_edges = [
        (source, target)
        for source, target, data in graph.edges(data=True)
        if data.get("edge_type") in {"successor", "both"}
    ]

    # Lọc các cạnh finger để vẽ shortcut
    finger_edges = [
        (source, target)
        for source, target, data in graph.edges(data=True)
        if data.get("edge_type") in {"finger", "both"}
    ]

    # Tính tham số hiển thị theo số node
    n = len(active_ids)
    side = min(22.0, 13.0 + n * 0.09)
    dpi = 180 if n <= 40 else 150 if n <= 70 else 120
    node_size = max(230.0, 860.0 - 4.6 * n)
    finger_w = max(0.7, 1.55 - 0.006 * n)
    succ_w = max(1.35, 2.15 - 0.007 * n)
    finger_alpha = max(0.2, 0.36 - 0.002 * n)

    # Tạo figure và tắt trục
    plt.figure(figsize=(side, side), dpi=dpi)
    plt.axis("off")
    plt.margins(0.005)

    # Vẽ cạnh finger trước để nằm dưới
    nx.draw_networkx_edges(
        graph,
        positions,
        edgelist=finger_edges,
        edge_color="#64748b",
        alpha=finger_alpha,
        arrows=False,
        width=finger_w,
    )

    # Vẽ cạnh successor sau để nổi bật vòng chính
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

    # Vẽ node active lên trên cạnh
    nx.draw_networkx_nodes(
        graph,
        positions,
        nodelist=active_ids,
        node_color=node_colors,
        node_size=node_size,
        linewidths=max(0.5, 0.95 - 0.004 * n),
        edgecolors="#e2e8f0",
    )

    # Vẽ cạnh lookup path khi có path
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

    # Vẽ label khi số node không quá lớn
    if n <= 60:
        # Chọn font lớn để đọc trên UI
        label_font = 18.0

        # Tạo bbox nền cho label thường
        label_bbox = {
            "boxstyle": "round,pad=0.36",
            "facecolor": "#fafafa",
            "edgecolor": "#1e293b",
            "linewidth": 1.45,
            "alpha": 0.97,
        }

        # Tạo bbox nền cho label thuộc path
        path_label_bbox = {
            "boxstyle": "round,pad=0.4",
            "facecolor": "#fff7ed",
            "edgecolor": "#dc2626",
            "linewidth": 3.2,
            "alpha": 1.0,
        }

        # Tạo set node thuộc path để lọc label
        path_nodes = set(lookup_path)

        # Tạo label cho node thường
        normal_labels = {
            node_id: str(node_id)
            for node_id in active_ids
            if node_id not in path_nodes
        }

        # Tạo label cho node thuộc path theo thứ tự xuất hiện
        path_labels = {
            node_id: str(node_id)
            for node_id in dict.fromkeys(lookup_path)
            if node_id in positions
        }

        # Vẽ label cho node thường
        nx.draw_networkx_labels(
            graph,
            positions,
            labels=normal_labels,
            font_size=label_font,
            font_color="#020617",
            font_weight="bold",
            bbox=label_bbox,
        )

        # Vẽ label cho node thuộc path
        nx.draw_networkx_labels(
            graph,
            positions,
            labels=path_labels,
            font_size=label_font,
            font_color="#7f1d1d",
            font_weight="bold",
            bbox=path_label_bbox,
        )

    # Vẽ viền ngoài cho node thuộc path để nổi bật
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

    # Căn sát nội dung vào khung ảnh
    plt.subplots_adjust(left=0, right=1, top=1, bottom=0)

    # Lưu ảnh ra PNG
    plt.savefig(output_path, bbox_inches="tight", pad_inches=0.01)

    # Đóng figure để tránh rò bộ nhớ
    plt.close()

    # Trả về report tóm tắt cho UI
    return {
        "node_count": len(active_ids),
        "successor_edges": len(successor_edges),
        "finger_edges": len(finger_edges),
        "path_edges": len(lookup_edges),
        "path_nodes": len(path_set),
        "chart_path": str(output_path),
    }
