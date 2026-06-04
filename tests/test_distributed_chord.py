# Nạp json để phân tích nội dung state đã persist
import json

# Nạp Path để thao tác đường dẫn test
from pathlib import Path

# Nạp pytest để chạy test theo fixture
import pytest

# Nạp các hàm định danh để kiểm thử
from chord_dht import ChordRing, Node, ResourceRecord, hash_identifier, in_clockwise_interval

# Kiểm thử hàm băm luôn trả về trong không gian m bit
def test_hash_identifier_stays_inside_m_bit_space():
    # Tạo giá trị băm từ một resource mẫu
    value = hash_identifier("resource-0001", m=16)

    # Kiểm tra giá trị băm nằm trong [0, 2^m)
    assert 0 <= value < 2**16

# Kiểm thử hàm interval xử lý wraparound trên vòng
def test_clockwise_interval_handles_wraparound():
    # Kiểm tra giá trị nằm trong khoảng wrap
    assert in_clockwise_interval(2, 14, 4)

    # Kiểm tra giá trị lớn hơn start vẫn thuộc khoảng wrap
    assert in_clockwise_interval(15, 14, 4)

    # Kiểm tra giá trị ở giữa không thuộc khoảng wrap
    assert not in_clockwise_interval(8, 14, 4)

# Tạo fixture client để gọi Flask API trong test
@pytest.fixture()
def client(tmp_path, monkeypatch):
    # Nạp app để lấy Flask application
    import app

    # Gắn STATE_PATH vào thư mục tạm để test không ghi đè dữ liệu thật
    monkeypatch.setattr(app, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(app, "NODE_IDS_PATH", tmp_path / "node_ids.json")
    monkeypatch.setattr(app, "RESOURCE_IDS_PATH", tmp_path / "resource_ids.json")

    # Đặt lại ring để mỗi test chạy độc lập
    app.ring = app.ChordRing(m=16, seed=61, replication_count=1)

    # Đặt lại cờ autoload để endpoint tự load lại từ file
    app.ring_startup_completed = False

    # Trả về test_client để gửi request
    yield app.app.test_client()

# Kiểm thử endpoint initialize có ghi state đã tách file đúng schema
def test_initialize_persists_split_state_json(client, tmp_path):
    # Gửi request khởi tạo ring
    resp = client.post(
        "/api/initialize",
        json={
            "nodes": 10,
            "resources": 12,
            "m": 10,
            "seed": 61,
            "replication_count": 2,
        },
    )

    # Kiểm tra status code thành công
    assert resp.status_code == 200

    # Đọc body json
    body = resp.get_json()

    # Kiểm tra cờ ok
    assert body["ok"] is True

    # Tạo đường dẫn state/meta.json trong thư mục tạm
    state_path = tmp_path / "state" / "meta.json"

    # Kiểm tra file meta state được tạo
    assert state_path.exists()

    # Đọc nội dung file meta state
    payload = json.loads(state_path.read_text(encoding="utf-8"))

    # Kiểm tra schema_version khớp với kỳ vọng
    assert payload["schema_version"] == 2

    # Kiểm tra m được persist đúng
    assert int(payload["config"]["m"]) == 10

    assert len(payload["node_files"]) == 10
    first_node_file = tmp_path / "state" / payload["node_files"][0]["path"]
    assert first_node_file.exists()

    node_payload = json.loads(first_node_file.read_text(encoding="utf-8"))
    assert "node" in node_payload
    assert "resources" in node_payload

# Kiểm thử endpoint state tự autoload từ state đã persist
def test_state_endpoint_autoloads_json(client, tmp_path):
    # Nạp app để thao tác trạng thái in-memory
    import app

    # Gọi initialize để tạo dữ liệu trước
    client.post(
        "/api/initialize",
        json={"nodes": 10, "resources": 12, "m": 10, "seed": 61, "replication_count": 2},
    )

    # Đặt lại ring trong bộ nhớ để bắt buộc autoload từ file
    app.ring = app.ChordRing(m=16, seed=61, replication_count=1)

    # Đặt lại cờ autoload để lần gọi sau sẽ load state từ đĩa
    app.ring_startup_completed = False

    # Gọi endpoint state
    resp = client.get("/api/state")

    # Đọc body json
    body = resp.get_json()

    # Kiểm tra cờ ok
    assert body["ok"] is True

    # Kiểm tra số node active đúng
    assert body["state"]["active_node_count"] == 10

    # Kiểm tra số resource đúng
    assert body["state"]["resource_count"] == 12

# Kiểm thử endpoint lookup có trả về trace đường đi
def test_lookup_returns_trace(client):
    # Gọi initialize để có ring hoạt động
    client.post(
        "/api/initialize",
        json={"nodes": 10, "resources": 12, "m": 10, "seed": 61, "replication_count": 2},
    )

    # Gọi lookup cho resource mẫu
    resp = client.post("/api/lookup", json={"resource_id": "resource-0001"})

    # Đọc body json
    body = resp.get_json()

    # Kiểm tra cờ ok
    assert body["ok"] is True

    # Kiểm tra có trường path trong kết quả
    assert "path" in body["result"]

    # Kiểm tra path là list
    assert isinstance(body["result"]["path"], list)

# Kiểm thử CRUD resource cập nhật state đã tách file
def test_resource_crud_updates_json(client, tmp_path):
    # Gọi initialize với resource_count bằng 0
    client.post(
        "/api/initialize",
        json={"nodes": 10, "resources": 0, "m": 10, "seed": 61, "replication_count": 2},
    )

    # Gọi endpoint tạo resource
    created = client.post("/api/resource", json={"resource_id": "student-score"}).get_json()

    # Kiểm tra tạo thành công
    assert created["ok"] is True

    # Gọi endpoint xóa resource
    deleted = client.delete("/api/resource", json={"resource_id": "student-score"}).get_json()

    # Kiểm tra xóa thành công
    assert deleted["ok"] is True

    # Đọc file meta state để xác nhận persist
    state_path = tmp_path / "state" / "meta.json"

    # Phân tích payload meta state
    payload = json.loads(state_path.read_text(encoding="utf-8"))

    persisted_resource_ids = set()
    for item in payload["node_files"]:
        node_path = tmp_path / "state" / item["path"]
        node_payload = json.loads(node_path.read_text(encoding="utf-8"))
        persisted_resource_ids.update(
            resource["resource_id"]
            for resource in node_payload.get("resources", [])
        )

    # Kiểm tra resource đã bị xóa khỏi danh sách persist
    assert "student-score" not in persisted_resource_ids

# Kiểm thử node join chỉ chuyển primary trong khoảng node mới nhận và cập nhật replica kế cận
def test_add_node_rebalances_primary_interval_and_successor_replicas():
    # Tạo ring thủ công để kiểm soát chính xác thứ tự node trên vòng
    ring = ChordRing(m=8, seed=61, replication_count=2)

    # Tạo ba node active ban đầu
    ring.nodes[50] = Node(node_id=50, active=True, predecessor=220, successor=150)
    ring.nodes[150] = Node(node_id=150, active=True, predecessor=50, successor=220)
    ring.nodes[220] = Node(node_id=220, active=True, predecessor=150, successor=50)

    # Làm mới finger table cho topology ban đầu
    ring.run_protocol_until_stable()

    # Tạo resource có key thuộc khoảng (50, 130] nên sẽ chuyển primary sang node mới
    moving_resource = ResourceRecord("moving-resource", "hash-moving", 120, 150)
    ring.resources[moving_resource.resource_id] = moving_resource
    ring._place_resource_copies(moving_resource)

    # Tạo resource nằm ngoài khoảng primary mới nhưng replica chain sẽ bị ảnh hưởng
    stable_resource = ResourceRecord("stable-resource", "hash-stable", 180, 220)
    ring.resources[stable_resource.resource_id] = stable_resource
    ring._place_resource_copies(stable_resource)

    # Thêm node mới vào giữa node 50 và node 150
    ring.add_node(130)

    # Kiểm tra resource trong khoảng (50, 130] chuyển primary sang node mới
    assert ring.resources["moving-resource"].owner_id == 130

    # Kiểm tra replica của resource mới đi theo successor chain sau primary
    assert ring.resources["moving-resource"].replica_node_ids == [150, 220]

    # Kiểm tra resource ngoài khoảng không bị đổi primary
    assert ring.resources["stable-resource"].owner_id == 220

    # Kiểm tra replica của resource ngoài khoảng vẫn được cập nhật khi node mới chen vào successor chain
    assert ring.resources["stable-resource"].replica_node_ids == [50, 130]

    # Kiểm tra toàn bộ mapping resource vẫn hợp lệ sau node join
    assert ring.verify_resource_mapping()


def test_mark_node_failed_only_marks_failure_without_repairing_tables_or_resources():
    ring = ChordRing(m=8, seed=61, replication_count=2)
    ring.initialize_network(node_count=10, resource_count=20, seed=61, replication_count=2)
    failed_node_id = next(iter(ring.resources.values())).owner_id
    failed_local_resources = set(ring.nodes[failed_node_id].local_resources)
    finger_tables_before = {
        node_id: [entry.to_dict() for entry in node.finger_table]
        for node_id, node in ring.nodes.items()
    }

    report = ring.mark_node_failed(failed_node_id)

    assert ring.nodes[failed_node_id].active is False
    assert failed_node_id in ring.failed_nodes
    assert set(ring.nodes[failed_node_id].local_resources) == failed_local_resources
    assert {
        node_id: [entry.to_dict() for entry in node.finger_table]
        for node_id, node in ring.nodes.items()
    } == finger_tables_before
    assert report["affected_resource_count"] >= 1
    assert "recovered_resource_total_count" not in report


def test_recover_failed_node_repairs_fingers_and_resource_mapping():
    ring = ChordRing(m=8, seed=61, replication_count=2)
    ring.initialize_network(node_count=10, resource_count=20, seed=61, replication_count=2)
    failed_node_id = next(iter(ring.resources.values())).owner_id

    ring.mark_node_failed(failed_node_id)
    report = ring.recover_failed_node(failed_node_id)

    assert report["updated_finger_entries"] >= 0
    assert all(
        entry.node_id != failed_node_id
        for node_id in ring.active_node_ids
        for entry in ring.nodes[node_id].finger_table
    )
    assert ring.verify_resource_mapping()


def test_route_repair_does_not_move_resources_before_recovery():
    ring = ChordRing(m=8, seed=61, replication_count=2)
    ring.initialize_network(node_count=10, resource_count=20, seed=61, replication_count=2)
    failed_node_id = next(iter(ring.resources.values())).owner_id

    ring.mark_node_failed(failed_node_id)
    owners_before_route_repair = {
        resource_id: resource.owner_id
        for resource_id, resource in ring.resources.items()
    }

    active_node_id = ring.active_node_ids[0]
    ring._repair_node_after_failure(active_node_id, failed_node_id)

    assert {
        resource_id: resource.owner_id
        for resource_id, resource in ring.resources.items()
    } == owners_before_route_repair


def test_fix_fingers_recomputes_successor_start_even_when_existing_finger_is_wrong():
    ring = ChordRing(m=16, seed=61, replication_count=1)
    for node_id in [18652, 19570, 21012, 24076, 30016, 37252, 51502]:
        ring.nodes[node_id] = Node(node_id=node_id, active=True)

    ordered = ring.active_node_ids
    for index, node_id in enumerate(ordered):
        ring.nodes[node_id].predecessor = ordered[(index - 1) % len(ordered)]
        ring.nodes[node_id].successor = ordered[(index + 1) % len(ordered)]

    ring.run_protocol_until_stable()
    stale_entry = ring.nodes[18652].finger_table[13]
    ring.nodes[18652].finger_table[13] = type(stale_entry)(
        index=stale_entry.index,
        start=stale_entry.start,
        interval_end=stale_entry.interval_end,
        node_id=19570,
    )

    ring._protocol_ticks = 13
    ring.fix_fingers_one(18652)

    assert ring.nodes[18652].finger_table[13].start == 26844
    assert ring.nodes[18652].finger_table[13].node_id == 30016


def test_recover_reconciles_resource_copies_with_wrong_active_owner():
    ring = ChordRing(m=16, seed=61, replication_count=1)
    ring.nodes[3265] = Node(node_id=3265, active=True, predecessor=60689, successor=4280)
    ring.nodes[4280] = Node(node_id=4280, active=True, predecessor=3265, successor=60689)
    ring.nodes[60689] = Node(node_id=60689, active=True, predecessor=4280, successor=3265)
    ring.nodes[199] = Node(node_id=199, active=False)
    ring.failed_nodes.add(199)
    ring.run_protocol_until_stable()

    resource = ResourceRecord(
        resource_id="resource-0004",
        hashed_resource_id="hash",
        key=61424,
        owner_id=4280,
        replica_node_ids=[60689],
    )
    ring.resources[resource.resource_id] = resource
    ring.nodes[4280].local_resources[resource.resource_id] = resource
    ring.nodes[60689].local_resources[resource.resource_id] = resource

    report = ring.recover_failed_node(199)

    assert report["ownership_repaired_resource_total_count"] == 1
    assert ring.resources["resource-0004"].owner_id == 3265
    assert ring.resources["resource-0004"].replica_node_ids == [4280]
    assert "resource-0004" in ring.nodes[3265].local_resources
    assert ring.lookup("resource-0004", start_node_id=3265).found is True
    assert ring.verify_resource_mapping()


def test_kill_endpoint_only_reports_impact_and_recover_endpoint_repairs(client):
    client.post(
        "/api/initialize",
        json={"nodes": 10, "resources": 12, "m": 10, "seed": 61, "replication_count": 2},
    )
    state_before = client.get("/api/state").get_json()["state"]
    resource = state_before["sample_resources"][0]
    node_id = int(resource["owner_id"])

    killed = client.post("/api/kill", json={"node_id": node_id}).get_json()

    assert killed["ok"] is True
    assert node_id in killed["state"]["failed_nodes"]
    assert "recovered_resource_total_count" not in killed["report"]
    assert any(
        item["resource_id"] == resource["resource_id"]
        for item in killed["state"]["sample_resources"]
    )
    assert any(
        item["resource_id"] == resource["resource_id"]
        for item in killed["state"]["affected_resources"]
    )

    recovered = client.post("/api/recover", json={"node_id": node_id}).get_json()

    assert recovered["ok"] is True
    assert "recovered_resource_total_count" in recovered["report"]
    recovered_impact = recovered["report"]["impact_report"]
    assert any(
        item["resource_id"] == resource["resource_id"] and item["failure_role"] == "owner"
        for item in recovered_impact["affected_resources"]
    )
    assert recovered["state"]["stale_finger_entries"] == []
    assert node_id not in recovered["state"]["failed_nodes"]
    assert node_id in recovered["state"]["retired_nodes"]
    assert any(
        int(node["node_id"]) == node_id and node["status"] == "retired"
        for node in recovered["state"]["nodes"]
    )


def test_pending_recovery_blocks_operations_until_recover(client):
    import app

    client.post(
        "/api/initialize",
        json={"nodes": 10, "resources": 12, "m": 10, "seed": 61, "replication_count": 2},
    )
    state_before = client.get("/api/state").get_json()["state"]
    resource = state_before["sample_resources"][0]
    failed_node_id = int(resource["owner_id"])
    other_node_id = next(
        int(node["node_id"])
        for node in state_before["nodes"]
        if int(node["node_id"]) != failed_node_id and node["active"]
    )

    client.post("/api/kill", json={"node_id": failed_node_id})
    finger_tables_after_kill = {
        node_id: [entry.to_dict() for entry in node.finger_table]
        for node_id, node in app.ring.nodes.items()
    }
    local_resources_after_kill = {
        node_id: set(node.local_resources)
        for node_id, node in app.ring.nodes.items()
    }

    blocked_requests = [
        client.post("/api/kill", json={"node_id": other_node_id}),
        client.post("/api/lookup", json={"resource_id": resource["resource_id"]}),
        client.post("/api/node", json={}),
        client.delete(f"/api/node/{other_node_id}"),
        client.post("/api/resource", json={"resource_id": "blocked-resource"}),
        client.put(
            "/api/resource",
            json={
                "old_resource_id": resource["resource_id"],
                "new_resource_id": "blocked-resource-update",
            },
        ),
        client.delete("/api/resource", json={"resource_id": resource["resource_id"]}),
        client.post("/api/metrics", json={"lookups": 1, "trials": 1}),
    ]

    for response in blocked_requests:
        body = response.get_json()
        assert response.status_code == 409
        assert body["ok"] is False
        assert body["requires_recovery"] is True
        assert failed_node_id in body["failed_nodes"]

    topology = client.post("/api/topology", json={})
    topology_body = topology.get_json()
    assert topology.status_code == 200
    assert topology_body["ok"] is True
    assert topology_body["report"]["failed_node_count"] == 1

    assert {
        node_id: [entry.to_dict() for entry in node.finger_table]
        for node_id, node in app.ring.nodes.items()
    } == finger_tables_after_kill
    assert {
        node_id: set(node.local_resources)
        for node_id, node in app.ring.nodes.items()
    } == local_resources_after_kill

    recovered = client.post("/api/recover", json={"node_id": failed_node_id}).get_json()
    assert recovered["ok"] is True
    assert failed_node_id not in recovered["state"]["failed_nodes"]
    assert failed_node_id in recovered["state"]["retired_nodes"]

    lookup_after_recover = client.post(
        "/api/lookup",
        json={"resource_id": resource["resource_id"]},
    )
    assert lookup_after_recover.status_code == 200
    assert lookup_after_recover.get_json()["ok"] is True


def test_initialize_is_allowed_while_recovery_is_pending(client):
    client.post(
        "/api/initialize",
        json={"nodes": 10, "resources": 12, "m": 10, "seed": 61, "replication_count": 2},
    )
    state_before = client.get("/api/state").get_json()["state"]
    failed_node_id = int(state_before["sample_resources"][0]["owner_id"])

    client.post("/api/kill", json={"node_id": failed_node_id})
    initialized = client.post(
        "/api/initialize",
        json={"nodes": 10, "resources": 1, "m": 10, "seed": 62, "replication_count": 1},
    )

    body = initialized.get_json()
    assert initialized.status_code == 200
    assert body["ok"] is True
    assert body["state"]["failed_nodes"] == []


def test_recover_does_not_restore_metadata_only_resource():
    ring = ChordRing(m=16, seed=61, replication_count=1)
    ring.nodes[3265] = Node(node_id=3265, active=True, predecessor=60689, successor=4280)
    ring.nodes[4280] = Node(node_id=4280, active=True, predecessor=3265, successor=60689)
    ring.nodes[60689] = Node(node_id=60689, active=True, predecessor=4280, successor=3265)
    ring.nodes[199] = Node(node_id=199, active=False)
    ring.failed_nodes.add(199)
    ring.run_protocol_until_stable()

    resource = ResourceRecord(
        resource_id="metadata-only",
        hashed_resource_id="hash",
        key=61424,
        owner_id=4280,
        replica_node_ids=[60689],
    )
    ring.resources[resource.resource_id] = resource

    report = ring.recover_failed_node(199)

    assert report["ownership_repaired_resource_total_count"] == 0
    assert "metadata-only" not in ring.nodes[3265].local_resources
    assert "metadata-only" not in ring.nodes[4280].local_resources
    assert "metadata-only" not in ring.nodes[60689].local_resources
