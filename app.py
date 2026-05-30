# Cung cap giao dien web de mo phong Chord DHT trong mot process.
# Mo phong toan bo node trong bo nho cua Flask server.
# Luu tru trai thai co ban vao `data/state.json` theo co che best effort.
# Ghi nhan loi thuat toan tai `chord_dht.chord.ChordRing`.
# Ghi nhan metrics va topology tai `chord_dht.metrics` va `chord_dht.visualization`.

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

PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from chord_dht import (
    ChordRing,
    build_growth_node_sizes,
    run_current_ring_metrics,
    run_lookup_metrics,
    save_topology_graph,
)


# Cau hinh logging de hien thi thoi gian, muc do, ten logger, va noi dung.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

# Tao ung dung Flask de phuc vu cac API endpoint va giao dien web.
app = Flask(__name__)
# Tat cache tren tat ca cac file tinh (CSS, JS, hinh anh) de dam bao luon lay ban moi nhat.
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0

# Khoa dong bo de bao ve ring state khi nhieu request UI thay doi dong thoi.
coordinator_lock = Lock()

# Khoa dong bo de bao ve thao tac Matplotlib, ngan chan cac endpoint ghi chong lenh nhau khi tao anh.
plot_lock = Lock()

# Duong dan luu tru anh topology va cac bieu do metrics.
TOPOLOGY_CHART_PATH = PROJECT_ROOT / "static" / "metrics" / "topology_graph.png"
METRICS_CHART_BASE = PROJECT_ROOT / "static" / "metrics" / "hops_chart"

# Duong dan file luu tru trai thai ring (nodes, resources, metrics) duoi dang JSON.
STATE_PATH = PROJECT_ROOT / "data" / "state.json"


# ==================== Luu va tai lai trai thai (best-effort) ====================

# Chuyen doi trai thai ring thanh dictionary de ghi vao file JSON.
# Chi luu tru cac truong co ban: cau hinh, danh sach node, danh sach resource, va metrics cuoi cung.
# Finger table, successor, predecessor se duoc xay dung lai boi stabilize() khi tai.
def _ring_state_to_json(ring: ChordRing) -> dict[str, Any]:
    # Doc last_metrics_payload truc tiep tu module-level global (khong dung globals()).
    # Vi ham nay la nested function nen khong doc duoc global cua module cha.
    global last_metrics_payload
    return {
        "schema_version": 1,
        "saved_at": time.time(),
        "config": {
            "m": ring.m,
            "seed": ring.seed,
            "replication_count": ring.replication_count,
        },
        "nodes": [
            {"node_id": node.node_id, "active": bool(node.active)}
            for node in ring.nodes.values()
        ],
        "resources": sorted(list(ring.resources.keys())),
        "metrics": last_metrics_payload,
    }


# Khoi phuc trai thai ring tu dictionary da doc tu file JSON.
# Tao lai toan bo ring, cac lien ket successor/predecessor, finger table, va resource ownership.
def _ring_state_from_json(payload: dict[str, Any]) -> ChordRing:
    # Tai lai metrics payload neu co trong JSON.
    global last_metrics_payload
    metrics_payload = payload.get("metrics")
    last_metrics_payload = metrics_payload if isinstance(metrics_payload, dict) else None

    # Doc cau hinh tu payload.
    config = payload.get("config") or {}
    m = int(config.get("m", 16))
    seed = int(config.get("seed", 61))
    replication_count = int(config.get("replication_count", 3))

    # Tao ring moi voi cau hinh tuong ung.
    ring = ChordRing(m=m, seed=seed, replication_count=replication_count)

    # Khoi phuc danh sach node.
    nodes_payload = payload.get("nodes") or []
    for node_info in nodes_payload:
        node_id = int(node_info["node_id"])
        ring.nodes[node_id] = ring.nodes.get(node_id) or __import__("chord_dht.models", fromlist=["Node"]).Node(node_id=node_id)
        ring.nodes[node_id].active = bool(node_info.get("active", True))
        if not ring.nodes[node_id].active:
            ring.failed_nodes.add(node_id)

    # Noi truoc successor/predecessor pointers theo thu tu circular.
    # Sau khi khoi phuc, tat ca cac node deu co successor=None, predecessor=None.
    # Neu goi stabilize() ngay luc nay, moi node se tu tham chieu chinh no (self-referential),
    # lam vong bi tach ra nhieu vong don le. Viec noi truoc cac pointer dam bao
    # stabilize() co the tinh chinh thay vi phai xay dung lai tu dau.
    active_ids = ring.active_node_ids
    active_count = len(active_ids)
    if active_count > 0:
        for i, node_id in enumerate(active_ids):
            ring.nodes[node_id].successor = active_ids[(i + 1) % active_count]
            ring.nodes[node_id].predecessor = active_ids[(i - 1) % active_count]

    # Goi stabilize() de tinh chinh cac lien ket va xay dung finger tables.
    ring.stabilize()

    # Khoi phuc danh sach resource (re-hash theo id).
    for resource_id in payload.get("resources") or []:
        rid = str(resource_id).strip()
        if not rid:
            continue
        if rid in ring.resources:
            continue
        ring.add_resource(rid)

    # Goi stabilize() lan nua sau khi khoi phuc resource
    # de dam bao resource duoc gan dung cho cac owner hien tai.
    ring.stabilize()

    return ring


# Ghi trai thai ring hien tai vao file JSON.
# Su dung che do ghi tam tep roi doi ten de dam bao tinh nguyen tu tren Windows.
def _save_ring_state(ring: ChordRing) -> None:
    import json

    # Dam bao thu muc cha ton tai.
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    # Tao ten tep tam chua PID va timestamp de tranh xung dot khi nhieu tien trinh chay dong thoi.
    tmp = STATE_PATH.with_suffix(f".json.tmp-{os.getpid()}-{time.time_ns()}")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(_ring_state_to_json(ring), f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    # Thu lai doi ten tren Windows khi bi loi PermissionError (file dang bi chiem).
    last_exc: OSError | None = None
    for attempt in range(8):
        try:
            tmp.replace(STATE_PATH)
            return
        except PermissionError as exc:
            last_exc = exc
            time.sleep(0.05 * (attempt + 1))
    try:
        if tmp.exists():
            tmp.unlink()
    except OSError:
        pass
    if last_exc is not None:
        raise last_exc


# Doc va khoi phuc trai thai ring tu file JSON neu tep ton tai.
def _load_ring_state() -> ChordRing | None:
    import json

    if not STATE_PATH.exists():
        return None
    with STATE_PATH.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    if not isinstance(payload, dict):
        return None
    return _ring_state_from_json(payload)


# ==================== Bien toan cuc ====================

# Ring instance mac dinh, duoc khoi tao khi module duoc nap.
ring = ChordRing(m=16, seed=61, replication_count=3)
# Co hieu de danh dau trang thai khoi dong da hoan thanh (nghia la da thu tai file JSON).
ring_startup_completed = False
startup_lock = Lock()

# Payload metrics duoc luu tru best-effort vao state.json.
# Gianh cho viec khoi phuc metrics khi app khoi dong lai.
last_metrics_payload: dict[str, Any] | None = None


# ==================== Ham tro giup ====================

# Tao phan hoi loi theo dinh dang JSON cho cac API endpoint.
def json_error(message: str, status_code: int = 400):
    response = jsonify({"ok": False, "message": message})
    response.status_code = status_code
    return response


# Trich xuat gia tri so nguyen tu payload JSON, nem loi neu truong bi thieu hoac khong hop le.
def parse_int_field(payload: dict[str, Any], field: str, default: int | None = None) -> int:
    raw_value = payload.get(field, default)
    if raw_value is None or raw_value == "":
        raise ValueError(f"{field} is required")
    return int(raw_value)


# Tao ba bieu do duong (hops, latency, overhead) tu danh sach cac diem sweep metrics.
# Luu cac anh PNG voi ten chua timestamp de tranh browser su dung cache cu.
def save_metric_charts_from_points(points: list[dict[str, Any]]) -> dict[str, str]:
    # Dam bao thu muc luu anh ton tai.
    METRICS_CHART_BASE.parent.mkdir(parents=True, exist_ok=True)
    urls: dict[str, str] = {}

    # Them timestamp vao ten tep de bua browser cache.
    ts = time.time_ns()

    # Trich xuat du lieu tu danh sach diem.
    node_counts = [int(p["nodes"]) for p in points]
    average_hops = [float(p["average_hops"]) for p in points]
    log_values = [float(p["log2_nodes"]) for p in points]
    average_latencies = [float(p["average_latency_ms"]) for p in points]
    messages_per_lookup = [float(p["messages_per_lookup"]) for p in points]

    # Tao bieu do so sanh average hops voi gioi han ly thuyet log2(N).
    hops_path = METRICS_CHART_BASE.with_name(f"{METRICS_CHART_BASE.name}_sweep_hops_{ts}.png")
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
    urls["hops"] = f"/static/metrics/{hops_path.name}"

    # Tao bieu do do tre trung binh theo so luong node.
    latency_path = METRICS_CHART_BASE.with_name(f"{METRICS_CHART_BASE.name}_sweep_latency_{ts}.png")
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
    urls["latency"] = f"/static/metrics/{latency_path.name}"

    # Tao bieu do so tin hieu chuan (messages per lookup) theo so luong node.
    overhead_path = METRICS_CHART_BASE.with_name(f"{METRICS_CHART_BASE.name}_sweep_overhead_{ts}.png")
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
    urls["overhead"] = f"/static/metrics/{overhead_path.name}"

    return urls


# Tao ba bieu do tu mot diem duy nhat (che do cu, con su dung cho tuong thich nguoc).
def save_metric_charts(point: dict[str, Any]) -> dict[str, str]:
    return save_metric_charts_from_points([point])


# Tai file state.json mot lan duy nhat khi app khoi dong.
# Su dung startup_lock de dam bao chi tai mot lan cho du nhieu thread goi dong thoi.
def _autoload_once() -> None:
    global ring_startup_completed, ring
    if ring_startup_completed:
        return
    with startup_lock:
        if ring_startup_completed:
            return
        loaded = None
        try:
            loaded = _load_ring_state()
        except Exception as exc:
            logging.warning(f"Auto-load state failed (continuing anyway): {exc}")
        if loaded is not None:
            ring = loaded
        ring_startup_completed = True


# ==================== Xu ly loi ====================

# Tra ve loi HTTP nhu binh thuong cho cac endpoint /api/.
@app.errorhandler(HTTPException)
def handle_http_error(exc: HTTPException):
    if request.path.startswith("/api/"):
        return json_error(exc.description or exc.name, exc.code or 500)
    return exc


# Log loi khong mong muon va tra ve JSON error cho cac endpoint /api/.
@app.errorhandler(Exception)
def handle_unexpected_error(exc: Exception):
    if request.path.startswith("/api/"):
        return json_error(str(exc) or "Internal server error", 500)
    raise exc


# ==================== Cac endpoint API ====================

# Tra ve trang giao dien chinh (index.html).
@app.get("/")
def index():
    return render_template("index.html")


# Tra ve tom tat trai thai hien tai cua ring (nodes, resources, failed_nodes).
@app.get("/api/state")
def state():
    with coordinator_lock:
        _autoload_once()
        return jsonify({"ok": True, "state": ring.summary(sample_size=None)})


# Tra ve danh sach resource (tom tat, gioi han 200 mau).
@app.get("/api/resources")
def list_resources():
    with coordinator_lock:
        _autoload_once()
        summary = ring.summary(sample_size=200)
    return jsonify({"ok": True, "count": summary["resource_count"], "resources": summary["sample_resources"]})


# Tra ve chi tiet mot node: thong tin co ban, finger table, va danh sach resource cuc bo.
@app.get("/api/node/<int:node_id>")
def node_details(node_id: int):
    with coordinator_lock:
        _autoload_once()
        return jsonify({"ok": True, "node": ring.node_details(node_id)})


# Khoi tao ring moi: tao node, phan bo resource, tao replica, va luu vao JSON.
@app.post("/api/initialize")
def initialize_network():
    payload = request.get_json(silent=True) or {}
    try:
        with coordinator_lock:
            _autoload_once()
            nodes = parse_int_field(payload, "nodes", 50)
            resources = parse_int_field(payload, "resources", 1000)
            m = parse_int_field(payload, "m", 16)
            seed = parse_int_field(payload, "seed", 61)
            replication_count = parse_int_field(payload, "replication_count", 3)

            global ring
            ring = ChordRing(m=m, seed=seed, replication_count=replication_count)
            state_payload = ring.initialize_network(node_count=nodes, resource_count=resources, seed=seed, replication_count=replication_count)
            _save_ring_state(ring)

        return jsonify({"ok": True, "message": "Chord ring initialized and persisted to JSON.", "state": state_payload})
    except Exception as exc:
        return json_error(str(exc))


# Tim owner cua mot resource theo Chord DHT algorithm.
# Tra ve duong di hops, node cuoi cung, va chi tiet tung buoc nhay.
@app.post("/api/lookup")
def lookup_resource():
    payload = request.get_json(silent=True) or {}
    resource_id = str(payload.get("resource_id", "")).strip()
    if not resource_id:
        return json_error("resource_id is required")
    start_node_id = payload.get("start_node_id")
    try:
        with coordinator_lock:
            _autoload_once()
            start = None if start_node_id in (None, "") else int(start_node_id)
            result_obj = ring.lookup(resource_id, start_node_id=start)
            # ring.lookup tra ve LookupResult dataclass, chuyen doi thanh dict neu can.
            result = result_obj.to_dict() if hasattr(result_obj, "to_dict") else result_obj
            state_payload = ring.summary(sample_size=None)
            _save_ring_state(ring)

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


# Danh dau mot node la da dung (kill) va kich hoat quy trinh phuc hoi.
# Noi vong Chord, sua finger tables, va promote replica cho cac resource bi anh huong.
@app.post("/api/kill")
def kill_node():
    payload = request.get_json(silent=True) or {}
    try:
        with coordinator_lock:
            _autoload_once()
            node_id = parse_int_field(payload, "node_id")
            report = ring.kill_node(node_id)
            _save_ring_state(ring)
        return jsonify({"ok": True, "message": report.get("message", "Node killed."), "report": report, "state": ring.summary(sample_size=None)})
    except Exception as exc:
        return json_error(str(exc))




# Xoa vinh vien mot node khoi ring.
# Kill node truoc khi xoa khi node van con active.
# Goi stabilize() sau khi xoa de hoi tu lai topology.
@app.delete("/api/node/<int:node_id>")
def delete_node(node_id: int):
    try:
        with coordinator_lock:
            _autoload_once()
            if node_id not in ring.nodes:
                return json_error(f"Node {node_id} does not exist", 404)

            if ring.nodes[node_id].active:
                ring.kill_node(node_id)

            del ring.nodes[node_id]
            ring.failed_nodes.discard(node_id)
            ring.stabilize()
            _save_ring_state(ring)

        return jsonify({
            "ok": True,
            "message": f"Node {node_id} deleted.",
            "state": ring.summary(sample_size=None),
        })
    except Exception as exc:
        return json_error(str(exc))

    payload = request.get_json(silent=True) or {}
    try:
        with coordinator_lock:
            _autoload_once()
            node_id = payload.get("node_id")
            report = ring.add_node(node_id=None if node_id in (None, "") else int(node_id))
            _save_ring_state(ring)
        return jsonify({"ok": True, "message": report.get("message", "Node added."), "report": report, "state": ring.summary(sample_size=None)})
    except Exception as exc:
        return json_error(str(exc))


# Khong ho tro restart node trong che do mo phong don process.
@app.post("/api/node/<int:node_id>/restart")
def restart_node(node_id: int):
    return json_error("Restart is not supported. Use /api/node to join a new node.", 400)


# Them mot resource moi vao ring: tinh key, tim owner, luu va copy replica.
@app.post("/api/resource")
def add_resource():
    payload = request.get_json(silent=True) or {}
    resource_id = str(payload.get("resource_id", "")).strip()
    if not resource_id:
        return json_error("resource_id is required")
    try:
        with coordinator_lock:
            _autoload_once()
            created = ring.add_resource(resource_id)
            _save_ring_state(ring)
        return jsonify({"ok": True, "message": created.get("message", "Resource stored."), "resource": created.get("resource"), "state": ring.summary(sample_size=None), "trace": {"path": created.get("put_path"), "hops": created.get("put_hops"), "logs": created.get("put_logs")}})
    except Exception as exc:
        return json_error(str(exc))


# Cap nhat resource: xoa ban cu, them ban moi, sao chep replica.
@app.put("/api/resource")
def update_resource():
    payload = request.get_json(silent=True) or {}
    old_id = str(payload.get("old_resource_id", "")).strip()
    new_id = str(payload.get("new_resource_id", "")).strip()
    if not old_id or not new_id:
        return json_error("old_resource_id and new_resource_id are required")
    try:
        with coordinator_lock:
            _autoload_once()
            updated = ring.update_resource(old_id, new_id)
            _save_ring_state(ring)
        return jsonify({"ok": True, "message": updated.get("message", "Resource updated."), "resource": updated.get("resource"), "state": ring.summary(sample_size=None), "trace": {"path": updated.get("put_path"), "hops": updated.get("put_hops"), "logs": updated.get("put_logs")}})
    except Exception as exc:
        return json_error(str(exc))


# Xoa mot resource khoi ring: xoa khoi owner va tat ca replica.
@app.delete("/api/resource")
def delete_resource():
    payload = request.get_json(silent=True) or {}
    resource_id = str(payload.get("resource_id", "")).strip()
    if not resource_id:
        return json_error("resource_id is required")
    try:
        with coordinator_lock:
            _autoload_once()
            deleted = ring.delete_resource(resource_id)
            _save_ring_state(ring)
        return jsonify({"ok": True, "message": deleted.get("message", "Resource deleted."), "removed": True, "resource": deleted.get("resource"), "state": ring.summary(sample_size=None), "trace": {"path": deleted.get("delete_path"), "hops": deleted.get("delete_hops"), "logs": deleted.get("delete_logs")}})
    except Exception as exc:
        return json_error(str(exc))


# Chay benchmark lookup tren ring hien tai de thu thap metrics.
# Tra ve bang sweep (toi da 50 dong) va ba bieu do (hops, latency, overhead).
# Luu metrics vao state.json de khoi phuc khi app khoi dong lai.
@app.post("/api/metrics")
def metrics_current_ring():
    payload = request.get_json(silent=True) or {}
    try:
        trials = parse_int_field(payload, "trials", 5)
        lookups = parse_int_field(payload, "lookups", 100)

        with coordinator_lock:
            _autoload_once()
            resource_count = len(ring.resources) or 1000
            m = ring.m
            seed = ring.seed

        with plot_lock:
            # Tinh so dong trong bang sweep = min(so node active, 50).
            active_nodes = int(ring.summary(sample_size=None).get("active_node_count", 0) or 0)
            row_count = max(1, min(active_nodes, 50))
            node_sizes = build_growth_node_sizes(active_nodes, row_limit=row_count)
            sweep_result = run_lookup_metrics(
                max_node_count=active_nodes,
                node_sizes=node_sizes,
                trial_count=trials,
                lookups_per_size=lookups,
                resource_count=resource_count,
                m=m,
                seed=seed,
                output_path=None,
            )
            charts = save_metric_charts_from_points(sweep_result["points"])

        # Tao payload tra ve cho client.
        response_payload = {
            "ok": True,
            "message": "Metrics completed successfully.",
            "sweep_points": sweep_result["points"],
            "node_counts": [int(p["nodes"]) for p in sweep_result["points"]],
            "charts": charts,
        }

        # Luu metrics payload vao bien toan cuc de ghi vao state.json.
        global last_metrics_payload
        last_metrics_payload = {
            "saved_at": time.time(),
            "trials": trials,
            "lookups": lookups,
            "active_nodes": active_nodes,
            "sweep_points": response_payload["sweep_points"],
            "charts": response_payload["charts"],
        }
        with coordinator_lock:
            _autoload_once()
            _save_ring_state(ring)

        return jsonify(response_payload)
    except Exception as exc:
        return json_error(str(exc))


# Tra ve metrics da luu gan nhat tu lan chay truoc (neu co).
# Su dung de khoi phuc UI metrics khi app khoi dong lai ma khong can chay lai benchmark.
@app.get("/api/metrics/last")
def metrics_last():
    with coordinator_lock:
        _autoload_once()
        if last_metrics_payload is None:
            return jsonify({"ok": False, "message": "No saved metrics yet."})
        return jsonify({"ok": True, "metrics": last_metrics_payload})


# Chay benchmark sweep tuy chinh: cho phep dat so node, trials, lookups, resources, m, seed.
@app.post("/api/metrics/sweep")
def metrics_sweep():
    payload = request.get_json(silent=True) or {}
    try:
        max_nodes = parse_int_field(payload, "max_nodes", 50)
        trials = parse_int_field(payload, "trials", 5)
        lookups = parse_int_field(payload, "lookups", 100)
        resources = parse_int_field(payload, "resources", 1000)
        m = parse_int_field(payload, "m", 16)
        seed = parse_int_field(payload, "seed", 61)

        node_sizes = tuple(payload.get("node_sizes") or [])
        node_sizes = node_sizes if node_sizes else build_growth_node_sizes(max_nodes)

        with plot_lock:
            result = run_lookup_metrics(
                node_sizes=tuple(int(x) for x in node_sizes),
                max_node_count=max_nodes,
                trial_count=trials,
                lookups_per_size=lookups,
                resource_count=resources,
                m=m,
                seed=seed,
                output_path=None,
            )
            charts = save_metric_charts_from_points(result["points"])
        return jsonify({"ok": True, "message": result.get("message", "Sweep completed."), **result, "charts": charts})
    except Exception as exc:
        return json_error(str(exc))


# Tao anh topology graph cua ring hien tai.
# Ho tro highlight duong di lookup neu duoc cung cap.
@app.post("/api/topology")
def topology():
    payload = request.get_json(silent=True) or {}
    include_last_path = bool(payload.get("include_last_path", False))
    try:
        with coordinator_lock:
            _autoload_once()
            lookup_path = None
            if include_last_path:
                # Su dung duong di lookup gan nhat neu client cung cap.
                lookup_path = payload.get("lookup_path")
                if isinstance(lookup_path, list):
                    lookup_path = [int(x) for x in lookup_path]
                else:
                    lookup_path = None

            with plot_lock:
                report = save_topology_graph(
                    ring,
                    TOPOLOGY_CHART_PATH,
                    lookup_path=lookup_path,
                    title="Chord Ring Topology",
                )

        return jsonify({"ok": True, "message": "Topology graph generated.", "report": report, "chart_url": f"/static/metrics/{TOPOLOGY_CHART_PATH.name}?_={time.time_ns()}"})
    except Exception as exc:
        return json_error(str(exc))


if __name__ == "__main__":
    # Tai file state.json ngay khi khoi dong, truoc khi nhan request dau tien.
    try:
        _autoload_once()
    except Exception as exc:
        logging.warning(f"Startup auto-load failed (continuing anyway): {exc}")

    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "5000"))
    app.run(host=host, port=port, debug=False)
