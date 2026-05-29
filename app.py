"""Cung cấp giao diện web để mô phỏng Chord DHT (ChordRing) trong một process.

Single-process mode:
- Tất cả node nằm trong bộ nhớ của một Flask server
- Persist trạng thái cơ bản vào `data/state.json` (best-effort)

Ghi chú:
- Lõi thuật toán dùng `chord_dht.chord.ChordRing` (consistent hashing + finger table)
- Metrics + topology dùng `chord_dht.metrics` và `chord_dht.visualization`
"""

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


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

app = Flask(__name__)
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0

# Bảo vệ ring state khi nhiều request UI thay đổi đồng thời
coordinator_lock = Lock()

# Bảo vệ thao tác Matplotlib để các endpoint không ghi chồng file ảnh
plot_lock = Lock()

TOPOLOGY_CHART_PATH = PROJECT_ROOT / "static" / "metrics" / "topology_graph.png"
METRICS_CHART_BASE = PROJECT_ROOT / "static" / "metrics" / "hops_chart"

STATE_PATH = PROJECT_ROOT / "data" / "state.json"


# ---------------- persistence (best-effort) ----------------

def _ring_state_to_json(ring: ChordRing) -> dict[str, Any]:
    # Persist dữ liệu đủ để khôi phục lại topology + resources.
    # Finger table / successor / predecessor sẽ được dựng lại bởi stabilize().
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
    }


def _ring_state_from_json(payload: dict[str, Any]) -> ChordRing:
    config = payload.get("config") or {}
    m = int(config.get("m", 16))
    seed = int(config.get("seed", 61))
    replication_count = int(config.get("replication_count", 3))

    ring = ChordRing(m=m, seed=seed, replication_count=replication_count)

    # Restore nodes
    nodes_payload = payload.get("nodes") or []
    for node_info in nodes_payload:
        node_id = int(node_info["node_id"])
        ring.nodes[node_id] = ring.nodes.get(node_id) or __import__("chord_dht.models", fromlist=["Node"]).Node(node_id=node_id)
        ring.nodes[node_id].active = bool(node_info.get("active", True))
        if not ring.nodes[node_id].active:
            ring.failed_nodes.add(node_id)

    # Stabilize to build links + fingers
    ring.stabilize()

    # Restore resources (re-hash by id)
    for resource_id in payload.get("resources") or []:
        rid = str(resource_id).strip()
        if not rid:
            continue
        if rid in ring.resources:
            continue
        ring.add_resource(rid)

    return ring


def _save_ring_state(ring: ChordRing) -> None:
    import json

    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(f".json.tmp-{os.getpid()}-{time.time_ns()}")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(_ring_state_to_json(ring), f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    # Windows-friendly replace retries
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


def _load_ring_state() -> ChordRing | None:
    import json

    if not STATE_PATH.exists():
        return None
    with STATE_PATH.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    if not isinstance(payload, dict):
        return None
    return _ring_state_from_json(payload)


# Global ring instance
ring = ChordRing(m=16, seed=61, replication_count=3)
ring_startup_completed = False
startup_lock = Lock()


# ---------------- helpers ----------------

def json_error(message: str, status_code: int = 400):
    response = jsonify({"ok": False, "message": message})
    response.status_code = status_code
    return response


def parse_int_field(payload: dict[str, Any], field: str, default: int | None = None) -> int:
    raw_value = payload.get(field, default)
    if raw_value is None or raw_value == "":
        raise ValueError(f"{field} is required")
    return int(raw_value)


def save_metric_charts_from_points(points: list[dict[str, Any]]) -> dict[str, str]:
    """Generate charts from multiple data points for dynamic chart display."""
    METRICS_CHART_BASE.parent.mkdir(parents=True, exist_ok=True)
    urls: dict[str, str] = {}

    node_counts = [int(p["nodes"]) for p in points]
    average_hops = [float(p["average_hops"]) for p in points]
    log_values = [float(p["log2_nodes"]) for p in points]
    average_latencies = [float(p["average_latency_ms"]) for p in points]
    messages_per_lookup = [float(p["messages_per_lookup"]) for p in points]

    # X ticks
    x_ticks = node_counts
    if len(node_counts) > 15:
        step = max(1, len(node_counts) // 10)
        x_ticks = node_counts[::step]
        if x_ticks[-1] != node_counts[-1]:
            x_ticks.append(node_counts[-1])

    # Hops chart
    hops_path = METRICS_CHART_BASE.with_name(f"{METRICS_CHART_BASE.name}_hops.png")
    plt.figure(figsize=(5.5, 3.2), dpi=130)
    plt.plot(node_counts, average_hops, marker="o", linewidth=2, color="#0f766e", label="Average hops")
    plt.plot(node_counts, log_values, marker="s", linestyle="--", color="#f59e0b", label="log2(N)")
    plt.title("Lookup Hops")
    plt.xlabel("Number of Nodes")
    plt.ylabel("Hops")
    plt.xticks(x_ticks)
    plt.grid(True, alpha=0.3)
    plt.legend(fontsize=8)
    plt.tight_layout()
    plt.savefig(hops_path)
    plt.close()
    urls["hops"] = f"/static/metrics/{hops_path.name}?ts={time.time_ns()}"

    # Latency chart
    latency_path = METRICS_CHART_BASE.with_name(f"{METRICS_CHART_BASE.name}_latency.png")
    plt.figure(figsize=(5.5, 3.2), dpi=130)
    plt.plot(node_counts, average_latencies, marker="^", linewidth=2, color="#2563eb", label="Avg latency (ms)")
    plt.title("Lookup Latency")
    plt.xlabel("Number of Nodes")
    plt.ylabel("Latency (ms)")
    plt.xticks(x_ticks)
    plt.grid(True, alpha=0.3)
    plt.legend(fontsize=8)
    plt.tight_layout()
    plt.savefig(latency_path)
    plt.close()
    urls["latency"] = f"/static/metrics/{latency_path.name}?ts={time.time_ns()}"

    # Overhead chart
    overhead_path = METRICS_CHART_BASE.with_name(f"{METRICS_CHART_BASE.name}_overhead.png")
    plt.figure(figsize=(5.5, 3.2), dpi=130)
    plt.plot(node_counts, messages_per_lookup, marker="D", linewidth=2, color="#b45309", label="Messages / Lookup")
    plt.title("Message Overhead")
    plt.xlabel("Number of Nodes")
    plt.ylabel("Messages / Lookup")
    plt.xticks(x_ticks)
    plt.grid(True, alpha=0.3)
    plt.legend(fontsize=8)
    plt.tight_layout()
    plt.savefig(overhead_path)
    plt.close()
    urls["overhead"] = f"/static/metrics/{overhead_path.name}?ts={time.time_ns()}"

    return urls


def save_metric_charts(point: dict[str, Any]) -> dict[str, str]:
    """Generate single-point charts (legacy)."""
    return save_metric_charts_from_points([point])


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


# ---------------- error handlers ----------------

@app.errorhandler(HTTPException)
def handle_http_error(exc: HTTPException):
    if request.path.startswith("/api/"):
        return json_error(exc.description or exc.name, exc.code or 500)
    return exc


@app.errorhandler(Exception)
def handle_unexpected_error(exc: Exception):
    if request.path.startswith("/api/"):
        return json_error(str(exc) or "Internal server error", 500)
    raise exc


# ---------------- routes ----------------

@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/state")
def state():
    with coordinator_lock:
        _autoload_once()
        return jsonify({"ok": True, "state": ring.summary(sample_size=None)})


@app.get("/api/resources")
def list_resources():
    with coordinator_lock:
        _autoload_once()
        summary = ring.summary(sample_size=200)
    return jsonify({"ok": True, "count": summary["resource_count"], "resources": summary["sample_resources"]})


@app.get("/api/node/<int:node_id>")
def node_details(node_id: int):
    with coordinator_lock:
        _autoload_once()
        return jsonify({"ok": True, "node": ring.node_details(node_id)})


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
            # ring.lookup returns LookupResult dataclass
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


@app.post("/api/node")
def add_node():
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


@app.post("/api/node/<int:node_id>/restart")
def restart_node(node_id: int):
    return json_error("Restart is not supported. Use /api/node to join a new node.", 400)

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


@app.post("/api/metrics")
def metrics_current_ring():
    payload = request.get_json(silent=True) or {}
    try:
        with coordinator_lock:
            _autoload_once()
            trials = parse_int_field(payload, "trials", 5)
            lookups = parse_int_field(payload, "lookups", 100)
            max_nodes = ring.active_node_count
            # Generate sweep data for dynamic charts (up to max_nodes or 50)
            sweep_max = min(max_nodes, 50)
            if sweep_max < 1:
                sweep_max = 10

            with plot_lock:
                # Get current ring metrics
                result = run_current_ring_metrics(ring, trial_count=trials, lookups_per_trial=lookups, output_path=METRICS_CHART_BASE.with_name(f"{METRICS_CHART_BASE.name}_current.png"))
                # Generate sweep for better charts
                sweep_result = run_lookup_metrics(
                    max_node_count=sweep_max,
                    trial_count=trials,
                    lookups_per_size=lookups,
                    resource_count=len(ring.resources) or 1000,
                    m=ring.m,
                    seed=ring.seed,
                    output_path=METRICS_CHART_BASE.with_name(f"{METRICS_CHART_BASE.name}_sweep.png"),
                )

        point = result["points"][0]
        # Use sweep data for charts (multiple points)
        charts = save_metric_charts_from_points(sweep_result["points"])
        return jsonify({
            "ok": True,
            "message": result.get("message", "Metrics done."),
            "points": result["points"],
            "sweep_points": sweep_result["points"],
            "charts": charts
        })
    except Exception as exc:
        return json_error(str(exc))


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
                output_path=METRICS_CHART_BASE.with_name(f"{METRICS_CHART_BASE.name}_sweep.png"),
            )
        return jsonify({"ok": True, "message": result.get("message", "Sweep completed."), **result})
    except Exception as exc:
        return json_error(str(exc))


@app.post("/api/topology")
def topology():
    payload = request.get_json(silent=True) or {}
    include_last_path = bool(payload.get("include_last_path", False))
    try:
        with coordinator_lock:
            _autoload_once()
            lookup_path = None
            if include_last_path:
                # best-effort: use most recent lookup path if provided by client
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

        return jsonify({"ok": True, "message": "Topology graph generated.", "report": report, "chart_url": f"/static/metrics/{TOPOLOGY_CHART_PATH.name}?ts={time.time_ns()}"})
    except Exception as exc:
        return json_error(str(exc))


if __name__ == "__main__":
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "5000"))
    app.run(host=host, port=port, debug=False)
