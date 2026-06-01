# Chord DHT Simulator

Ứng dụng web mô phỏng **Chord Distributed Hash Table (DHT)** cho đề tài **Peer-to-Peer Data Management / Chord DHT**. Dự án minh họa cách một hệ thống P2P phân tán ánh xạ tài nguyên vào vòng định danh, định tuyến truy vấn bằng finger table, xử lý node join/leave/failure, sao lưu dữ liệu bằng replica và đo hiệu năng lookup theo số lượng node.

## Thông Tin Dự Án

| Mục | Nội dung |
| --- | --- |
| Chủ đề | Topic 61 - Simple Chord DHT Implementation |
| Thành viên | Nguyễn Đông Din |
| Môn học | Cơ Sở Dữ Liệu Phân Tán |
| Ngôn ngữ | Python, JavaScript, HTML, CSS |
| Backend | Flask |
| Visualization | Matplotlib, NetworkX |
| Kiểu triển khai | Single-process simulation |

## Mục Lục

- [Tổng Quan](#tổng-quan)
- [Mục Tiêu Dự Án](#mục-tiêu-dự-án)
- [Kiến Thức Chord DHT](#kiến-thức-chord-dht)
- [Tính Năng Chính](#tính-năng-chính)
- [Kiến Trúc Hệ Thống](#kiến-trúc-hệ-thống)
- [Luồng Hoạt Động](#luồng-hoạt-động)
- [Cấu Trúc Thư Mục](#cấu-trúc-thư-mục)
- [Cài Đặt](#cài-đặt)
- [Chạy Ứng Dụng](#chạy-ứng-dụng)
- [Hướng Dẫn Sử Dụng](#hướng-dẫn-sử-dụng)
- [API Endpoints](#api-endpoints)
- [Dữ Liệu Lưu Trữ](#dữ-liệu-lưu-trữ)
- [Metrics Và Visualization](#metrics-và-visualization)
- [Kiểm Thử](#kiểm-thử)
- [Thuật Ngữ](#thuật-ngữ)

## Tổng Quan

Chord DHT là một giao thức quản lý dữ liệu P2P sử dụng vòng định danh để phân phối key và tài nguyên lên các node. Mỗi node chỉ cần biết một lượng nhỏ thông tin định tuyến thông qua successor, predecessor và finger table, nhưng vẫn có thể tìm owner của một key với độ phức tạp kỳ vọng **O(log N)**.

Dự án này mô phỏng đầy đủ các thành phần cốt lõi của Chord:

- Sinh node ID và resource key bằng SHA-1 trong không gian `2^m`
- Sắp xếp node trên vòng định danh
- Xác định owner của resource bằng `successor(key)`
- Xây dựng finger table cho từng node
- Định tuyến lookup bằng thuật toán closest preceding finger
- Thêm node, xóa node và mô phỏng node failure
- Sao lưu resource qua các successor node
- Sinh biểu đồ topology và biểu đồ hiệu năng lookup
- Persist trạng thái ring xuống file JSON để khôi phục sau khi restart server

## Mục Tiêu Dự Án

Dự án được xây dựng để phục vụ học tập và trình bày trong môn Cơ Sở Dữ Liệu Phân Tán. Các mục tiêu chính gồm:

1. Mô phỏng cách Chord DHT phân phối dữ liệu trong mạng ngang hàng
2. Minh họa cơ chế lookup theo finger table thay vì duyệt tuyến tính toàn bộ node
3. Thể hiện quá trình node tham gia, rời mạng và làm ổn định lại topology
4. Mô phỏng fault tolerance thông qua replica và recovery khi node lỗi
5. Cung cấp giao diện trực quan để quan sát ring, finger table, resource ownership và lookup path
6. Đo lường số hop, latency mô phỏng và message overhead khi số node thay đổi

## Kiến Thức Chord DHT

### Không gian định danh

Chord sử dụng không gian định danh dạng vòng với kích thước `2^m`. Trong dự án, giá trị mặc định thường dùng là `m = 16`, tương ứng không gian ID từ `0` đến `65535`.

```text
identifier_space = 2^m
node_id = SHA1("node:<seed>:<attempt>") mod 2^m
resource_key = SHA1(resource_id) mod 2^m
```

### Owner của resource

Một resource được gán cho node đầu tiên có ID lớn hơn hoặc bằng key của resource theo chiều kim đồng hồ trên vòng. Node đó được gọi là successor của key.

```text
owner(resource) = successor(resource_key)
```

Nếu key lớn hơn tất cả node ID hiện có, owner sẽ quay vòng về node có ID nhỏ nhất.

### Finger table

Mỗi node có `m` finger entry. Entry thứ `i` của node `n` bắt đầu tại:

```text
start_i = (n + 2^(i - 1)) mod 2^m
finger_i = successor(start_i)
```

Finger table giúp node nhảy xa hơn trên vòng thay vì chỉ đi từng successor. Nhờ đó lookup có thể đạt độ phức tạp kỳ vọng `O(log N)`.

### Lookup

Khi một node cần tìm owner của key:

1. Kiểm tra node hiện tại có sở hữu key không
2. Nếu chưa sở hữu, chọn finger gần key nhất nhưng không vượt quá key
3. Chuyển tiếp truy vấn tới finger đó
4. Lặp lại cho đến khi tìm được owner

Trong giao diện, lookup path được hiển thị để người dùng thấy truy vấn đi qua những node nào.

## Tính Năng Chính

### Quản lý mạng Chord

- Khởi tạo ring với số node, số resource, `m`, `seed` và số replica tùy chọn
- Thêm node mới vào ring và tự động stabilize topology
- Xóa node khỏi ring sau khi xử lý trạng thái active/inactive
- Mô phỏng node failure bằng thao tác kill node
- Cập nhật successor, predecessor và finger table sau các thay đổi topology

### Quản lý resource

- Thêm resource mới vào ring bằng Chord routing
- Lookup resource và trả về owner, key, số hop, path và log định tuyến
- Cập nhật resource bằng cách xóa bản cũ và put bản mới
- Xóa resource khỏi owner và các replica liên quan
- Liệt kê toàn bộ resource đang được quản lý

### Replication và recovery

- Lưu resource tại owner và các successor tiếp theo tùy theo `replication_count`
- Theo dõi danh sách replica của từng resource
- Khi node bị kill, hệ thống chạy recovery để giữ resource tiếp tục khả dụng nếu còn replica hợp lệ
- Ghi nhận trạng thái node lỗi trong `failed_nodes`

### Visualization

- Sinh ảnh topology của vòng Chord bằng NetworkX và Matplotlib
- Hiển thị successor edge và finger edge
- Highlight lookup path khi người dùng vừa tra cứu resource
- Sinh biểu đồ metric gồm average hops, latency mô phỏng và message overhead

### Persist state

- Lưu toàn bộ trạng thái ring vào `data/state.json`
- Lưu dataset node ban đầu vào `data/node_ids.json`
- Lưu dataset resource ban đầu vào `data/resource_ids.json`
- Tự động autoload state khi server nhận request đầu tiên

## Kiến Trúc Hệ Thống

```text
Browser
  |
  | HTTP / REST API
  v
app.py
  |
  | Điều phối request, validate payload, persist state
  v
ChordRing
  |
  | Quản lý node, resource, routing, replication, metrics
  v
src/chord_dht/*
  |
  | Lưu snapshot JSON và ảnh biểu đồ
  v
data/* + static/metrics/*
```

### Vai trò các thành phần

| Thành phần | Vai trò |
| --- | --- |
| `app.py` | Flask server, REST API, persist state, điều phối metric và topology |
| `src/chord_dht/chord.py` | Cài đặt lớp `ChordRing`, routing, join, stabilize, lookup, replication |
| `src/chord_dht/models.py` | Định nghĩa `Node`, `FingerEntry`, `ResourceRecord`, `LookupResult` |
| `src/chord_dht/identifiers.py` | Hash identifier và xử lý interval trên vòng Chord |
| `src/chord_dht/metrics.py` | Chạy benchmark lookup và sinh dữ liệu metric |
| `src/chord_dht/visualization.py` | Dựng topology graph và lưu ảnh visualization |
| `templates/index.html` | Giao diện chính |
| `static/app.js` | Logic frontend gọi API và render dữ liệu |
| `static/style.css`, `static/busy.css` | Style giao diện |
| `tests/test_distributed_chord.py` | Bộ test cho hash, API, lookup, replication và recovery |

## Luồng Hoạt Động

### Khởi tạo ring

1. Frontend gửi `POST /api/initialize`
2. Backend đọc số node, resource, `m`, `seed` và replication count
3. `ChordRing` sinh node ID duy nhất theo seed
4. Ring sắp xếp node, nối predecessor/successor và build finger table
5. Resource được hash thành key và đặt vào owner tương ứng
6. Replica được đặt lên các successor tiếp theo
7. State được persist xuống `data/state.json`

### Lookup resource

1. Frontend gửi `POST /api/lookup` với `resource_id`
2. Backend chuẩn hóa resource ID và node bắt đầu nếu có
3. `ChordRing` route key qua closest preceding finger
4. Hệ thống trả về owner, path, hops, logs và replica node IDs
5. Frontend có thể gọi topology để highlight path vừa lookup

### Node failure

1. Frontend gửi `POST /api/kill` với `node_id`
2. Backend đánh dấu node inactive
3. Ring chạy recovery để đảm bảo resource còn bản hợp lệ
4. Finger table và topology được ổn định lại
5. State mới được persist

### Metrics

1. Frontend gửi `POST /api/metrics`
2. Backend chạy metric trên ring hiện tại
3. Backend dựng sweep từ 1 node tới số node active hiện có
4. Hệ thống đo average hops, latency mô phỏng và message overhead
5. Biểu đồ được lưu trong `static/metrics`
6. Payload metric gần nhất được cache để khôi phục sau refresh

## Cấu Trúc Thư Mục

```text
Final Source Code/
|-- app.py
|-- chord.py
|-- pyproject.toml
|-- requirements.txt
|-- README.md
|-- data/
|   |-- node_ids.json
|   |-- resource_ids.json
|   `-- state.json
|-- docs/
|   |-- analysis.md
|   |-- Topic 61.docx
|   |-- Topic 61.md
|   `-- project_proposal.md
|-- src/
|   `-- chord_dht/
|       |-- __init__.py
|       |-- chord.py
|       |-- identifiers.py
|       |-- metrics.py
|       |-- models.py
|       |-- ring.py
|       `-- visualization.py
|-- static/
|   |-- app.js
|   |-- busy.css
|   |-- style.css
|   `-- metrics/
|-- templates/
|   `-- index.html
`-- tests/
    |-- fixtures/
    `-- test_distributed_chord.py
```

## Cài Đặt

### Yêu cầu môi trường

- Python 3.10 trở lên
- pip
- Windows PowerShell hoặc terminal tương đương

### Cài đặt bằng virtual environment

```powershell
py -3.10 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Nếu không dùng editable install, có thể cài trực tiếp từ `requirements.txt`:

```powershell
python -m pip install -r requirements.txt
```

### Dependencies chính

| Package | Mục đích |
| --- | --- |
| Flask | Xây dựng web server và REST API |
| matplotlib | Sinh biểu đồ metric và topology |
| networkx | Dựng graph topology Chord |
| psutil | Hỗ trợ thu thập thông tin tiến trình nếu cần mở rộng |
| pytest | Chạy bộ test trong môi trường dev |

## Chạy Ứng Dụng

Khởi động server:

```powershell
.\.venv\Scripts\python.exe app.py
```

Mặc định ứng dụng chạy tại:

```text
http://127.0.0.1:5000
```

Có thể đổi host và port bằng biến môi trường:

```powershell
$env:HOST = "0.0.0.0"
$env:PORT = "8080"
.\.venv\Scripts\python.exe app.py
```

Sau khi server chạy, mở trình duyệt và truy cập URL tương ứng để sử dụng giao diện.

## Hướng Dẫn Sử Dụng

### Khởi tạo mạng

Trên giao diện, nhập số node, số resource, `m`, `seed` và số replica. Khi nhấn initialize, backend sẽ tạo lại ring mới và lưu state.

Ví dụ gọi API:

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:5000/api/initialize" `
  -ContentType "application/json" `
  -Body '{"nodes":50,"resources":1000,"m":16,"seed":61,"replication_count":3}'
```

### Lookup resource

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:5000/api/lookup" `
  -ContentType "application/json" `
  -Body '{"resource_id":"resource-1"}'
```

Kết quả lookup gồm key, owner, path, số hop, log định tuyến và danh sách replica.

### Thêm node

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:5000/api/node" `
  -ContentType "application/json" `
  -Body '{"node_id":12345}'
```

Nếu không truyền `node_id`, hệ thống sẽ tự sinh node ID mới.

### Mô phỏng node lỗi

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:5000/api/kill" `
  -ContentType "application/json" `
  -Body '{"node_id":12345}'
```

### Chạy metrics

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:5000/api/metrics" `
  -ContentType "application/json" `
  -Body '{"trials":5,"lookups":100}'
```

## API Endpoints

### Giao diện

| Method | Endpoint | Mô tả |
| --- | --- | --- |
| `GET` | `/` | Trả về giao diện web chính |

### State và resource

| Method | Endpoint | Mô tả |
| --- | --- | --- |
| `GET` | `/api/state` | Lấy snapshot trạng thái ring hiện tại |
| `GET` | `/api/resources` | Lấy toàn bộ resource đang được quản lý |
| `POST` | `/api/initialize` | Khởi tạo lại ring theo cấu hình truyền vào |

### Node

| Method | Endpoint | Mô tả |
| --- | --- | --- |
| `GET` | `/api/node/<node_id>` | Lấy chi tiết node, finger table và resource local |
| `POST` | `/api/node` | Thêm node mới hoặc kích hoạt node theo ID |
| `DELETE` | `/api/node/<node_id>` | Xóa node khỏi ring |
| `POST` | `/api/kill` | Mô phỏng node failure và chạy recovery |

### Resource

| Method | Endpoint | Mô tả |
| --- | --- | --- |
| `POST` | `/api/resource` | Thêm resource mới vào ring |
| `PUT` | `/api/resource` | Đổi resource ID bằng delete và put lại |
| `DELETE` | `/api/resource` | Xóa resource khỏi owner và replica |
| `POST` | `/api/lookup` | Lookup owner của resource và trả về trace |

### Metrics và topology

| Method | Endpoint | Mô tả |
| --- | --- | --- |
| `GET` | `/api/metrics` | Trả lỗi 405 để tránh chạy benchmark bằng GET |
| `POST` | `/api/metrics` | Chạy benchmark hiện tại và sweep tăng trưởng |
| `GET` | `/api/metrics/last` | Lấy metric đã lưu từ lần chạy gần nhất |
| `POST` | `/api/topology` | Sinh ảnh topology và tùy chọn highlight lookup path |

## Dữ Liệu Lưu Trữ

### `data/state.json`

File này lưu snapshot đầy đủ của hệ thống:

- `schema_version`
- Cấu hình ring như `m`, `seed`, `replication_count`
- Danh sách node, trạng thái active, predecessor, successor và finger table
- Danh sách resource, key, owner và replica
- Danh sách node lỗi
- Payload metric gần nhất nếu có

Ứng dụng dùng cơ chế ghi file tạm rồi replace file chính để giảm rủi ro ghi dở khi server đang hoạt động.

### `data/node_ids.json`

Lưu danh sách node ID ban đầu sau khi initialize. File này hữu ích cho báo cáo, kiểm thử và tái hiện topology.

### `data/resource_ids.json`

Lưu danh sách resource ID và hash tương ứng sau khi initialize. File này giúp đối chiếu resource key và owner.

## Metrics Và Visualization

### Chỉ số đo lường

| Metric | Ý nghĩa |
| --- | --- |
| `average_hops` | Số hop trung bình để lookup thành công |
| `max_hops` | Số hop lớn nhất trong các mẫu lookup |
| `average_latency_ms` | Độ trễ lookup mô phỏng theo millisecond |
| `message_overhead` | Tổng số message suy ra từ tổng số hop |
| `messages_per_lookup` | Số message trung bình cho mỗi lookup |
| `success_rate` | Tỷ lệ lookup thành công nếu payload có trường này |

### Biểu đồ sinh ra

Khi chạy metric, hệ thống lưu ảnh trong `static/metrics`:

- Biểu đồ average hops so với `log2(N)`
- Biểu đồ latency trung bình
- Biểu đồ message overhead
- Ảnh topology graph của ring

### Ý nghĩa thực nghiệm

Với Chord, số hop lookup kỳ vọng tăng xấp xỉ theo `log2(N)`. Vì vậy biểu đồ average hops được đặt cạnh đường tham chiếu `log2(N)` để kiểm tra hành vi định tuyến có phù hợp lý thuyết hay không.

## Kiểm Thử

Chạy toàn bộ test:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Chạy test với output chi tiết:

```powershell
.\.venv\Scripts\python.exe -m pytest -v
```

Chạy riêng file test chính:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_distributed_chord.py -v
```

Các nhóm test chính:

- Hash identifier nằm đúng trong không gian `2^m`
- Interval xử lý đúng trường hợp wraparound
- Endpoint initialize ghi state đúng schema
- Endpoint state autoload được dữ liệu persist
- Lookup trả về trace đường đi
- CRUD resource hoạt động đúng
- Node join, delete, kill và recovery cập nhật ring hợp lệ
- Finger table và resource ownership giữ tính nhất quán

## Ghi Chú Triển Khai

- Đây là mô phỏng single-process, không phải triển khai P2P thật trên nhiều máy
- Mỗi node được biểu diễn bằng object trong bộ nhớ thay vì process độc lập
- Latency trong metric là latency mô phỏng để phục vụ visualization
- State JSON phục vụ demo và kiểm thử nhanh, chưa thay thế cho storage bền vững trong môi trường production
- Flask app mặc định chạy `debug=False`

## Thuật Ngữ

| Thuật ngữ | Giải thích |
| --- | --- |
| Node | Peer trong mạng Chord |
| Ring | Vòng định danh kích thước `2^m` |
| Key | Giá trị hash của resource trong vòng định danh |
| Owner | Node chịu trách nhiệm chính cho một key |
| Successor | Node active đầu tiên đứng sau một ID trên vòng |
| Predecessor | Node active đứng trước một node trên vòng |
| Finger table | Bảng định tuyến giúp lookup nhanh theo bước nhảy lũy thừa |
| Lookup path | Danh sách node mà truy vấn đi qua |
| Replica | Bản sao resource được lưu trên successor node |
| Stabilization | Quá trình cập nhật successor, predecessor và finger table sau thay đổi topology |

## Tài Liệu Liên Quan

- `docs/analysis.md`: phân tích và đánh giá hệ thống
- `docs/project_proposal.md`: đề xuất ban đầu của dự án
- `docs/Topic 61.md`: nội dung đề tài và yêu cầu liên quan
- `tests/test_distributed_chord.py`: các kịch bản kiểm thử chính
