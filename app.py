# Cung cấp giao diện web mô phỏng Chord DHT

from __future__ import annotations

import logging
import math
import os
import sys
import time
from pathlib import Path
from threading import Lock
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from flask import Flask, jsonify, render_template, request
from werkzeug.exceptions import HTTPException

# Thêm thư mục src vào sys.path để import chord_dht
PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from chord_dht import (
    ChordRing,
    build_growth_node_sizes,
    run_lookup_metrics,
    save_topology_graph,
)

# Cấu hình logging ghi lại các hoạt động
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

# Tạo ứng dụng Flask
app = Flask(__name__)
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0

# Khóa đồng bộ bảo vệ ring state và thao tác Matplotlib
coordinator_lock = Lock()
plot_lock = Lock()

# Đường dẫn lưu trữ ảnh và trạng thái
TOPOLOGY_CHART_PATH = PROJECT_ROOT / "static" / "metrics" / "topology_graph.png"
METRICS_CHART_BASE = PROJECT_ROOT / "static" / "metrics" / "hops_chart"
STATE_PATH = PROJECT_ROOT / "data" / "state.json"


# ==================== Lưu và tải lại trạng thái ====================

# Chuyển trạng thái ring thành dictionary để ghi JSON
def _ring_state_to_json(ring: ChordRing) -> dict[str, Any]:
    global last_metrics_payload
    return {
        "schema_version": 1,  # Phiên bản schema để tracking thay đổi
        "saved_at": time.time(),  # Timestamp lưu trạng thái
        "config": {  # Cấu hình của ring
            "m": ring.m,  # Số bit của không gian ID
            "seed": ring.seed,  # Seed cho random
            "replication_count": ring.replication_count,  # Số bản sao của mỗi resource
        },
        "nodes": [
            {"node_id": node.node_id, "active": bool(node.active)}  # Danh sách node và trạng thái hoạt động
            for node in ring.nodes.values()
        ],
        "resources": sorted(list(ring.resources.keys())),  # Danh sách resource đã được sắp xếp
        "metrics": last_metrics_payload,  # Metrics đã lưu trước đó
    }


# Khôi phục trạng thái ring từ dictionary JSON
def _ring_state_from_json(payload: dict[str, Any]) -> ChordRing:
    global last_metrics_payload
    metrics_payload = payload.get("metrics")  # Lấy metrics từ payload
    last_metrics_payload = metrics_payload if isinstance(metrics_payload, dict) else None  # Cập nhật biến toàn cục nếu metrics hợp lệ

    config = payload.get("config") or {}  # Lấy cấu hình hoặc empty dict nếu không có
    ring = ChordRing(
        m=int(config.get("m", 16)),  # Số bit không gian ID, mặc định 16
        seed=int(config.get("seed", 61)),  # Seed random, mặc định 61
        replication_count=int(config.get("replication_count", 3))  # Số bản sao, mặc định 3
    )
    for node_info in payload.get("nodes") or []:  # Duyệt qua danh sách node từ JSON
        node_id = int(node_info["node_id"])  # Lấy node_id
        ring.nodes[node_id] = ring.nodes.get(node_id) or __import__("chord_dht.models", fromlist=["Node"]).Node(node_id=node_id)  # Tạo node mới nếu chưa tồn tại
        ring.nodes[node_id].active = bool(node_info.get("active", True))  # Cập nhật trạng thái hoạt động
        if not ring.nodes[node_id].active:  # Nếu node không hoạt động
            ring.failed_nodes.add(node_id)  # Thêm vào tập failed_nodes

    active_ids = ring.active_node_ids  # Lấy danh sách node đang hoạt động
    for i, node_id in enumerate(active_ids):  # Duyệt qua từng node để nối circular links
        ring.nodes[node_id].successor = active_ids[(i + 1) % len(active_ids)]  # Đặt successor là node tiếp theo
        ring.nodes[node_id].predecessor = active_ids[(i - 1) % len(active_ids)]  # Đặt predecessor là node trước đó

    ring.stabilize()  # Tính toán lại liên kết và finger tables

    for resource_id in payload.get("resources") or []:  # Duyệt qua danh sách resource từ JSON
        rid = str(resource_id).strip()  # Chuẩn hóa resource_id
        if rid and rid not in ring.resources:  # Nếu resource hợp lệ và chưa tồn tại
            ring.add_resource(rid)  # Thêm resource vào ring

    ring.stabilize()  # Stabilize lần cuối sau khi khôi phục resources
    return ring


# Ghi trạng thái ring vào file JSON với cơ chế atomic rename
def _save_ring_state(ring: ChordRing) -> None:
    import json

    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)  # Tạo thư mục cha nếu chưa tồn tại
    tmp = STATE_PATH.with_suffix(f".json.tmp-{os.getpid()}-{time.time_ns()}")  # Tạo file tạm với PID và timestamp
    with tmp.open("w", encoding="utf-8") as f:  # Mở file tạm để ghi
        json.dump(_ring_state_to_json(ring), f, ensure_ascii=False, indent=2)  # Ghi JSON với unicode
        f.flush()  # Flush buffer
        os.fsync(f.fileno())  # Force ghi xuống disk

    last_exc: OSError | None = None  # Khởi tạo biến lưu exception
    for attempt in range(8):  # Thử đổi tên 8 lần
        try:
            tmp.replace(STATE_PATH)  # Đổi tên file tạm thành file chính thức
            return
        except PermissionError as exc:  # Bắt lỗi file lock trên Windows
            last_exc = exc
            time.sleep(0.05 * (attempt + 1))  # Chờ tăng dần
    try:
        if tmp.exists():  # Kiểm tra file tạm còn tồn tại
            tmp.unlink()  # Xóa file tạm
    except OSError:
        pass
    if last_exc is not None:  # Nếu vẫn còn exception sau khi retry
        raise last_exc


# Đọc và khôi phục trạng thái ring từ file JSON
def _load_ring_state() -> ChordRing | None:
    import json

    if not STATE_PATH.exists():  # Kiểm tra file có tồn tại không
        return None
    with STATE_PATH.open("r", encoding="utf-8") as f:  # Mở file để đọc
        payload = json.load(f)  # Parse JSON
    if not isinstance(payload, dict):  # Kiểm tra payload có phải dict không
        return None
    return _ring_state_from_json(payload)  # Khôi phục ring từ payload


# ==================== Biến toàn cục ====================

ring = ChordRing(m=16, seed=61, replication_count=3)  # Khởi tạo ring mặc định với m=16, seed=61, 3 bản sao
ring_startup_completed = False  # Cờ đánh dấu đã khởi động xong chưa
startup_lock = Lock()  # Lock cho quá trình khởi động
last_metrics_payload: dict[str, Any] | None = None  # Lưu metrics gần nhất


# ==================== Hàm trợ giúp ====================

# Tạo phản hồi lỗi JSON cho API endpoint
def json_error(message: str, status_code: int = 400):
    response = jsonify({"ok": False, "message": message})  # Tạo JSON response với ok=False
    response.status_code = status_code  # Đặt HTTP status code
    return response


# Trích xuất giá trị số nguyên từ payload JSON
def parse_int_field(payload: dict[str, Any], field: str, default: int | None = None) -> int:
    raw_value = payload.get(field, default)  # Lấy giá trị từ payload hoặc default
    if raw_value is None or raw_value == "":  # Kiểm tra giá trị hợp lệ
        raise ValueError(f"{field} is required")  # Ném exception nếu thiếu trường bắt buộc
    return int(raw_value)  # Chuyển đổi sang int


# Tạo ba biểu đồ (hops, latency, overhead) từ danh sách điểm sweep metrics
def save_metric_charts_from_points(points: list[dict[str, Any]]) -> dict[str, str]:
    METRICS_CHART_BASE.parent.mkdir(parents=True, exist_ok=True)  # Tạo thư mục lưu biểu đồ
    urls: dict[str, str] = {}  # Dictionary lưu URL của các biểu đồ
    ts = time.time_ns()  # Timestamp để đặt tên file duy nhất

    node_counts = [int(p["nodes"]) for p in points]  # Trích xuất số node từ mỗi điểm
    average_hops = [float(p["average_hops"]) for p in points]  # Trích xuất average hops
    log_values = [float(p["log2_nodes"]) for p in points]  # Trích xuất log2(N) để so sánh
    average_latencies = [float(p["average_latency_ms"]) for p in points]  # Trích xuất latency
    messages_per_lookup = [float(p["messages_per_lookup"]) for p in points]  # Trích xuất message overhead

    # Tạo biểu đồ hops vs log2(N)
    hops_path = METRICS_CHART_BASE.with_name(f"{METRICS_CHART_BASE.name}_sweep_hops_{ts}.png")  # Tạo đường dẫn file biểu đồ
    plt.figure(figsize=(7.0, 4.2), dpi=150)  # Tạo figure với kích thước và DPI
    plt.plot(node_counts, average_hops, marker="o", linewidth=2, color="#0f766e", label="Average hops")  # Vẽ đường average hops
    plt.plot(node_counts, log_values, marker="s", linestyle="--", color="#f59e0b", label="log2(N)")  # Vẽ đường log2(N) để so sánh
    plt.title("Lookup hops vs log2(N)", fontsize=12, fontweight="bold")  # Đặt tiêu đề biểu đồ
    plt.xlabel("Number of nodes (N)", fontsize=10)  # Đặt nhãn trục x
    plt.ylabel("Hops", fontsize=10)  # Đặt nhãn trục y
    plt.xticks(node_counts, fontsize=7, rotation=90)  # Đặt tick trục x với xoay 90 độ
    plt.yticks(fontsize=9)  # Đặt tick trục y
    plt.grid(True, alpha=0.3)  # Bật grid với độ trong suốt 30%
    plt.legend(fontsize=9)  # Hiển thị legend
    plt.tight_layout()  # Tự động điều chỉnh layout
    plt.savefig(hops_path, dpi=150)  # Lưu biểu đồ
    plt.close()  # Đóng figure để giải phóng bộ nhớ
    urls["hops"] = f"/static/metrics/{hops_path.name}"  # Thêm URL vào dictionary

    # Tạo biểu đồ latency
    latency_path = METRICS_CHART_BASE.with_name(f"{METRICS_CHART_BASE.name}_sweep_latency_{ts}.png")  # Tạo đường dẫn file latency
    plt.figure(figsize=(7.0, 4.2), dpi=150)  # Tạo figure mới
    plt.plot(node_counts, average_latencies, marker="^", linewidth=2, color="#2563eb", label="Average latency (ms)")  # Vẽ đường latency
    plt.title("Lookup latency (ms)", fontsize=12, fontweight="bold")  # Đặt tiêu đề
    plt.xlabel("Number of nodes (N)", fontsize=10)  # Đặt nhãn trục x
    plt.ylabel("Latency (ms)", fontsize=10)  # Đặt nhãn trục y
    plt.xticks(node_counts, fontsize=7, rotation=90)  # Đặt tick trục x
    plt.yticks(fontsize=9)  # Đặt tick trục y
    plt.grid(True, alpha=0.3)  # Bật grid
    plt.legend(fontsize=9)  # Hiển thị legend
    plt.tight_layout()  # Tự động điều chỉnh layout
    plt.savefig(latency_path, dpi=150)  # Lưu biểu đồ
    plt.close()  # Đóng figure
    urls["latency"] = f"/static/metrics/{latency_path.name}"  # Thêm URL vào dictionary

    # Tạo biểu đồ message overhead
    overhead_path = METRICS_CHART_BASE.with_name(f"{METRICS_CHART_BASE.name}_sweep_overhead_{ts}.png")  # Tạo đường dẫn file overhead
    plt.figure(figsize=(7.0, 4.2), dpi=150)  # Tạo figure mới
    plt.plot(node_counts, messages_per_lookup, marker="D", linewidth=2, color="#b45309", label="Messages per lookup")  # Vẽ đường message overhead
    plt.title("Message overhead (messages/lookup)", fontsize=12, fontweight="bold")  # Đặt tiêu đề
    plt.xlabel("Number of nodes (N)", fontsize=10)  # Đặt nhãn trục x
    plt.ylabel("Messages / lookup", fontsize=10)  # Đặt nhãn trục y
    plt.xticks(node_counts, fontsize=7, rotation=90)  # Đặt tick trục x
    plt.yticks(fontsize=9)  # Đặt tick trục y
    plt.grid(True, alpha=0.3)  # Bật grid
    plt.legend(fontsize=9)  # Hiển thị legend
    plt.tight_layout()  # Tự động điều chỉnh layout
    plt.savefig(overhead_path, dpi=150)  # Lưu biểu đồ
    plt.close()  # Đóng figure
    urls["overhead"] = f"/static/metrics/{overhead_path.name}"  # Thêm URL vào dictionary

    return urls


# Tải file state.json một lần duy nhất khi app khởi động
def _autoload_once() -> None:
    global ring_startup_completed, ring  # Khai báo sử dụng biến toàn cục
    if ring_startup_completed:  # Kiểm tra đã khởi động chưa
        return
    with startup_lock:  # Lock để tránh race condition
        if ring_startup_completed:  # Double-check sau khi acquire lock
            return
        loaded = None  # Khởi tạo biến loaded
        try:
            loaded = _load_ring_state()  # Thử tải trạng thái từ file
        except Exception as exc:
            logging.warning(f"Auto-load state failed (continuing anyway): {exc}")  # Log warning nếu thất bại
        if loaded is not None:  # Nếu tải thành công
            ring = loaded  # Cập nhật biến ring toàn cục
        ring_startup_completed = True  # Đánh dấu đã khởi động xong


# ==================== Xử lý lỗi ====================

# Xử lý HTTP exception cho API endpoint
@app.errorhandler(HTTPException)
def handle_http_error(exc: HTTPException):
    if request.path.startswith("/api/"):  # Kiểm tra request có phải API không
        return json_error(exc.description or exc.name, exc.code or 500)  # Trả về JSON error
    return exc  # Trả về exception gốc cho non-API


# Xử lý exception không mong muốn cho API endpoint
@app.errorhandler(Exception)
def handle_unexpected_error(exc: Exception):
    if request.path.startswith("/api/"):  # Kiểm tra request có phải API không
        return json_error(str(exc) or "Internal server error", 500)  # Trả về JSON error
    raise exc  # Re-raise exception cho non-API


# ==================== Các endpoint API ====================

# Trả về trang index
@app.get("/")
def index():
    return render_template("index.html")


# Trả về trạng thái ring
@app.get("/api/state")
def state():
    with coordinator_lock:  # Lock để đồng bộ truy cập ring
        _autoload_once()  # Đảm bảo đã autoload
        return jsonify({"ok": True, "state": ring.summary(sample_size=None)})  # Trả về summary của ring


# Trả về danh sách resource
@app.get("/api/resources")
def list_resources():
    with coordinator_lock:  # Lock để đồng bộ truy cập ring
        _autoload_once()  # Đảm bảo đã autoload
        summary = ring.summary(sample_size=200)  # Lấy summary với giới hạn 200 resources
    return jsonify({"ok": True, "count": summary["resource_count"], "resources": summary["sample_resources"]})  # Trả về danh sách resource


# Trả về chi tiết một node
@app.get("/api/node/<int:node_id>")
def node_details(node_id: int):
    with coordinator_lock:  # Lock để đồng bộ truy cập ring
        _autoload_once()  # Đảm bảo đã autoload
        return jsonify({"ok": True, "node": ring.node_details(node_id)})  # Trả về chi tiết node


# Khởi tạo ring mới
@app.post("/api/initialize")
def initialize_network():
    payload = request.get_json(silent=True) or {}  # Lấy JSON payload từ request
    try:
        with coordinator_lock:  # Lock để đồng bộ truy cập ring
            _autoload_once()  # Đảm bảo đã autoload
            nodes = parse_int_field(payload, "nodes", 50)  # Trích xuất số node, mặc định 50
            resources = parse_int_field(payload, "resources", 1000)  # Trích xuất số resource, mặc định 1000
            m = parse_int_field(payload, "m", 16)  # Trích xuất số bit m, mặc định 16
            seed = parse_int_field(payload, "seed", 61)  # Trích xuất seed, mặc định 61
            replication_count = parse_int_field(payload, "replication_count", 3)  # Trích xuất số bản sao, mặc định 3

            global ring  # Khai báo sử dụng biến ring toàn cục
            ring = ChordRing(m=m, seed=seed, replication_count=replication_count)  # Tạo ring mới với cấu hình
            state_payload = ring.initialize_network(node_count=nodes, resource_count=resources, seed=seed, replication_count=replication_count)  # Khởi tạo network
            _save_ring_state(ring)  # Lưu trạng thái ring

        return jsonify({"ok": True, "message": "Chord ring initialized and persisted to JSON.", "state": state_payload})  # Trả về kết quả thành công
    except Exception as exc:
        return json_error(str(exc))  # Trả về lỗi


# Tìm owner của resource
@app.post("/api/lookup")
def lookup_resource():
    payload = request.get_json(silent=True) or {}  # Lấy JSON payload
    resource_id = str(payload.get("resource_id", "")).strip()  # Lấy và chuẩn hóa resource_id
    if not resource_id:  # Kiểm tra resource_id có giá trị không
        return json_error("resource_id is required")
    start_node_id = payload.get("start_node_id")  # Lấy node bắt đầu tìm kiếm
    try:
        with coordinator_lock:  # Lock để đồng bộ truy cập ring
            _autoload_once()  # Đảm bảo đã autoload
            start = None if start_node_id in (None, "") else int(start_node_id)  # Xác định node bắt đầu
            result_obj = ring.lookup(resource_id, start_node_id=start)  # Thực hiện lookup
            result = result_obj.to_dict() if hasattr(result_obj, "to_dict") else result_obj  # Chuyển đổi kết quả thành dict
            state_payload = ring.summary(sample_size=None)  # Lấy summary của ring
            _save_ring_state(ring)  # Lưu trạng thái ring

        hops = int(result["hops"])  # Lấy số hops từ kết quả
        node_count = int(state_payload["active_node_count"])  # Lấy số node đang hoạt động
        metric = {  # Tạo dictionary metrics cho lookup
            "nodes": node_count,  # Số node trong ring
            "log2_nodes": round(math.log2(max(1, node_count)), 3),  # log2 của số node
            "attempted_lookups": 1,  # Số lookup đã thử
            "total_lookups": 1,  # Tổng số lookup
            "successful_lookups": 1,  # Số lookup thành công
            "failed_lookups": 0,  # Số lookup thất bại
            "success_rate": 1,  # Tỷ lệ thành công
            "average_hops": hops,  # Số hops trung bình
            "max_hops": hops,  # Số hops tối đa
            "average_latency_ms": 0.0,  # Latency trung bình
            "message_overhead": hops,  # Message overhead
            "messages_per_lookup": hops,  # Số message mỗi lookup
        }

        return jsonify({"ok": True, "message": "Lookup completed.", "result": result, "lookup_metric": metric})  # Trả về kết quả lookup và metrics
    except Exception as exc:
        return json_error(str(exc))  # Trả về lỗi


# Dừng một node
@app.post("/api/kill")
def kill_node():
    payload = request.get_json(silent=True) or {}  # Lấy JSON payload
    try:
        with coordinator_lock:  # Lock để đồng bộ truy cập ring
            _autoload_once()  # Đảm bảo đã autoload
            node_id = parse_int_field(payload, "node_id")  # Trích xuất node_id từ payload
            report = ring.kill_node(node_id)  # Dừng node
            _save_ring_state(ring)  # Lưu trạng thái ring
        return jsonify({"ok": True, "message": report.get("message", "Node killed."), "report": report, "state": ring.summary(sample_size=None)})  # Trả về kết quả
    except Exception as exc:
        return json_error(str(exc))  # Trả về lỗi


# Xóa một node
@app.delete("/api/node/<int:node_id>")
def delete_node(node_id: int):
    try:
        with coordinator_lock:  # Lock để đồng bộ truy cập ring
            _autoload_once()  # Đảm bảo đã autoload
            if node_id not in ring.nodes:  # Kiểm tra node có tồn tại không
                return json_error(f"Node {node_id} does not exist", 404)  # Trả về lỗi 404

            if ring.nodes[node_id].active:  # Nếu node đang hoạt động
                ring.kill_node(node_id)  # Dừng node trước khi xóa

            del ring.nodes[node_id]  # Xóa node khỏi dictionary
            ring.failed_nodes.discard(node_id)  # Loại bỏ khỏi tập failed_nodes
            ring.stabilize()  # Cập nhật liên kết sau khi xóa
            _save_ring_state(ring)  # Lưu trạng thái ring

        return jsonify({
            "ok": True,
            "message": f"Node {node_id} deleted.",  # Thông báo xóa thành công
            "state": ring.summary(sample_size=None),  # Trả về trạng thái ring mới
        })
    except Exception as exc:
        return json_error(str(exc))  # Trả về lỗi


# Thêm node mới vào ring
@app.post("/api/node")
def add_node():
    payload = request.get_json(silent=True) or {}  # Lấy JSON payload
    try:
        with coordinator_lock:  # Lock để đồng bộ truy cập ring
            _autoload_once()  # Đảm bảo đã autoload
            node_id = payload.get("node_id")  # Lấy node_id từ payload (có thể None)
            report = ring.add_node(node_id=None if node_id in (None, "") else int(node_id))  # Thêm node vào ring
            _save_ring_state(ring)  # Lưu trạng thái ring
        return jsonify({"ok": True, "message": report.get("message", "Node added."), "report": report, "state": ring.summary(sample_size=None)})  # Trả về kết quả
    except Exception as exc:
        return json_error(str(exc))  # Trả về lỗi


# Không hỗ trợ restart node
@app.post("/api/node/<int:node_id>/restart")
def restart_node(node_id: int):
    return json_error("Restart is not supported. Use /api/node to join a new node.", 400)  # Trả về lỗi không hỗ trợ


# Thêm resource mới
@app.post("/api/resource")
def add_resource():
    payload = request.get_json(silent=True) or {}  # Lấy JSON payload
    resource_id = str(payload.get("resource_id", "")).strip()  # Lấy và chuẩn hóa resource_id
    if not resource_id:  # Kiểm tra resource_id có giá trị không
        return json_error("resource_id is required")
    try:
        with coordinator_lock:  # Lock để đồng bộ truy cập ring
            _autoload_once()  # Đảm bảo đã autoload
            created = ring.add_resource(resource_id)  # Thêm resource vào ring
            _save_ring_state(ring)  # Lưu trạng thái ring
        return jsonify({"ok": True, "message": created.get("message", "Resource stored."), "resource": created.get("resource"), "state": ring.summary(sample_size=None), "trace": {"path": created.get("put_path"), "hops": created.get("put_hops"), "logs": created.get("put_logs")}})  # Trả về kết quả và trace
    except Exception as exc:
        return json_error(str(exc))  # Trả về lỗi


# Cập nhật resource
@app.put("/api/resource")
def update_resource():
    payload = request.get_json(silent=True) or {}  # Lấy JSON payload
    old_id = str(payload.get("old_resource_id", "")).strip()  # Lấy resource_id cũ
    new_id = str(payload.get("new_resource_id", "")).strip()  # Lấy resource_id mới
    if not old_id or not new_id:  # Kiểm tra cả hai có giá trị không
        return json_error("old_resource_id and new_resource_id are required")
    try:
        with coordinator_lock:  # Lock để đồng bộ truy cập ring
            _autoload_once()  # Đảm bảo đã autoload
            updated = ring.update_resource(old_id, new_id)  # Cập nhật resource
            _save_ring_state(ring)  # Lưu trạng thái ring
        return jsonify({"ok": True, "message": updated.get("message", "Resource updated."), "resource": updated.get("resource"), "state": ring.summary(sample_size=None), "trace": {"path": updated.get("put_path"), "hops": updated.get("put_hops"), "logs": updated.get("put_logs")}})  # Trả về kết quả và trace
    except Exception as exc:
        return json_error(str(exc))  # Trả về lỗi


# Xóa resource
@app.delete("/api/resource")
def delete_resource():
    payload = request.get_json(silent=True) or {}  # Lấy JSON payload
    resource_id = str(payload.get("resource_id", "")).strip()  # Lấy và chuẩn hóa resource_id
    if not resource_id:  # Kiểm tra resource_id có giá trị không
        return json_error("resource_id is required")
    try:
        with coordinator_lock:  # Lock để đồng bộ truy cập ring
            _autoload_once()  # Đảm bảo đã autoload
            deleted = ring.delete_resource(resource_id)  # Xóa resource khỏi ring
            _save_ring_state(ring)  # Lưu trạng thái ring
        return jsonify({"ok": True, "message": deleted.get("message", "Resource deleted."), "removed": True, "resource": deleted.get("resource"), "state": ring.summary(sample_size=None), "trace": {"path": deleted.get("delete_path"), "hops": deleted.get("delete_hops"), "logs": deleted.get("delete_logs")}})  # Trả về kết quả và trace
    except Exception as exc:
        return json_error(str(exc))  # Trả về lỗi


# Chạy metrics trên ring hiện tại
@app.post("/api/metrics")
def metrics_current_ring():
    payload = request.get_json(silent=True) or {}  # Lấy JSON payload
    try:
        trials = parse_int_field(payload, "trials", 5)  # Trích xuất số trials, mặc định 5
        lookups = parse_int_field(payload, "lookups", 100)  # Trích xuất số lookups mỗi trial, mặc định 100

        with coordinator_lock:  # Lock để đồng bộ truy cập ring
            _autoload_once()  # Đảm bảo đã autoload
            resource_count = len(ring.resources) or 1000  # Lấy số resource hoặc mặc định 1000
            m = ring.m  # Lấy số bit m
            seed = ring.seed  # Lấy seed

        with plot_lock:  # Lock để đồng bộ vẽ biểu đồ
            active_nodes = int(ring.summary(sample_size=None).get("active_node_count", 0) or 0)  # Lấy số node đang hoạt động
            row_count = max(1, min(active_nodes, 50))  # Giới hạn số hàng tối đa 50
            node_sizes = build_growth_node_sizes(active_nodes, row_limit=row_count)  # Xây dựng danh sách kích thước node để đo
            sweep_result = run_lookup_metrics(  # Chạy metrics lookup
                max_node_count=active_nodes,  # Số node tối đa
                node_sizes=node_sizes,  # Danh sách kích thước node
                trial_count=trials,  # Số trials
                lookups_per_size=lookups,  # Số lookups mỗi kích thước
                resource_count=resource_count,  # Số resource
                m=m,  # Số bit m
                seed=seed,  # Seed
                output_path=None,  # Không lưu file CSV
            )
            charts = save_metric_charts_from_points(sweep_result["points"])  # Tạo biểu đồ từ kết quả

        response_payload = {  # Tạo payload phản hồi
            "ok": True,
            "message": "Metrics completed successfully.",
            "sweep_points": sweep_result["points"],  # Các điểm sweep
            "node_counts": [int(p["nodes"]) for p in sweep_result["points"]],  # Danh sách số node
            "charts": charts,  # Dictionary chứa đường dẫn biểu đồ
        }

        global last_metrics_payload  # Khai báo sử dụng biến toàn cục
        last_metrics_payload = {  # Cập nhật metrics đã lưu
            "saved_at": time.time(),  # Timestamp lưu
            "trials": trials,  # Số trials
            "lookups": lookups,  # Số lookups
            "active_nodes": active_nodes,  # Số node hoạt động
            "sweep_points": response_payload["sweep_points"],  # Các điểm sweep
            "charts": response_payload["charts"],  # Biểu đồ
        }
        with coordinator_lock:  # Lock để lưu trạng thái
            _autoload_once()  # Đảm bảo đã autoload
            _save_ring_state(ring)  # Lưu trạng thái ring

        return jsonify(response_payload)  # Trả về kết quả
    except Exception as exc:
        return json_error(str(exc))  # Trả về lỗi


# Lấy metrics đã lưu trước đó
@app.get("/api/metrics/last")
def metrics_last():
    with coordinator_lock:  # Lock để đồng bộ truy cập ring
        _autoload_once()  # Đảm bảo đã autoload
        if last_metrics_payload is None:  # Kiểm tra có metrics không
            return jsonify({"ok": False, "message": "No saved metrics yet."})  # Trả về lỗi
        return jsonify({"ok": True, "metrics": last_metrics_payload})  # Trả về metrics đã lưu


# Chạy metrics sweep tùy chỉnh
@app.post("/api/metrics/sweep")
def metrics_sweep():
    payload = request.get_json(silent=True) or {}  # Lấy JSON payload
    try:
        max_nodes = parse_int_field(payload, "max_nodes", 50)  # Trích xuất số node tối đa, mặc định 50
        trials = parse_int_field(payload, "trials", 5)  # Trích xuất số trials, mặc định 5
        lookups = parse_int_field(payload, "lookups", 100)  # Trích xuất số lookups, mặc định 100
        resources = parse_int_field(payload, "resources", 1000)  # Trích xuất số resource, mặc định 1000
        m = parse_int_field(payload, "m", 16)  # Trích xuất số bit m, mặc định 16
        seed = parse_int_field(payload, "seed", 61)  # Trích xuất seed, mặc định 61

        node_sizes = tuple(payload.get("node_sizes") or [])  # Lấy danh sách kích thước node tùy chỉnh
        node_sizes = node_sizes if node_sizes else build_growth_node_sizes(max_nodes)  # Sử dụng tùy chỉnh hoặc tạo mặc định

        with plot_lock:  # Lock để đồng bộ vẽ biểu đồ
            result = run_lookup_metrics(  # Chạy metrics với cấu hình tùy chỉnh
                node_sizes=tuple(int(x) for x in node_sizes),  # Chuyển đổi sang tuple int
                max_node_count=max_nodes,  # Số node tối đa
                trial_count=trials,  # Số trials
                lookups_per_size=lookups,  # Số lookups mỗi kích thước
                resource_count=resources,  # Số resource
                m=m,  # Số bit m
                seed=seed,  # Seed
                output_path=None,  # Không lưu file CSV
            )
            charts = save_metric_charts_from_points(result["points"])  # Tạo biểu đồ
        return jsonify({"ok": True, "message": result.get("message", "Sweep completed."), **result, "charts": charts})  # Trả về kết quả
    except Exception as exc:
        return json_error(str(exc))  # Trả về lỗi


# Tạo ảnh topology
@app.post("/api/topology")
def topology():
    payload = request.get_json(silent=True) or {}  # Lấy JSON payload
    include_last_path = bool(payload.get("include_last_path", False))  # Lấy cờ có hiển thị path không
    try:
        with coordinator_lock:  # Lock để đồng bộ truy cập ring
            _autoload_once()  # Đảm bảo đã autoload
            lookup_path = None  # Khởi tạo lookup_path
            if include_last_path:  # Nếu cần hiển thị path
                lookup_path = payload.get("lookup_path")  # Lấy path từ payload
                if isinstance(lookup_path, list):  # Kiểm tra path có phải list không
                    lookup_path = [int(x) for x in lookup_path]  # Chuyển đổi các phần tử sang int
                else:
                    lookup_path = None  # Đặt None nếu không hợp lệ

            with plot_lock:  # Lock để đồng bộ vẽ biểu đồ
                report = save_topology_graph(  # Tạo biểu đồ topology
                    ring,  # Ring cần vẽ
                    TOPOLOGY_CHART_PATH,  # Đường dẫn lưu file
                    lookup_path=lookup_path,  # Path lookup để highlight
                    title="Chord Ring Topology",  # Tiêu đề biểu đồ
                )

        return jsonify({"ok": True, "message": "Topology graph generated.", "report": report, "chart_url": f"/static/metrics/{TOPOLOGY_CHART_PATH.name}?_={time.time_ns()}"})  # Trả về kết quả với URL biểu đồ
    except Exception as exc:
        return json_error(str(exc))  # Trả về lỗi


if __name__ == "__main__":
    try:
        _autoload_once()  # Tải trạng thái đã lưu trước khi nhận request
    except Exception as exc:
        logging.warning(f"Startup auto-load failed (continuing anyway): {exc}")  # Log warning nếu thất bại

    host = os.environ.get("HOST", "127.0.0.1")  # Lấy host từ biến môi trường hoặc mặc định
    port = int(os.environ.get("PORT", "5000"))  # Lấy port từ biến môi trường hoặc mặc định
    app.run(host=host, port=port, debug=False)  # Chạy ứng dụng Flask
