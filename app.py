from __future__ import annotations

import json
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

# Xác định thư mục gốc của dự án
PROJECT_ROOT = Path(__file__).resolve().parent

# Xác định thư mục chứa package backend
SRC_DIR = PROJECT_ROOT / "src"

# Thêm src vào sys.path khi chạy app.py trực tiếp
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from chord_dht import (
    ChordRing,
    FingerEntry,
    Node,
    ResourceRecord,
    build_growth_node_sizes,
    run_current_ring_metrics,
    run_lookup_metrics,
    save_topology_graph,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

# Khởi tạo Flask application
app = Flask(__name__)
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0

# Khóa thao tác đọc ghi trạng thái ring trong request API
coordinator_lock = Lock()

# Khóa quá trình sinh biểu đồ để tránh matplotlib chạy song song
plot_lock = Lock()

# Xác định đường dẫn lưu ảnh topology
TOPOLOGY_CHART_PATH = PROJECT_ROOT / "static" / "metrics" / "topology_graph.png"

# Xác định tên gốc cho các ảnh metric
METRICS_CHART_BASE = PROJECT_ROOT / "static" / "metrics" / "hops_chart"

# Xác định đường dẫn lưu snapshot trạng thái ring
STATE_PATH = PROJECT_ROOT / "data" / "state.json"

# Chuyển trạng thái ring thành payload JSON để lưu xuống đĩa
def _ring_state_to_json(ring: ChordRing) -> dict[str, Any]:
    global last_metrics_payload
    # Trả về snapshot gồm cấu hình, node, resource và metric đã lưu
    return {
        "schema_version": 1,
        "saved_at": time.time(),
        "config": {
            "m": ring.m,
            "seed": ring.seed,
            "replication_count": ring.replication_count,
        },
        "nodes": [
            {
                "node_id": node.node_id,
                "active": bool(node.active),
                "status": (
                    "failed"
                    if node.node_id in ring.failed_nodes
                    else "active"
                    if node.active
                    else "retired"
                ),
                "predecessor": node.predecessor,
                "successor": node.successor,
                "finger_table": [entry.to_dict() for entry in node.finger_table],
            }
            for node in ring.nodes.values()
        ],
        "resources": [
            resource.to_dict()
            for resource in sorted(ring.resources.values(), key=lambda r: r.resource_id)
        ],
        "metrics": last_metrics_payload,
    }

# Khôi phục ring từ payload JSON đã lưu
def _ring_state_from_json(payload: dict[str, Any]) -> ChordRing:
    global last_metrics_payload
    metrics_payload = payload.get("metrics")
    # Khôi phục metric gần nhất nếu payload chứa dữ liệu hợp lệ
    last_metrics_payload = metrics_payload if isinstance(metrics_payload, dict) else None

    config = payload.get("config") or {}
    # Tạo ring theo cấu hình đã persist
    ring = ChordRing(
        m=int(config.get("m", 16)),
        seed=int(config.get("seed", 61)),
        replication_count=int(config.get("replication_count", 1)),
    )
    # Khôi phục danh sách node và trạng thái active
    has_saved_routing = False
    for node_info in payload.get("nodes") or []:
        node_id = int(node_info["node_id"])
        ring.nodes[node_id] = ring.nodes.get(node_id) or Node(node_id=node_id)
        ring.nodes[node_id].active = bool(node_info.get("active", True))
        if "predecessor" in node_info or "successor" in node_info or "finger_table" in node_info:
            has_saved_routing = True
        ring.nodes[node_id].predecessor = node_info.get("predecessor")
        ring.nodes[node_id].successor = node_info.get("successor")
        ring.nodes[node_id].finger_table = [
            FingerEntry(
                index=int(entry.get("index", 0)),
                start=int(entry.get("start", 0)),
                interval_end=int(entry.get("interval_end", 0)),
                node_id=int(entry.get("node_id", 0)),
            )
            for entry in (node_info.get("finger_table") or [])
            if isinstance(entry, dict)
        ]
        status = str(node_info.get("status", "")).strip().lower()
        # State cũ chưa có status: inactive được xem là failed để vẫn yêu cầu recover.
        if status == "failed" or (not status and not ring.nodes[node_id].active):
            ring.failed_nodes.add(node_id)

    active_ids = ring.active_node_ids
    # Nối predecessor và successor cho các node active theo thứ tự vòng
    if not has_saved_routing:
        for i, node_id in enumerate(active_ids):
            ring.nodes[node_id].successor = active_ids[(i + 1) % len(active_ids)]
            ring.nodes[node_id].predecessor = active_ids[(i - 1) % len(active_ids)]

        ring.stabilize()

    # Khôi phục metadata resource và bản copy local tương ứng
    for res in payload.get("resources") or []:
        # Chuẩn hóa định dạng resource cũ nếu payload chỉ lưu chuỗi
        if not isinstance(res, dict):
            res = {"resource_id": str(res).strip()}
        rid = str(res.get("resource_id", "")).strip()
        # Bỏ qua resource rỗng hoặc đã được khôi phục trước đó
        if rid and rid not in ring.resources:
            record = ResourceRecord(
                resource_id=rid,
                hashed_resource_id=str(res.get("hashed_resource_id", "")),
                key=int(res.get("key", 0)),
                owner_id=int(res.get("owner_id", 0)),
                replica_node_ids=list(res.get("replica_node_ids") or []),
            )
            ring.resources[rid] = record

            # Gắn resource vào owner khi owner còn active
            if record.owner_id in ring.nodes and ring.nodes[record.owner_id].active:
                ring.nodes[record.owner_id].local_resources[rid] = record

            # Gắn resource vào các replica còn active
            for rep_id in record.replica_node_ids:
                # Bỏ qua replica trỏ tới node không tồn tại hoặc inactive
                if rep_id in ring.nodes and ring.nodes[rep_id].active:
                    ring.nodes[rep_id].local_resources[rid] = record

    if not has_saved_routing:
        ring.stabilize()

    # Trả về ring đã được ổn định sau khi khôi phục
    return ring

# Lưu trạng thái ring xuống state.json theo cách ghi tạm rồi thay thế
def _save_ring_state(ring: ChordRing) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(f".json.tmp-{os.getpid()}-{time.time_ns()}")
    # Ghi snapshot vào file tạm trước khi replace file chính
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(_ring_state_to_json(ring), f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())

    last_exc: OSError | None = None
    # Thử replace nhiều lần để tránh lỗi file đang bị Windows giữ tạm
    for attempt in range(8):
        try:
            tmp.replace(STATE_PATH)
            return
        except PermissionError as exc:
            last_exc = exc
            time.sleep(0.05 * (attempt + 1))

    # Dọn file tạm nếu replace thất bại
    try:
        if tmp.exists():
            tmp.unlink()
    except OSError:
        pass

    # Ném lại lỗi replace cuối cùng để caller biết persist thất bại
    if last_exc is not None:
        raise last_exc

# Xác định đường dẫn lưu danh sách node_id ban đầu
NODE_IDS_PATH = PROJECT_ROOT / "data" / "node_ids.json"

# Xác định đường dẫn lưu danh sách resource_id ban đầu
RESOURCE_IDS_PATH = PROJECT_ROOT / "data" / "resource_ids.json"


# Lưu danh sách node_id ra file JSON
def _save_node_ids(ring: ChordRing) -> None:
    NODE_IDS_PATH.parent.mkdir(parents=True, exist_ok=True)
    data = sorted([int(n.node_id) for n in ring.nodes.values()])
    tmp = NODE_IDS_PATH.with_suffix(f".json.tmp-{os.getpid()}-{time.time_ns()}")
    # Ghi danh sách node vào file tạm
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    last_exc: OSError | None = None
    # Thử replace nhiều lần để tránh lỗi file lock
    for attempt in range(8):
        try:
            tmp.replace(NODE_IDS_PATH)
            return
        except PermissionError as exc:
            last_exc = exc
            time.sleep(0.05 * (attempt + 1))

    # Dọn file tạm nếu replace thất bại
    try:
        if tmp.exists():
            tmp.unlink()
    except OSError:
        pass

    # Ném lại lỗi replace cuối cùng
    if last_exc is not None:
        raise last_exc


# Lưu danh sách resource_id và hash ra file JSON
def _save_resource_ids(ring: ChordRing) -> None:
    RESOURCE_IDS_PATH.parent.mkdir(parents=True, exist_ok=True)
    data = [
        {
            "resource_id": r.resource_id,
            "hashed_resource_id": r.hashed_resource_id,
        }
        for r in sorted(ring.resources.values(), key=lambda x: x.resource_id)
    ]
    tmp = RESOURCE_IDS_PATH.with_suffix(f".json.tmp-{os.getpid()}-{time.time_ns()}")
    # Ghi danh sách resource vào file tạm
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    last_exc: OSError | None = None
    # Thử replace nhiều lần để tránh lỗi file lock
    for attempt in range(8):
        try:
            tmp.replace(RESOURCE_IDS_PATH)
            return
        except PermissionError as exc:
            last_exc = exc
            time.sleep(0.05 * (attempt + 1))

    # Dọn file tạm nếu replace thất bại
    try:
        if tmp.exists():
            tmp.unlink()
    except OSError:
        pass

    # Ném lại lỗi replace cuối cùng
    if last_exc is not None:
        raise last_exc

# Lưu và xác minh các file dataset ban đầu
def _save_initial_dataset_files(ring: ChordRing) -> None:
    _save_node_ids(ring)
    _save_resource_ids(ring)

    # Đọc lại node_ids.json để xác minh số lượng đã ghi
    with NODE_IDS_PATH.open("r", encoding="utf-8") as f:
        node_ids = json.load(f)

    # Đọc lại resource_ids.json để xác minh số lượng đã ghi
    with RESOURCE_IDS_PATH.open("r", encoding="utf-8") as f:
        resource_ids = json.load(f)

    # Kiểm tra số node trong file khớp với ring vừa khởi tạo
    if len(node_ids) != len(ring.nodes):
        raise RuntimeError("node_ids.json was not written with the initialized node count")

    # Kiểm tra số resource trong file khớp với ring vừa khởi tạo
    if len(resource_ids) != len(ring.resources):
        raise RuntimeError("resource_ids.json was not written with the initialized resource count")


# Tải trạng thái ring đã persist từ state.json
def _load_ring_state() -> ChordRing | None:
    # Bỏ qua autoload khi chưa có file state
    if not STATE_PATH.exists():
        return None

    # Đọc payload JSON từ file state
    with STATE_PATH.open("r", encoding="utf-8") as f:
        payload = json.load(f)

    # Bỏ qua payload không đúng dạng dictionary
    if not isinstance(payload, dict):
        return None

    # Trả về ring được dựng lại từ payload
    return _ring_state_from_json(payload)


# Khởi tạo ring mặc định trước khi autoload state
ring = ChordRing(m=16, seed=61, replication_count=1)
ring_startup_completed = False

# Khóa quá trình autoload để chỉ chạy một lần
startup_lock = Lock()

# Lưu payload metrics gần nhất để frontend khôi phục biểu đồ
last_metrics_payload: dict[str, Any] | None = None


# Trả về lỗi API theo định dạng JSON thống nhất
def json_error(message: str, status_code: int = 400, **extra: Any):
    payload = {"ok": False, "message": message}
    payload.update(extra)
    response = jsonify(payload)
    response.status_code = status_code
    return response


def _require_no_pending_recovery():
    failed_nodes = sorted(int(node_id) for node_id in ring.failed_nodes)
    if not failed_nodes:
        return None
    return json_error(
        "A node is failed. Press Recover before running this operation.",
        409,
        requires_recovery=True,
        failed_nodes=failed_nodes,
    )


# Đọc và ép kiểu trường số nguyên từ payload request
def parse_int_field(payload: dict[str, Any], field: str, default: int | None = None) -> int:
    raw_value = payload.get(field, default)
    # Kiểm tra trường bắt buộc không được rỗng
    if raw_value is None or raw_value == "":
        raise ValueError(f"{field} is required")

    # Trả về giá trị đã ép kiểu int
    return int(raw_value)


# Sinh các biểu đồ metric từ danh sách điểm benchmark
def save_metric_charts_from_points(points: list[dict[str, Any]]) -> dict[str, str]:
    # Tạo thư mục lưu biểu đồ nếu chưa tồn tại
    METRICS_CHART_BASE.parent.mkdir(parents=True, exist_ok=True)

    # Khởi tạo map URL trả về cho frontend
    urls: dict[str, str] = {}

    # Tạo timestamp để tránh trình duyệt cache ảnh cũ
    ts = time.time_ns()

    # Tách danh sách số node từ các điểm metric
    node_counts = [int(p["nodes"]) for p in points]

    # Tách danh sách số hop trung bình để vẽ biểu đồ hop
    average_hops = [float(p["average_hops"]) for p in points]

    # Tách danh sách log2(N) để làm đường tham chiếu
    log_values = [float(p["log2_nodes"]) for p in points]

    # Tách danh sách độ trễ trung bình để vẽ biểu đồ latency
    average_latencies = [float(p["average_latency_ms"]) for p in points]

    # Tách danh sách số message mỗi lookup để vẽ overhead
    messages_per_lookup = [float(p["messages_per_lookup"]) for p in points]

    # Tạo đường dẫn ảnh biểu đồ hop
    hops_path = METRICS_CHART_BASE.with_name(f"{METRICS_CHART_BASE.name}_sweep_hops_{ts}.png")

    # Vẽ biểu đồ so sánh average hops với log2(N)
    plt.figure(figsize=(7.0, 4.2), dpi=150)
    plt.plot(node_counts, average_hops, marker="o", linewidth=2, color="#0f766e", label="Average hops")
    plt.plot(node_counts, log_values, marker="s", linestyle="--", color="#f59e0b", label="log2(N)")
    plt.title("Lookup hops vs log2(N)", fontsize=12, fontweight="bold")
    plt.xlabel("Number of nodes (N)", fontsize=10)
    plt.ylabel("Hops", fontsize=10)
    plt.xticks(node_counts, fontsize=7, rotation=90)
    plt.yticks(fontsize=9)
    plt.grid(True, alpha=0.3)
    plt.legend(fontsize=9)
    plt.tight_layout()
    plt.savefig(hops_path, dpi=150)
    plt.close()

    # Lưu URL biểu đồ hop cho frontend
    urls["hops"] = f"/static/metrics/{hops_path.name}"

    # Tạo đường dẫn ảnh biểu đồ latency
    latency_path = METRICS_CHART_BASE.with_name(f"{METRICS_CHART_BASE.name}_sweep_latency_{ts}.png")

    # Vẽ biểu đồ độ trễ lookup trung bình theo số node
    plt.figure(figsize=(7.0, 4.2), dpi=150)
    plt.plot(node_counts, average_latencies, marker="^", linewidth=2, color="#2563eb", label="Average latency (ms)")
    plt.title("Lookup latency (ms)", fontsize=12, fontweight="bold")
    plt.xlabel("Number of nodes (N)", fontsize=10)
    plt.ylabel("Latency (ms)", fontsize=10)
    plt.xticks(node_counts, fontsize=7, rotation=90)
    plt.yticks(fontsize=9)
    plt.grid(True, alpha=0.3)
    plt.legend(fontsize=9)
    plt.tight_layout()
    plt.savefig(latency_path, dpi=150)
    plt.close()

    # Lưu URL biểu đồ latency cho frontend
    urls["latency"] = f"/static/metrics/{latency_path.name}"

    # Tạo đường dẫn ảnh biểu đồ overhead
    overhead_path = METRICS_CHART_BASE.with_name(f"{METRICS_CHART_BASE.name}_sweep_overhead_{ts}.png")

    # Vẽ biểu đồ số message trung bình cho mỗi lookup
    plt.figure(figsize=(7.0, 4.2), dpi=150)
    plt.plot(node_counts, messages_per_lookup, marker="D", linewidth=2, color="#b45309", label="Messages per lookup")
    plt.title("Message overhead (messages/lookup)", fontsize=12, fontweight="bold")
    plt.xlabel("Number of nodes (N)", fontsize=10)
    plt.ylabel("Messages / lookup", fontsize=10)
    plt.xticks(node_counts, fontsize=7, rotation=90)
    plt.yticks(fontsize=9)
    plt.grid(True, alpha=0.3)
    plt.legend(fontsize=9)
    plt.tight_layout()
    plt.savefig(overhead_path, dpi=150)
    plt.close()

    # Lưu URL biểu đồ overhead cho frontend
    urls["overhead"] = f"/static/metrics/{overhead_path.name}"

    # Trả về URL của ba biểu đồ vừa sinh
    return urls


# Tự động nạp state từ đĩa đúng một lần khi có request đầu tiên
def _autoload_once() -> None:
    global ring_startup_completed, ring
    # Bỏ qua khi startup đã hoàn tất
    if ring_startup_completed:
        return
    # Khóa startup để tránh nhiều request cùng autoload
    with startup_lock:
        # Kiểm tra lại sau khi lấy lock
        if ring_startup_completed:
            return
        loaded = None
        # Thử nạp state đã lưu nhưng không chặn server nếu file lỗi
        try:
            loaded = _load_ring_state()
        except Exception as exc:
            logging.warning(f"Auto-load state failed (continuing anyway): {exc}")
        # Cập nhật ring hiện tại khi có state hợp lệ
        if loaded is not None:
            ring = loaded
        ring_startup_completed = True


# Xử lý lỗi HTTP thành JSON cho API
@app.errorhandler(HTTPException)
def handle_http_error(exc: HTTPException):
    if request.path.startswith("/api/"):
        return json_error(exc.description or exc.name, exc.code or 500)
    return exc

# Xử lý lỗi bất ngờ thành JSON cho API
@app.errorhandler(Exception)
def handle_unexpected_error(exc: Exception):
    if request.path.startswith("/api/"):
        return json_error(str(exc) or "Internal server error", 500)
    raise exc

# Hiển thị giao diện chính
@app.get("/")
def index():
    return render_template("index.html")


# Trả về snapshot trạng thái ring hiện tại
@app.get("/api/state")
def state():
    with coordinator_lock:
        _autoload_once()
        return jsonify({"ok": True, "state": ring.summary(sample_size=None)})

# Trả về toàn bộ resource đang được ring quản lý
@app.get("/api/resources")
def list_resources():
    with coordinator_lock:
        _autoload_once()
        summary = ring.summary(sample_size=None)
    return jsonify({"ok": True, "count": summary["resource_count"], "resources": summary["sample_resources"]})

# Trả về chi tiết một node theo node_id
@app.get("/api/node/<int:node_id>")
def node_details(node_id: int):
    with coordinator_lock:
        _autoload_once()
        return jsonify({"ok": True, "node": ring.node_details(node_id)})

# Khởi tạo lại ring theo cấu hình từ request
@app.post("/api/initialize")
def initialize_network():
    # Đọc payload JSON từ request khởi tạo
    payload = request.get_json(silent=True) or {}
    try:
        with coordinator_lock:
            # Đảm bảo state đã được autoload trước khi thay ring mới
            _autoload_once()

            # Đọc số node cần khởi tạo
            nodes = parse_int_field(payload, "nodes", 50)

            # Đọc số resource cần phân phối ban đầu
            resources = parse_int_field(payload, "resources", 1000)

            # Đọc số bit không gian định danh
            m = parse_int_field(payload, "m", 16)

            # Đọc seed để tạo topology có thể tái lập
            seed = parse_int_field(payload, "seed", 61)

            # Đọc số replica cần lưu cho mỗi resource
            replication_count = parse_int_field(payload, "replication_count", 1)

            global ring
            # Tạo ring mới rồi persist state và dataset ban đầu
            ring = ChordRing(m=m, seed=seed, replication_count=replication_count)

            # Khởi tạo node, resource và finger table cho ring mới
            state_payload = ring.initialize_network(
                node_count=nodes,
                resource_count=resources,
                seed=seed,
                replication_count=replication_count,
            )

            # Lưu snapshot state để lần mở sau có thể khôi phục
            _save_ring_state(ring)

            # Lưu file dataset node/resource ban đầu cho báo cáo và kiểm thử
            _save_initial_dataset_files(ring)

        # Trả về state mới cho frontend render lại toàn bộ UI
        return jsonify({"ok": True, "message": "Chord ring initialized and persisted to JSON.", "state": state_payload})
    except Exception as exc:
        return json_error(str(exc))

# Tra cứu resource qua Chord routing và trả về metric của lần lookup
@app.post("/api/lookup")
def lookup_resource():
    # Đọc payload JSON từ request lookup
    payload = request.get_json(silent=True) or {}

    # Chuẩn hóa resource_id người dùng nhập
    resource_id = str(payload.get("resource_id", "")).strip()

    # Kiểm tra resource_id bắt buộc trước khi lookup
    if not resource_id:
        return json_error("resource_id is required")

    # Đọc node bắt đầu nếu frontend có truyền
    start_node_id = payload.get("start_node_id")
    try:
        with coordinator_lock:
            # Đảm bảo ring đã được nạp trước khi lookup
            _autoload_once()
            pending_recovery = _require_no_pending_recovery()
            if pending_recovery is not None:
                return pending_recovery

            # Chuẩn hóa start_node_id rỗng thành None
            start = None if start_node_id in (None, "") else int(start_node_id)

            # Thực hiện lookup qua overlay Chord
            result_obj = ring.lookup(resource_id, start_node_id=start)

            # Chuyển kết quả lookup sang dict để jsonify
            result = result_obj.to_dict() if hasattr(result_obj, "to_dict") else result_obj

            # Lấy snapshot mới sau lookup
            state_payload = ring.summary(sample_size=None)

            # Persist state sau lookup để giữ log/metadata mới nhất
            _save_ring_state(ring)

        # Tạo metric nhanh cho lần lookup vừa chạy để frontend cập nhật tức thời
        hops = int(result["hops"])
        node_count = int(state_payload["active_node_count"])
        metric = {
            "nodes": node_count,
            "log2_nodes": round(math.log2(max(1, node_count)), 3),
            "attempted_lookups": 1,
            "total_lookups": 1,
            "successful_lookups": 1,
            "failed_lookups": 0,
            "success_rate": 1,
            "average_hops": hops,
            "max_hops": hops,
            "average_latency_ms": 0.0,
            "message_overhead": hops,
            "messages_per_lookup": hops,
        }

        return jsonify({"ok": True, "message": "Lookup completed.", "result": result, "lookup_metric": metric})
    except Exception as exc:
        return json_error(str(exc))

# Dừng một node để mô phỏng lỗi và persist trạng thái mới
@app.post("/api/kill")
def kill_node():
    # Đọc payload JSON từ request stop node
    payload = request.get_json(silent=True) or {}
    try:
        with coordinator_lock:
            # Đảm bảo ring đã được nạp trước khi kill node
            _autoload_once()
            pending_recovery = _require_no_pending_recovery()
            if pending_recovery is not None:
                return pending_recovery

            # Đọc node_id bắt buộc từ payload
            node_id = parse_int_field(payload, "node_id")

            # Mô phỏng lỗi node và chạy recovery dữ liệu
            report = ring.mark_node_failed(node_id)

            # Persist state sau khi node bị dừng
            _save_ring_state(ring)

        # Trả về report recovery và state mới cho frontend
        return jsonify({
            "ok": True,
            "message": report.get("message", "Node marked as failed."),
            "report": report,
            "state": ring.summary(sample_size=None),
        })
    except Exception as exc:
        return json_error(str(exc))

# Xóa một node khỏi ring sau khi vô hiệu hóa nếu còn active
@app.post("/api/recover")
def recover_node():
    payload = request.get_json(silent=True) or {}
    try:
        with coordinator_lock:
            _autoload_once()
            node_id = parse_int_field(payload, "node_id")
            report = ring.recover_failed_node(node_id)
            _save_ring_state(ring)

        return jsonify({
            "ok": True,
            "message": report.get("message", "Node recovered."),
            "report": report,
            "state": ring.summary(sample_size=None),
        })
    except Exception as exc:
        return json_error(str(exc))

@app.delete("/api/node/<int:node_id>")
def delete_node(node_id: int):
    try:
        with coordinator_lock:
            # Đảm bảo ring đã được nạp trước khi xóa node
            _autoload_once()
            pending_recovery = _require_no_pending_recovery()
            if pending_recovery is not None:
                return pending_recovery

            # Kiểm tra node tồn tại trước khi xóa
            if node_id not in ring.nodes:
                return json_error(f"Node {node_id} does not exist", 404)

            # Dừng node đang chạy để kích hoạt recovery trước khi xóa khỏi metadata
            if ring.nodes[node_id].active:
                ring.kill_node(node_id)

            # Xóa node khỏi metadata mô phỏng
            del ring.nodes[node_id]

            # Loại node khỏi tập failed_nodes nếu có
            ring.failed_nodes.discard(node_id)

            # Cho ring hội tụ lại sau khi xóa node
            ring.stabilize()

            # Persist state sau khi xóa node
            _save_ring_state(ring)

        # Trả về state mới sau khi xóa node
        return jsonify({
            "ok": True,
            "message": f"Node {node_id} deleted.",
            "state": ring.summary(sample_size=None),
        })
    except Exception as exc:
        return json_error(str(exc))

# Thêm node mới hoặc kích hoạt lại node đã dừng
@app.post("/api/node")
def add_node():
    # Đọc payload JSON từ request thêm node
    payload = request.get_json(silent=True) or {}
    try:
        with coordinator_lock:
            # Đảm bảo ring đã được nạp trước khi thêm node
            _autoload_once()
            pending_recovery = _require_no_pending_recovery()
            if pending_recovery is not None:
                return pending_recovery

            # Đọc node_id tùy chọn từ payload
            node_id = payload.get("node_id")

            # Thêm node tự động hoặc theo ID người dùng nhập
            report = ring.add_node(node_id=None if node_id in (None, "") else int(node_id))

            # Persist state sau khi node join ring
            _save_ring_state(ring)

        # Trả về report join và state mới
        return jsonify({
            "ok": True,
            "message": report.get("message", "Node added."),
            "report": report,
            "state": ring.summary(sample_size=None),
        })
    except Exception as exc:
        return json_error(str(exc))

# Thêm resource mới vào ring và trả về trace định tuyến put
@app.post("/api/resource")
def add_resource():
    # Đọc payload JSON từ request thêm resource
    payload = request.get_json(silent=True) or {}

    # Chuẩn hóa resource_id người dùng nhập
    resource_id = str(payload.get("resource_id", "")).strip()

    # Kiểm tra resource_id bắt buộc trước khi ghi resource
    if not resource_id:
        return json_error("resource_id is required")
    try:
        with coordinator_lock:
            # Đảm bảo ring đã được nạp trước khi thêm resource
            _autoload_once()
            pending_recovery = _require_no_pending_recovery()
            if pending_recovery is not None:
                return pending_recovery

            # Put resource qua routing Chord để tìm owner
            created = ring.add_resource(resource_id)

            # Persist state sau khi ghi resource
            _save_ring_state(ring)

        # Trả về resource mới, state và trace put
        return jsonify({
            "ok": True,
            "message": created.get("message", "Resource stored."),
            "resource": created.get("resource"),
            "state": ring.summary(sample_size=None),
            "trace": {
                "path": created.get("put_path"),
                "hops": created.get("put_hops"),
                "logs": created.get("put_logs"),
            },
        })
    except Exception as exc:
        return json_error(str(exc))

# Đổi resource_id bằng cách xóa bản cũ và put bản mới qua Chord
@app.put("/api/resource")
def update_resource():
    # Đọc payload JSON từ request cập nhật resource
    payload = request.get_json(silent=True) or {}

    # Chuẩn hóa ID resource cũ
    old_id = str(payload.get("old_resource_id", "")).strip()

    # Chuẩn hóa ID resource mới
    new_id = str(payload.get("new_resource_id", "")).strip()

    # Kiểm tra cả ID cũ và ID mới đều bắt buộc
    if not old_id or not new_id:
        return json_error("old_resource_id and new_resource_id are required")
    try:
        with coordinator_lock:
            # Đảm bảo ring đã được nạp trước khi cập nhật resource
            _autoload_once()
            pending_recovery = _require_no_pending_recovery()
            if pending_recovery is not None:
                return pending_recovery

            # Cập nhật resource bằng delete và put phân tán
            updated = ring.update_resource(old_id, new_id)

            # Persist state sau khi đổi resource_id
            _save_ring_state(ring)

        # Trả về resource mới, state và trace put
        return jsonify({
            "ok": True,
            "message": updated.get("message", "Resource updated."),
            "resource": updated.get("resource"),
            "state": ring.summary(sample_size=None),
            "trace": {
                "path": updated.get("put_path"),
                "hops": updated.get("put_hops"),
                "logs": updated.get("put_logs"),
            },
        })
    except Exception as exc:
        return json_error(str(exc))

# Xóa resource khỏi owner và các replica liên quan
@app.delete("/api/resource")
def delete_resource():
    # Đọc payload JSON từ request xóa resource
    payload = request.get_json(silent=True) or {}

    # Chuẩn hóa resource_id cần xóa
    resource_id = str(payload.get("resource_id", "")).strip()

    # Kiểm tra resource_id bắt buộc trước khi xóa
    if not resource_id:
        return json_error("resource_id is required")
    try:
        with coordinator_lock:
            # Đảm bảo ring đã được nạp trước khi xóa resource
            _autoload_once()
            pending_recovery = _require_no_pending_recovery()
            if pending_recovery is not None:
                return pending_recovery

            # Delete resource qua routing Chord tới owner hiện tại
            deleted = ring.delete_resource(resource_id)

            # Persist state sau khi xóa resource
            _save_ring_state(ring)

        # Trả về state mới và trace delete
        return jsonify({
            "ok": True,
            "message": deleted.get("message", "Resource deleted."),
            "removed": True,
            "resource": deleted.get("resource"),
            "state": ring.summary(sample_size=None),
            "trace": {
                "path": deleted.get("delete_path"),
                "hops": deleted.get("delete_hops"),
                "logs": deleted.get("delete_logs"),
            },
        })
    except Exception as exc:
        return json_error(str(exc))

# Chặn GET metrics để tránh chạy benchmark ngoài ý muốn
@app.get("/api/metrics")
def metrics_requires_post():
    return json_error("Metrics must be run with POST. Use the Run Metrics button on the UI.", 405)

# Chạy benchmark lookup trên ring hiện tại và sweep tăng trưởng
@app.post("/api/metrics")
def metrics_current_ring():
    # Đọc payload JSON chứa tham số chạy benchmark
    payload = request.get_json(silent=True) or {}
    try:
        # Chuẩn hóa số trial benchmark từ payload
        trials = parse_int_field(payload, "trials", 5)

        # Chuẩn hóa số lookup trong mỗi trial từ payload
        lookups = parse_int_field(payload, "lookups", 100)

        # Sinh seed metric mới mỗi lần chạy nếu người dùng không truyền metric_seed
        metric_seed = parse_int_field(payload, "metric_seed", time.time_ns())

        with coordinator_lock:
            # Đảm bảo ring đã được nạp trước khi chạy metric
            _autoload_once()
            pending_recovery = _require_no_pending_recovery()
            if pending_recovery is not None:
                return pending_recovery

            # Lấy resource thật từ local storage của các node active cho benchmark
            live_resources = list(ring._unique_active_local_resources().values())

            # Lấy số resource hiện có để dùng lại cho sweep tăng trưởng
            resource_count = len(live_resources) or 1000

            # Sao chép bản ghi resource để benchmark không phụ thuộc mutation trực tiếp
            resource_records = live_resources

            # Ghi nhận danh sách node hiện tại làm nguồn cho ring metric
            metric_node_ids = ring.active_node_ids

            # Lưu cấu hình không gian định danh của ring hiện tại
            m = ring.m

            # Lưu số bản sao resource để sweep giữ đúng cấu hình ring
            replication_count = ring.replication_count

            # Đếm số node active theo summary đầy đủ của ring
            active_nodes = int(ring.summary(sample_size=None).get("active_node_count", 0) or 0)

            # Trả về payload rỗng khi chưa có node active để đo metric
            if active_nodes < 1:
                return jsonify({
                    "ok": False,
                    "message": "No active nodes. Please initialize the ring first.",
                    "sweep_points": [],
                    "charts": {},
                })

            # Chạy metric trên ring hiện tại trước để dùng làm điểm cuối của sweep
            current_result = run_current_ring_metrics(
                ring,
                trial_count=trials,
                lookups_per_trial=lookups,
                seed=metric_seed,
                output_path=None,
            )

            # Lấy điểm metric của ring hiện tại
            current_point = current_result["points"][0]

        # Sinh sweep và biểu đồ trong lock riêng để matplotlib không chạy song song
        with plot_lock:
            # Tạo danh sách kích thước node từ 1 tới số node active hiện tại
            node_sizes = build_growth_node_sizes(active_nodes, row_limit=50)

            # Chạy benchmark tăng trưởng bằng dữ liệu sao chép từ ring hiện tại
            sweep_result = run_lookup_metrics(
                max_node_count=active_nodes,
                node_sizes=node_sizes,
                trial_count=trials,
                lookups_per_size=lookups,
                resource_count=resource_count,
                resource_records=resource_records,
                node_ids=metric_node_ids,
                replication_count=replication_count,
                m=m,
                seed=metric_seed,
                fixed_points={active_nodes: current_point},
                output_path=None,
            )

            # Lấy toàn bộ điểm metric sau khi sweep hoàn tất
            sweep_points = sweep_result["points"]

            # Lưu các biểu đồ metric từ danh sách điểm đã tính
            charts = save_metric_charts_from_points(sweep_points)

        # Đóng gói payload trả về cho frontend
        response_payload = {
            "ok": True,
            "message": "Metrics completed successfully.",
            "metric_seed": metric_seed,
            "sweep_points": sweep_points,
            "node_counts": [int(p["nodes"]) for p in sweep_points],
            "charts": charts,
        }

        global last_metrics_payload
        # Lưu metric gần nhất để frontend có thể khôi phục sau refresh
        last_metrics_payload = {
            "saved_at": time.time(),
            "trials": trials,
            "lookups": lookups,
            "metric_seed": metric_seed,
            "active_nodes": active_nodes,
            "sweep_points": response_payload["sweep_points"],
            "charts": response_payload["charts"],
        }
        with coordinator_lock:
            # Đảm bảo state mới nhất vẫn được nạp trước khi persist
            _autoload_once()

            # Persist ring state sau khi chạy metric
            _save_ring_state(ring)

        # Trả về kết quả benchmark và đường dẫn biểu đồ
        return jsonify(response_payload)
    except Exception as exc:
        return json_error(str(exc))

# Trả về metric đã lưu từ lần chạy gần nhất
@app.get("/api/metrics/last")
def metrics_last():
    with coordinator_lock:
        # Đảm bảo ring/state đã được nạp trước khi trả metric cache
        _autoload_once()

        # Trả về thông báo khi chưa từng chạy metric
        if last_metrics_payload is None:
            return jsonify({"ok": False, "message": "No saved metrics yet."})

        # Trả về metric đã lưu từ lần chạy gần nhất
        return jsonify({"ok": True, "metrics": last_metrics_payload})

# Sinh ảnh topology graph và tùy chọn highlight đường lookup
@app.post("/api/topology")
def topology():
    # Đọc payload JSON chứa tùy chọn highlight lookup path
    payload = request.get_json(silent=True) or {}

    # Xác định frontend có yêu cầu vẽ lại đường lookup gần nhất hay không
    include_last_path = bool(payload.get("include_last_path", False))
    try:
        with coordinator_lock:
            # Đảm bảo ring đã được nạp trước khi sinh topology
            _autoload_once()

            # Khởi tạo đường lookup mặc định không highlight
            lookup_path = None

            # Chuẩn hóa lookup_path khi frontend yêu cầu highlight đường đi
            if include_last_path:
                lookup_path = payload.get("lookup_path")

                # Chuyển từng node_id trong lookup_path sang số nguyên
                if isinstance(lookup_path, list):
                    lookup_path = [int(x) for x in lookup_path]
                else:
                    # Bỏ lookup_path không hợp lệ để vẫn sinh topology thường
                    lookup_path = None

            with plot_lock:
                # Sinh ảnh topology với hoặc không có đường lookup được highlight
                report = save_topology_graph(
                    ring,
                    TOPOLOGY_CHART_PATH,
                    lookup_path=lookup_path,
                    title="Chord Ring Topology",
                )

        # Trả về metadata ảnh topology và URL chống cache
        return jsonify({
            "ok": True,
            "message": "Topology graph generated.",
            "report": report,
            "chart_url": f"/static/metrics/{TOPOLOGY_CHART_PATH.name}?_={time.time_ns()}",
        })
    except Exception as exc:
        return json_error(str(exc))

# Khởi chạy Flask server khi chạy trực tiếp app.py
if __name__ == "__main__":
    # Thử autoload state trước khi nhận request đầu tiên
    try:
        _autoload_once()
    except Exception as exc:
        logging.warning(f"Startup auto-load failed (continuing anyway): {exc}")

    # Đọc host từ biến môi trường hoặc dùng localhost mặc định
    host = os.environ.get("HOST", "127.0.0.1")

    # Đọc port từ biến môi trường hoặc dùng cổng Flask mặc định
    port = int(os.environ.get("PORT", "5000"))

    # Chạy Flask server ở chế độ không debug
    app.run(host=host, port=port, debug=False)
