# Tài Liệu Thiết Kế Hệ Thống

**Dự án:** Simple Chord DHT Implementation: *The Hash Ring*  
**Chủ đề:** #61 - Peer-to-Peer Data Management / Chord DHT

## 1. Mục Tiêu

Hệ thống cài đặt một overlay Chord thực trên localhost. Mỗi peer chạy như một
process HTTP riêng, định tuyến bằng routing state cục bộ và lưu dữ liệu trong
JSON cục bộ. Thiết kế này cho phép chứng minh peer independence: việc một node
dừng không biến thành thao tác sửa một object ring toàn cục.

Phạm vi demo hỗ trợ `10-50` node, lookup đa hop, join/stop/restart, replication,
failure recovery, topology và metric từ request HTTP thực.

## 2. Phân Tách Vai Trò

```text
UI -> Coordinator app.py -> entry node HTTP -> peer HTTP -> owner
                              |                 |
                              v                 v
                         node_<id>.json    node_<id>.json
```

`DistributedCoordinator`:

- khởi chạy, stop và restart `node_server.py`;
- giữ registry quản trị endpoint/PID/JSON path/health;
- gửi yêu cầu người dùng vào một entry node đang sống;
- đọc `/state` để tổng hợp UI, graph và metrics.

Coordinator không tìm successor, không giữ `resource_id -> owner` phục vụ
routing và không đọc file JSON peer để quyết định thuật toán.

`ChordNode`:

- giữ `predecessor`, `successor`, `successor_list` và `finger_table`;
- định tuyến `find-successor`, put/get/delete qua HTTP;
- chạy `join`, `notify`, `stabilize`, `fix_fingers`, health check;
- sở hữu primary/replica và ghi duy nhất file JSON của chính nó.

Runtime chỉ có mô hình node-per-port; không tồn tại core ring tập trung để trả
kết quả thay cho peer.

## 3. Identity Và State

Với endpoint `127.0.0.1:<port>`:

```text
node_id = SHA1("127.0.0.1:<port>") mod 2^m
key     = SHA1(resource_id) mod 2^m
```

Nếu hai endpoint va chạm `node_id`, initialize/join báo lỗi để người dùng đổi
`base_port` hoặc `m`. UI không cho sửa trực tiếp Node ID.

State JSON tối thiểu:

```text
NodeReference: node_id, host, port, endpoint
FingerEntry: index, start, interval_end, node
StoredResource: resource_id, key, role, owner, replica_nodes, degraded_replication
NodeState: self_reference, predecessor, successor, successor_list,
           finger_table, primary_resources, replica_resources, updated_at
```

Mỗi peer lưu `data/nodes/node_<node_id>.json`. `JsonNodeStore` ghi file tạm
trong cùng thư mục rồi atomic replace file đích. Restart cùng port đọc lại file
cũ; initialize mới dọn state node thuộc thư mục deployment đã chọn.

## 4. Routing Và Maintenance

Owner của key là successor đầu tiên theo chiều kim đồng hồ. Node `n` duy trì
finger:

```text
start_i = (n + 2^(i-1)) mod 2^m
finger_i = successor(start_i)
```

`find-successor` chỉ dùng predecessor/successor/fingers cục bộ. Peer lấy
neighbor list qua `/links`, endpoint không chứa primary/replica; `/state` chỉ
dành cho coordinator/UI. Payload route mang
`trace_id`, visited endpoints, hop count và log để phát hiện vòng lặp và hiển
thị HTTP path thực.

Luồng maintenance:

1. `join`: node mới hỏi một bootstrap để tìm successor của identity mình.
2. `stabilize`: node hỏi predecessor của successor, cập nhật nếu ứng viên nằm
   giữa hai node, sau đó gửi `notify`.
3. `fix_fingers`: mỗi lần cập nhật entry bằng lookup qua overlay.
4. `check_predecessor`: bỏ predecessor không phản hồi.
5. `successor_list`: dùng successor còn sống để failover khi neighbor chết.

Mỗi `node_server.py` chạy một vòng maintenance nền định kỳ. Coordinator cũng có
thể kích hoạt nhiều chu kỳ sau thao tác UI để demo hội tụ sớm, nhưng mỗi quyết
định vẫn do node-local HTTP protocol thực hiện.

## 5. Resource Và Failure

`put` route tới owner, ghi primary JSON trước rồi gửi replica tới các successor.
Nếu thiếu replica, resource vẫn committed nhưng báo `degraded_replication`.

Khi process owner dừng:

- peer còn sống phát hiện neighbor timeout và stabilize;
- successor mới kiểm tra replica cục bộ của mình;
- replica đúng khoảng ownership được promote thành primary;
- primary mới gửi lại replica tới successor sống tiếp theo;
- nếu không còn bản sao, lookup báo unavailable/lost.

`Stop Node` dừng process thật. `Restart Node` dùng cùng port và JSON, do đó
identity không đổi.

## 6. API Và UI

Node API chính:

| Endpoint | Mục đích |
| --- | --- |
| `GET /health`, `GET /state` | Health và state cục bộ |
| `GET /links` | Neighbor metadata phục vụ peer protocol, không lộ resource |
| `POST /join`, `/find-successor`, `/notify` | Giao thức routing/join |
| `POST /maintenance/*` | Stabilize, fix finger, recovery |
| `POST /resources/put`, `/resources/get`, `DELETE /resources/<id>` | CRUD route |
| `POST /resources/put-batch` | Nạp dataset tại entry peer rồi route tới owner |
| `POST /replicas`, `DELETE /replicas/<id>` | Lưu/xóa replica cục bộ |

UI hiển thị endpoint, JSON path, trạng thái `Running/Stopped/Unreachable`,
local predecessor/successor/Finger Table, primary/replica, HTTP trace, latency,
topology và recovery report.

## 7. Kiểm Thử Và Đo Lường

Test integration khởi chạy process node thật và kiểm tra:

- identity sinh đúng từ endpoint;
- mỗi node tạo file JSON riêng;
- lookup đi qua node endpoint và trả path;
- stop owner vẫn tìm được dữ liệu khi replica còn sống;
- restart giữ identity và state JSON persisted.

Khi viết báo cáo kết quả, khởi tạo lần lượt `N = 10, 20, 30, 40, 50` và thu
thập average/max hops, HTTP message overhead, local HTTP latency, success rate,
degraded/lost resources. Chỉ kết quả từ request HTTP multi-process được dùng
làm bằng chứng đánh giá.
