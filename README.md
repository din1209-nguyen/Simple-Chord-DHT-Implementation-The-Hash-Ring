# Chord DHT Simulator

**Chủ đề:** #61 - Peer-to-Peer Data Management / Chord DHT
**Nhóm:** The Hash Ring
**Thành viên:** Nguyễn Đông Din

Một ứng dụng web mô phỏng **Chord Distributed Hash Table (DHT)** - giao thức P2P phân tán cho việc quản lý dữ liệu với khả năng tìm kiếm có độ phức tạp O(log N).

## Mục lục

- [Giới thiệu](#giới-thiệu)
- [Tính năng](#tính-năng)
- [Kiến trúc](#kiến-trúc)
- [Cài đặt](#cài-đặt)
- [Sử dụng](#sử-dụng)
- [API Endpoints](#api-endpoints)
- [Cấu trúc dự án](#cấu-trúc-dự-án)

---

## Giới thiệu

**Chord DHT** là một giao thức peer-to-peer được thiết kế để:

- Phân phối dữ liệu đều trên các node
- Tìm kiếm dữ liệu với độ phức tạp **O(log N)** hops
- Tự tổ chức khi node tham gia/rời mạng
- Chịu lỗi node thông qua replication

### Core Formulas

```text
node_id = SHA1("node:<seed>:<attempt>") mod 2^m
key     = SHA1(resource_id) mod 2^m
owner   = successor(key)

Finger Table Entry i:
  start_i = (n + 2^(i-1)) mod 2^m
  finger_i = successor(start_i)
```

## Tính năng

### Core Chord Protocol
- **Finger Table**: Bảng định tuyến với m mục, mỗi mục trỏ tới successor
- **Lookup**: Tìm owner của key bằng thuật toán closest preceding finger
- **Node Management**: Thêm, xóa, dừng node với automatic stabilization

### Replication & Fault Tolerance
- **Replication**: Mỗi resource được lưu trên `r` successor nodes
- **Failure Recovery**: Tự động phục hồi từ replica khi node chết
- **Data Integrity**: Xác minh ánh xạ resource và finger table

### Visualization & Metrics
- **Topology Graph**: Hiển thị cấu trúc vòng Chord với finger links
- **Performance Charts**: Biểu đồ hops, latency, message overhead theo số node
- **Node Details**: Xem finger table, predecessor/successor, local resources

### Web Interface
- Giao diện HTML/JavaScript tương tác
- Real-time state updates
- Visual routing path highlighting

## Kiến trúc

```
## Kiến trúc hệ thống

┌─────────────────────────────────────────────────────────────┐
│                           Browser                           │
│                       Web Interface                         │
└───────────────────────────────┬─────────────────────────────┘
                                │
                                │ HTTP / REST API
                                ▼
┌─────────────────────────────────────────────────────────────┐
│                         app.py                              │
│                    Flask Web Server                         │
│                                                             │
│  ┌───────────────────────────────────────────────────────┐  │
│  │                    ChordRing                          │  │
│  │                 In-Memory Storage                     │  │
│  │                                                       │  │
│  │  • Manage Chord nodes                                 │  │
│  │  • Build and update finger tables                     │  │
│  │  • Maintain successor and predecessor links           │  │
│  │  • Store and lookup resources                         │  │
│  └───────────────────────────────────────────────────────┘  │
│                                │                            │
│                                │ Save / Restore state       │
│                                ▼                            │
│  ┌───────────────────────────────────────────────────────┐  │
│  │                    data/state.json                    │  │
│  │              Persistent State Backup                  │  │
│  └───────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

### Mô tả luồng hoạt động

Người dùng thao tác thông qua giao diện web trên trình duyệt. Các request từ browser được gửi đến Flask server thông qua HTTP/REST API.

Bên trong `app.py`, hệ thống sử dụng `ChordRing` để mô phỏng mạng Chord DHT trong bộ nhớ. `ChordRing` quản lý danh sách node, finger table, liên kết successor/predecessor và quá trình lưu trữ hoặc tìm kiếm resource.

Dữ liệu trạng thái của hệ thống được sao lưu vào file `data/state.json`, giúp khôi phục lại node, resource và cấu trúc vòng Chord khi cần thiết.

```

### Đặc điểm triển khai

- **Single-process simulation**: Tất cả node được mô phỏng trong bộ nhớ
- **State Persistence**: Trạng thái ring tự động lưu vào JSON
- **Flask REST API**: Cung cấp endpoints cho CRUD operations

## Cài đặt

### Yêu cầu

- Python 3.10+
- pip

### Các bước cài đặt

```powershell
# 1. Tạo virtual environment
py -3.10 -m venv .venv

# 2. Kích hoạt virtual environment
.\.venv\Scripts\activate

# 3. Cài đặt dependencies
python -m pip install -e .

# Hoặc cài trực tiếp:
python -m pip install Flask matplotlib networkx pytest
```

## Sử dụng

### Khởi động server

```powershell
python app.py
```

Server sẽ chạy tại `http://127.0.0.1:5000/`

### Tùy chọn environment

```powershell
$env:HOST = "0.0.0.0"  # Bind address (mặc định: 127.0.0.1)
$env:PORT = "8080"     # Port (mặc định: 5000)
python app.py
```

### Khởi tạo Network

Mặc định khi truy cập lần đầu, hệ thống sẽ tự động khởi tạo với:
- **50 nodes**
- **1000 resources**
- **m = 16** (không gian ID: 2^16 = 65,536)
- **replication = 3**

Có thể cấu hình qua API:

```bash
curl -X POST http://127.0.0.1:5000/api/initialize \
  -H "Content-Type: application/json" \
  -d '{"nodes": 30, "resources": 500, "m": 16, "seed": 42}'
```

## API Endpoints

### Network Management

| Method | Endpoint | Mô tả |
|--------|----------|--------|
| `GET` | `/api/state` | Lấy trạng thái tổng quan |
| `POST` | `/api/initialize` | Khởi tạo network mới |

### Node Operations

| Method | Endpoint | Mô tả |
|--------|----------|--------|
| `POST` | `/api/node` | Thêm node mới |
| `GET` | `/api/node/<node_id>` | Chi tiết node |
| `DELETE` | `/api/node/<node_id>` | Xóa node |
| `POST` | `/api/kill` | Dừng node (simulate failure) |

### Resource Operations

| Method | Endpoint | Mô tả |
|--------|----------|--------|
| `POST` | `/api/resource` | Thêm resource |
| `PUT` | `/api/resource` | Cập nhật resource |
| `DELETE` | `/api/resource` | Xóa resource |
| `GET` | `/api/resources` | Danh sách resources |
| `POST` | `/api/lookup` | Tìm owner của resource |

### Metrics & Visualization

| Method | Endpoint | Mô tả |
|--------|----------|--------|
| `POST` | `/api/metrics` | Thu thập metrics trên ring hiện tại |
| `GET` | `/api/metrics/last` | Lấy metrics đã lưu |
| `POST` | `/api/metrics/sweep` | Sweep metrics với nhiều kích thước network |
| `POST` | `/api/topology` | Tạo ảnh topology graph |

## Cấu trúc dự án

```
Final/
├── app.py                      # Flask application & API endpoints
├── src/
│   └── chord_dht/
│       ├── __init__.py         # Package exports
│       ├── chord.py            # ChordRing implementation
│       ├── identifiers.py      # Hash functions (SHA-1)
│       ├── models.py           # Data models (Node, Resource, etc.)
│       ├── metrics.py          # Performance measurement
│       ├── ring.py            # Ring utilities
│       └── visualization.py    # Graph generation (NetworkX)
├── static/
│   ├── app.js                 # Frontend JavaScript
│   └── style.css               # UI styles
├── templates/
│   └── index.html             # Main UI template
├── data/
│   └── state.json            # Persisted state
├── tests/
│   ├── test_distributed_chord.py
│   └── fixtures/
├── docs/
│   ├── design_document.md     # Chi tiết thiết kế
│   ├── analysis.md            # Phân tích và đánh giá
│   └── project_proposal.md    # Đề xuất dự án
├── requirements.txt
├── pyproject.toml
└── README.md
```

## Testing

```powershell
# Chạy tất cả tests
.\.venv\Scripts\python.exe -m pytest -q

# Chạy với verbose output
.\.venv\Scripts\python.exe -m pytest -v

# Chạy specific test file
.\.venv\Scripts\python.exe -m pytest tests/test_distributed_chord.py -v
```

### Test Coverage

- Node join/leave operations
- Lookup routing algorithm
- Replication consistency
- Failure recovery
- Finger table integrity
- Resource mapping verification

---

## Thuật ngữ

| Thuật ngữ | Mô tả |
|-----------|--------|
| **Node** | Một peer trong mạng Chord |
| **Key** | Giá trị hash của resource |
| **Owner** | Node chịu trách nhiệm lưu trữ key |
| **Successor** | Node đứng sau một node khác trên vòng |
| **Predecessor** | Node đứng trước một node khác trên vòng |
| **Finger Table** | Bảng định tuyến giúp lookup nhanh O(log N) |
| **Replica** | Bản sao của resource trên các successor nodes |

---

**Đề tài:** Topic 61 - Peer-to-Peer Data Management / Chord DHT
**Môn học:** Cơ Sở Dữ Liệu Phân Tán - PTIT
