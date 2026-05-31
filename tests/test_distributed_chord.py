# Import json để parse nội dung state.json
import json

# Import Path để thao tác đường dẫn test
from pathlib import Path

# Import pytest để chạy test theo fixture
import pytest

# Import các hàm định danh để kiểm thử
from chord_dht import hash_identifier, in_clockwise_interval


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
    # Import app để lấy Flask application
    import app

    # Gắn STATE_PATH vào thư mục tạm để test không ghi đè dữ liệu thật
    monkeypatch.setattr(app, "STATE_PATH", tmp_path / "state.json")

    # Reset ring để mỗi test chạy độc lập
    app.ring = app.ChordRing(m=16, seed=61, replication_count=1)

    # Reset cờ autoload để endpoint tự load lại từ file
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
    # Import app để thao tác trạng thái in-memory
    import app

    # Gọi initialize để tạo dữ liệu trước
    client.post(
        "/api/initialize",
        json={"nodes": 10, "resources": 12, "m": 10, "seed": 61, "replication_count": 2},
    )

    # Reset ring trong bộ nhớ để bắt buộc autoload từ file
    app.ring = app.ChordRing(m=16, seed=61, replication_count=1)

    # Reset cờ autoload để lần gọi sau sẽ load state.json
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

    # Parse payload state.json
    payload = json.loads(state_path.read_text(encoding="utf-8"))

    # Kiểm tra resource đã bị xóa khỏi danh sách persist
    assert "student-score" not in payload.get("resources", [])
