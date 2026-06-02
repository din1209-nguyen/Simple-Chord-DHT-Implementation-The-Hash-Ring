# Simple Chord DHT Implementation

Ứng dụng web mô phỏng **Chord Distributed Hash Table (DHT)** cho đề tài **Simple Chord DHT Implementation**. Dự án minh họa cách node và resource được ánh xạ vào vòng định danh, cách lookup dùng finger table, cách node join/failure ảnh hưởng tới topology, và cách replication giúp phục hồi dữ liệu khi node lỗi.

> Đây là mô phỏng single-process phục vụ học tập và demo. Mỗi node là một object trong bộ nhớ, không phải một process/máy độc lập trong mạng P2P thật.

## Thông Tin Dự Án

| Mục | Nội dung |
| --- | --- |
| Chủ đề | Simple Chord DHT Implementation |
| Môn học | Cơ Sở Dữ Liệu Phân Tán |
| Ngôn ngữ | Python, JavaScript, HTML, CSS |
| Backend | Flask |
| Visualization | Matplotlib, NetworkX |
| Kiểu triển khai | Single-process Chord simulator |

## Tính Năng Chính

- Khởi tạo Chord ring với số node, số resource, `m`, `seed` và `replication_count`.
- Hash node/resource vào cùng không gian định danh `2^m`.
- Xác định owner của resource theo quy tắc `successor(resource_key)`.
- Hiển thị `successor`, `predecessor`, finger table và local resource của từng node.
- Lookup resource bằng Chord routing và `closest preceding finger`.
- Thêm node mới và rebalance đúng khoảng key bị ảnh hưởng.
- Kill node để mô phỏng failure, hiển thị impact trước recovery.
- Recover node failure bằng cách sửa ring, sửa finger table, promote primary từ replica sống và đặt lại replica.
- Hiển thị topology, lookup path, resource distribution và metrics.
- Lưu trạng thái ring vào `data/state.json` để autoload sau khi restart server.

## Lý Thuyết Chord Được Mô Phỏng

### Vòng định danh

Chord dùng không gian định danh dạng vòng:

```text
identifier_space = 2^m
```

Với cấu hình thường dùng `m = 16`, ID nằm trong khoảng:

```text
0 -> 65535
```

Node ID và resource key được sinh bằng SHA-1 rồi rút gọn vào không gian `2^m`:

```text
node_id      = SHA1(...) mod 2^m
resource_key = SHA1(resource_id) mod 2^m
```

### Seed

`seed` giúp kết quả random có thể tái lập. Nếu dùng cùng một seed, danh sách node ID/resource ID sinh ra sẽ giống nhau giữa các lần chạy. Điều này giúp demo và debug ổn định, ví dụ lỗi ở node `18652` có thể tái hiện lại chính xác.

### Owner Của Resource

Resource được lưu chính tại node `successor(resource_key)`:

```text
owner(resource) = successor(resource_key)
```

`successor(key)` là node active đầu tiên theo chiều kim đồng hồ có ID lớn hơn hoặc bằng key. Nếu không có node nào lớn hơn key, kết quả quay vòng về node nhỏ nhất.

Ví dụ:

```text
active nodes = [18652, 19570, 24076, 30016, 37252]
resource_key = 26844
owner = 30016
```

### Khoảng Sở Hữu Của Node

Một node `n` sở hữu các key nằm trong khoảng:

```text
(predecessor(n), n]
```

Ví dụ node `3265` có predecessor là `60689`, thì khoảng sở hữu là:

```text
(60689, 3265]
```

Khoảng này wrap qua 0, nên key `1202` thuộc về node `3265`.

### Finger Table

Mỗi node có `m` dòng finger table. Với node `n`, dòng thứ `i` được tính:

```text
start_i = (n + 2^(i - 1)) mod 2^m
end_i   = (n + 2^i) mod 2^m
node_i  = successor(start_i)
```

Finger table không chọn node ngẫu nhiên. Mỗi dòng đại diện cho một bước nhảy theo lũy thừa của 2, giúp lookup đi nhanh hơn thay vì duyệt từng successor.

Ví dụ với node `18652`, `m = 16`:

```text
finger #14:
start = 18652 + 2^13 = 26844
node  = successor(26844)
```

Nếu node active đầu tiên sau `26844` là `30016`, thì finger #14 phải trỏ tới `30016`.

### Lookup

Lookup dùng finger table để định tuyến tới owner:

```text
1. Bắt đầu từ một node active.
2. Nếu key thuộc (predecessor(current), current], current là owner.
3. Nếu key thuộc (current, successor], successor là owner.
4. Nếu chưa tới owner, chọn closest preceding finger gần key nhất.
5. Lặp lại cho tới khi tìm được owner.
```

Điểm quan trọng:

- `closest_preceding_finger` dùng cho quá trình lookup/routing.
- Finger table được tính bằng `successor(start)`.
- Verify finger table cũng so với `successor(start)`, không dùng route để tránh che lỗi khi bảng đang stale.

## Replication

Mỗi resource có:

```text
owner_id
replica_node_ids
```

Owner là node chính. Replica được đặt trên các successor kế tiếp của owner, không trùng owner.

Ví dụ:

```text
owner = 30016
successor chain = 30016 -> 37252 -> 51502
replication_count = 2
replica_node_ids = [37252, 51502]
```

Nếu `replication_count` lớn hơn số node có thể đặt replica, hệ thống dùng `effective_replica_count`:

```text
effective_replica_count = min(replication_count, active_nodes - 1)
```

## Node Join

Khi thêm node mới:

```text
1. Node mới được gán node_id.
2. Node được chèn vào đúng vị trí trên vòng.
3. Successor/predecessor được stabilize lại.
4. Finger table chạy protocol tới khi stable.
5. Resource thuộc khoảng (predecessor(new_node), new_node] chuyển sang node mới.
6. Replica placement được tính lại.
```

Ý nghĩa lý thuyết: nhờ consistent hashing, node join không làm phân phối lại toàn bộ dữ liệu, chỉ các key trong khoảng node mới chịu trách nhiệm bị ảnh hưởng.

## Node Failure Và Recovery

Flow failure trong dự án được tách thành hai bước để dễ demo.

### 1. Kill Node

Khi bấm **Kill**, node được đánh dấu inactive và thêm vào `failed_nodes`. Hệ thống chưa phục hồi ngay, mà hiển thị impact:

- Failed node.
- Old predecessor và old successor.
- Các finger entry đang trỏ tới failed node.
- Primary resource do failed node làm owner.
- Replica resource đang đặt trên failed node.

Node failed không còn được xem là nguồn dữ liệu tin cậy.

### 2. Recover

Khi bấm **Recover**, hệ thống thực hiện:

```text
1. Xác nhận node failed.
2. Nối old predecessor với old successor để vá ring.
3. Sửa finger table đang trỏ tới node chết bằng successor(entry.start).
4. Với primary resource bị ảnh hưởng, promote từ replica còn sống.
5. Với replica resource bị ảnh hưởng, loại replica chết và đặt replica mới.
6. Dọn metadata resource bị mất nếu không còn bản copy active.
```

Nếu primary resource không còn replica sống, resource được xem là lost.

## Protocol Tick Và Stabilization

Dự án có hai hàm chính để mô phỏng protocol Chord:

```text
run_protocol_tick()
run_protocol_until_stable()
```

Một tick thực hiện trên toàn bộ node active:

```text
1. stabilize_one(node)
2. check_predecessor_one(node)
3. fix_fingers_one(node)
```

Mỗi tick chỉ sửa một dòng finger table trên mỗi node. Vì finger table có `m` dòng, `run_protocol_until_stable()` chạy tối thiểu `m` tick để quét đủ một vòng finger table, rồi dừng khi routing snapshot không còn thay đổi.

## Kiến Trúc

```text
Browser
  |
  | REST API
  v
app.py
  |
  | Flask routes, validation, state persistence
  v
ChordRing
  |
  | Chord protocol, lookup, join, failure, replication
  v
src/chord_dht/*
  |
  | JSON state + generated metric/topology images
  v
data/* + static/*
```

| Thành phần | Vai trò |
| --- | --- |
| `app.py` | Flask server, API, persist state, điều phối metrics/topology |
| `src/chord_dht/chord.py` | Lớp `ChordRing`, core Chord logic, lookup, join, recovery, replication |
| `src/chord_dht/models.py` | `Node`, `FingerEntry`, `ResourceRecord`, `LookupResult` |
| `src/chord_dht/identifiers.py` | Hash ID và kiểm tra interval trên vòng Chord |
| `src/chord_dht/metrics.py` | Benchmark lookup và dữ liệu metrics |
| `src/chord_dht/visualization.py` | Sinh topology graph |
| `templates/index.html` | Giao diện chính |
| `static/app.js` | Logic frontend và render UI |
| `tests/test_distributed_chord.py` | Test API và logic Chord |

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
|   `-- style.css
|-- templates/
|   `-- index.html
`-- tests/
    |-- fixtures/
    `-- test_distributed_chord.py
```

## Cài Đặt

Yêu cầu:

- Python 3.10 trở lên
- pip
- Windows PowerShell hoặc terminal tương đương

Cách khuyến nghị trên Windows là chạy script tự tạo môi trường ảo, cài dependency và mở server:

```powershell
powershell -ExecutionPolicy Bypass -File .\run.ps1
```

Trên macOS/Linux:

```bash
chmod +x ./run.sh
./run.sh
```

Script sẽ tự tạo `.venv` trong thư mục dự án nếu chưa có. Không dùng lại thư mục `venv`/`.venv` copy từ máy khác vì đường dẫn Python trong virtual environment thường phụ thuộc từng máy.

Cài thủ công bằng virtual environment trên Windows:

```powershell
py -3.10 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Cài thủ công trên macOS/Linux:

```bash
python3 -m venv .venv
. ./.venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Hoặc cài từ `requirements.txt` sau khi đã activate `.venv`:

```powershell
python -m pip install -r requirements.txt
```

## Chạy Ứng Dụng

Nếu dùng script:

```powershell
powershell -ExecutionPolicy Bypass -File .\run.ps1
```

Nếu đã cài thủ công trên Windows:

```powershell
.\.venv\Scripts\python.exe app.py
```

Nếu đã cài thủ công trên macOS/Linux:

```bash
./.venv/bin/python app.py
```

Mặc định server chạy tại:

```text
http://127.0.0.1:5000
```

Có thể đổi host/port:

```powershell
$env:HOST = "0.0.0.0"
$env:PORT = "8080"
.\.venv\Scripts\python.exe app.py
```

Trên macOS/Linux:

```bash
HOST=0.0.0.0 PORT=8080 ./.venv/bin/python app.py
```

## API Chính

### State Và Resource

| Method | Endpoint | Mô tả |
| --- | --- | --- |
| `GET` | `/` | Giao diện web |
| `GET` | `/api/state` | Lấy trạng thái ring hiện tại |
| `GET` | `/api/resources` | Lấy danh sách resource |
| `POST` | `/api/initialize` | Khởi tạo lại ring |

### Node

| Method | Endpoint | Mô tả |
| --- | --- | --- |
| `GET` | `/api/node/<node_id>` | Chi tiết node, finger table và local resources |
| `POST` | `/api/node` | Thêm node mới |
| `DELETE` | `/api/node/<node_id>` | Xóa node khỏi ring |
| `POST` | `/api/kill` | Đánh dấu node failed và trả về impact |
| `POST` | `/api/recover` | Recover node failed |

### Resource

| Method | Endpoint | Mô tả |
| --- | --- | --- |
| `POST` | `/api/resource` | Thêm resource |
| `PUT` | `/api/resource` | Đổi resource ID |
| `DELETE` | `/api/resource` | Xóa resource |
| `POST` | `/api/lookup` | Lookup resource và trả về trace |

### Metrics Và Topology

| Method | Endpoint | Mô tả |
| --- | --- | --- |
| `GET` | `/api/metrics` | Trả 405 để tránh chạy benchmark bằng GET |
| `POST` | `/api/metrics` | Chạy benchmark metrics |
| `GET` | `/api/metrics/last` | Lấy metrics gần nhất |
| `POST` | `/api/topology` | Sinh topology graph |

## Ví Dụ Gọi API

Khởi tạo ring:

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:5000/api/initialize" `
  -ContentType "application/json" `
  -Body '{"nodes":50,"resources":1000,"m":16,"seed":61,"replication_count":1}'
```

Lookup resource:

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:5000/api/lookup" `
  -ContentType "application/json" `
  -Body '{"resource_id":"resource-0010"}'
```

Kill node:

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:5000/api/kill" `
  -ContentType "application/json" `
  -Body '{"node_id":9213}'
```

Recover node:

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:5000/api/recover" `
  -ContentType "application/json" `
  -Body '{"node_id":9213}'
```

## Dữ Liệu Lưu Trữ

| File | Mô tả |
| --- | --- |
| `data/state.json` | Snapshot đầy đủ của ring, nodes, resources, failed nodes và metrics gần nhất |
| `data/node_ids.json` | Danh sách node ID sinh ra khi initialize |
| `data/resource_ids.json` | Danh sách resource ID/hash/key sinh ra khi initialize |

Khi autoload state, nếu không có failed node đang pending recovery, hệ thống chạy protocol để hội tụ lại routing/finger table từ snapshot đã lưu.

## Metrics

Metrics dùng để quan sát hành vi lookup:

| Metric | Ý nghĩa |
| --- | --- |
| `average_hops` | Số hop trung bình |
| `max_hops` | Số hop lớn nhất |
| `average_latency_ms` | Latency mô phỏng |
| `message_overhead` | Tổng message suy ra từ lookup |
| `messages_per_lookup` | Message trung bình trên mỗi lookup |
| `success_rate` | Tỷ lệ lookup thành công |

Về lý thuyết, Chord lookup kỳ vọng khoảng `O(log N)`, nên biểu đồ average hops được so với `log2(N)`.

## Kiểm Thử

Chạy toàn bộ test:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Chạy file test chính:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_distributed_chord.py -v
```

Trên macOS/Linux thay `.\.venv\Scripts\python.exe` bằng `./.venv/bin/python`.

Lưu ý: nếu môi trường thiếu `matplotlib`, pytest sẽ lỗi ở bước import `chord_dht.metrics`. Cài lại dependency trong đúng `.venv` của dự án bằng `python -m pip install -e ".[dev]"` hoặc `python -m pip install -r requirements.txt`.

Nhóm test chính:

- Hash ID nằm đúng trong không gian `2^m`.
- Interval xử lý đúng wraparound.
- Initialize ghi state đúng.
- Lookup trả về owner/path/log.
- Node join rebalance đúng khoảng key.
- Kill/Recover sửa ring, finger table và resource placement.
- Finger table đúng công thức `successor(start)`.
- Resource owner đúng công thức `successor(key)`.

## Luồng Demo Gợi Ý

1. Initialize mạng với 50 node, 1000 resource, `m = 16`, `seed = 61`.
2. Mở một node để giải thích predecessor, successor và finger table.
3. Lookup `resource-0010`, chỉ path, hops và log.
4. Thêm node mới, giải thích chỉ một khoảng key bị rebalance.
5. Kill một node, chỉ impact report: primary affected, replica affected, stale fingers.
6. Bấm Recover, giải thích vá ring, sửa finger, promote từ replica và đặt lại replica.
7. Chạy metrics để so average hops với `log2(N)`.

## Thuật Ngữ

| Thuật ngữ | Giải thích |
| --- | --- |
| Node | Peer trong mạng Chord |
| Ring | Vòng định danh kích thước `2^m` |
| Key | ID hash của resource |
| Owner | Node chịu trách nhiệm chính cho resource |
| Successor | Node active đầu tiên sau một ID theo chiều kim đồng hồ |
| Predecessor | Node active đứng trước một node |
| Finger table | Bảng định tuyến gồm các mốc nhảy lũy thừa của 2 |
| Lookup path | Các node mà truy vấn đi qua |
| Replica | Bản sao resource trên successor node |
| Stabilization | Quá trình cập nhật successor, predecessor và finger table |
| Failed node | Node inactive do Kill và đang chờ/đã recovery |
| Retired node | Node đã bị loại khỏi routing sau recovery |
