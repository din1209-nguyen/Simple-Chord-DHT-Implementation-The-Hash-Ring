# Nạp json để phân tích nội dung state.json
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

    # Đặt lại ring để mỗi test chạy độc lập
    app.ring = app.ChordRing(m=16, seed=61, replication_count=1)

    # Đặt lại cờ autoload để endpoint tự load lại từ file
    app.ring_startup_completed = False

    # Trả về test_client để gửi request
    yield app.app.test_client()

# Kiểm thử endpoint initialize có ghi state.json đúng schema
def test_initialize_persists_state_json(client, tmp_path):
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

    # Tạo đường dẫn state.json trong thư mục tạm
    state_path = tmp_path / "state.json"

    # Kiểm tra file state.json được tạo
    assert state_path.exists()

    # Đọc nội dung file state.json
    payload = json.loads(state_path.read_text(encoding="utf-8"))

    # Kiểm tra schema_version khớp với kỳ vọng
    assert payload["schema_version"] == 1

    # Kiểm tra m được persist đúng
    assert int(payload["config"]["m"]) == 10

# Kiểm thử endpoint state tự autoload từ state.json
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

    # Đặt lại cờ autoload để lần gọi sau sẽ load state.json
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

# Kiểm thử CRUD resource cập nhật state.json
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

    # Đọc file state.json để xác nhận persist
    state_path = tmp_path / "state.json"

    # Phân tích payload state.json
    payload = json.loads(state_path.read_text(encoding="utf-8"))

    # Kiểm tra resource đã bị xóa khỏi danh sách persist
    assert "student-score" not in payload.get("resources", [])

# Kiểm thử node join chỉ chuyển primary trong khoảng node mới nhận và cập nhật replica kế cận
def test_add_node_rebalances_primary_interval_and_successor_replicas():
    # Tạo ring thủ công để kiểm soát chính xác thứ tự node trên vòng
    ring = ChordRing(m=8, seed=61, replication_count=2)

    # Tạo ba node active ban đầu
    ring.nodes[50] = Node(node_id=50, active=True, predecessor=220, successor=150)
    ring.nodes[150] = Node(node_id=150, active=True, predecessor=50, successor=220)
    ring.nodes[220] = Node(node_id=220, active=True, predecessor=150, successor=50)

    # Làm mới finger table cho topology ban đầu
    ring.refresh_all_finger_tables()

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
