# Báo Cáo Phân Tích Thiết Kế

**Dự án:** Simple Chord DHT Implementation: *The Hash Ring*  
**Chủ đề:** #61 - Peer-to-Peer Data Management / Chord Distributed Hash Table

## 1. Luận Điểm Chính

Dự án dùng Chord vì Topic 61 yêu cầu một mạng P2P có cấu trúc, nơi resource
được đặt và tìm bằng quy tắc phân tán thay vì flooding hoặc directory trung
tâm. Bản triển khai chính chạy trên localhost nhưng là multi-process thật: mỗi
peer có HTTP endpoint và JSON riêng.

Phân biệt quan trọng:

- Coordinator quản lý process và snapshot hiển thị.
- Node Chord quyết định route bằng state cục bộ và message HTTP.
- Không tồn tại core tập trung trả lời owner; tất cả kết quả định tuyến đến từ
  các endpoint peer.

## 2. Đối Chiếu Topic 61

| Yêu cầu | Hiện thực distributed |
| --- | --- |
| `10-50` node / tối đa 50 `Node_IDs` | Mỗi node là `node_server.py` ở port riêng |
| 1.000 `Resource_IDs` | Coordinator gửi dataset vào entry node; owner do route trả về |
| SHA-1 | Node ID băm từ `127.0.0.1:<port>`; resource key băm từ ID |
| Finger Table | Mỗi `ChordNode` duy trì table cục bộ |
| Lookup `O(log N)` | Node forward tới closest preceding finger/successor |
| Churn | Stop process, stabilize/notify/fix finger, promote replica |
| Peer independence | Node chỉ đọc/ghi file JSON của chính nó |

## 3. Placement Và Routing

Node và resource chia sẻ không gian định danh:

```text
node_id = SHA1("127.0.0.1:<port>") mod 2^m
key     = SHA1(resource_id) mod 2^m
owner   = successor(key)
```

Quy tắc successor làm mỗi node chịu trách nhiệm cho khoảng:

```text
(predecessor(node), node]
```

Nó có ba ích lợi: owner được xác định ổn định khi topology không đổi, không cần
bảng `resource -> owner` tập trung, và khi join/leave chỉ vùng key lân cận cần
đổi owner.

Node chỉ biết neighbor và fingers cần thiết. Finger thứ `i` bắt đầu tại:

```text
start_i = (node_id + 2^(i-1)) mod 2^m
finger_i = successor(start_i)
```

Lookup bắt đầu ở một entry node và mang trace qua từng request HTTP. Tại mỗi
hop, node chọn successor nếu key ở khoảng gần kế tiếp; nếu không, nó forward
tới closest preceding finger. `visited_nodes` và giới hạn hop ngăn vòng lặp khi
routing state đang hội tụ.

## 4. Vì Sao Kỳ Vọng O(log N)

Nếu chỉ đi từng successor, đường đi trường hợp xấu gần `O(N)`. Finger Table đặt
các shortcut theo lũy thừa của hai. Trong trạng thái ổn định, closest preceding
finger thường giảm đáng kể khoảng cách logic còn lại tới owner. Sau `h` hop,
số ứng viên còn lại có xu hướng:

```text
N / 2^h
```

Lookup kết thúc khi giá trị này xấp xỉ một, nên:

```text
h ≈ log2(N)
```

Báo cáo thực nghiệm cần xác nhận xu hướng này bằng trace HTTP thật tại
`N = 10, 20, 30, 40, 50`, đo trực tiếp latency HTTP giữa các process.

## 5. Join Và Stabilization

Node mới không nhận topology đầy đủ từ coordinator. Nó chỉ nhận một bootstrap
endpoint và gọi `find-successor(node_id)` để thiết lập successor ban đầu.

Sau đó giao thức hội tụ như sau:

1. `stabilize` hỏi predecessor của successor.
2. Nếu ứng viên nằm giữa node hiện tại và successor, node cập nhật successor.
3. Node gửi `notify` để successor xem xét cập nhật predecessor.
4. `fix_fingers` tìm successor cho từng start position bằng route Chord.
5. `check_predecessor` và successor list phát hiện/failover endpoint chết.

Mỗi process tự chạy các nhịp này định kỳ; coordinator còn kích hoạt thêm sau
thao tác UI để demo nhanh hội tụ, nhưng không tự chọn successor hoặc sửa finger
cho peer.

## 6. Persistence, Replication Và Failure

Mỗi node lưu một file JSON gồm routing state, primary và replica cục bộ.
`JsonNodeStore` sử dụng atomic replace để tránh state dở dang nếu process bị
dừng trong lúc ghi.

Khi `put`:

1. Request được route qua HTTP đến owner.
2. Owner ghi primary cục bộ.
3. Owner gửi replica tới các successor theo cấu hình.
4. Nếu thiếu replica, primary vẫn thành công nhưng trạng thái là `degraded`.

Khi owner bị `Stop Node`:

1. Process thực sự ngừng phản hồi.
2. Neighbor còn sống phát hiện lỗi và stabilize.
3. Node trở thành owner mới kiểm tra replica cục bộ.
4. Nếu có replica, node promote thành primary và sửa replica set.
5. Nếu không có replica sống, lookup báo unavailable/lost.

Điều này tách rõ routing correctness khỏi data availability: tìm được owner mới
không đồng nghĩa dữ liệu còn tồn tại.

## 7. Metrics Và Bằng Chứng

Mỗi lần lookup distributed có thể báo cáo:

| Chỉ số | Ý nghĩa |
| --- | --- |
| Average/max hops | Số bước forward HTTP quan sát được |
| HTTP message overhead | Tổng hop routing trong mẫu đo |
| Local HTTP latency | Thời gian request thực giữa các process localhost |
| Success rate | Tỷ lệ resource còn đọc được tại owner |
| Degraded/lost count | Tác động availability của failure |

Quy trình báo cáo đề xuất:

1. Initialize riêng từng deployment `N = 10, 20, 30, 40, 50`, giữ cùng `m`,
   resource count và replication count.
2. Chạy lookup đủ mẫu trên mỗi deployment qua API/UI.
3. Ghi hops, HTTP latency và success rate.
4. Stop một owner, ghi số resource promote/lost và chạy lookup lại.
5. Restart endpoint, xác nhận identity và JSON persisted.

## 8. Bằng Chứng Trong Mã Và Test

Các module chính:

- `distributed_node.py`: thuật toán node-local và HTTP forwarding qua `/links`.
- `coordinator.py`: process lifecycle và snapshot quan sát.
- `storage.py`: persistence JSON atomic.
- `node_server.py`: REST API của từng peer.
- `app.py`: facade của UI.

Integration test dựng deployment process thật và kiểm tra Node ID từ endpoint,
file JSON riêng, peer không đọc `/state` của nhau, lookup HTTP, recovery sau
stop owner và restart cùng identity.

## 9. Kết Luận

Bản triển khai đáp ứng bản chất của Chord DHT: resource placement dựa trên
successor, routing dùng fingers cục bộ, maintenance diễn ra qua message peer,
và failure không được che giấu bởi metadata trung tâm. Đây là nền tảng hợp lý
để phân tích xu hướng `O(log N)` và đánh giá availability khi churn.

## Tài Liệu Tham Khảo

- Ion Stoica et al., *Chord: A Scalable Peer-to-Peer Lookup Service for Internet Applications*, [MIT PDOS](https://pdos.csail.mit.edu/6.824/papers/stoica-chord.pdf).
- M. T. Özsu và P. Valduriez, *Principles of Distributed Database Systems*, phần structured P2P/DHT.
- `docs/design_document.md` và `docs/project_proposal.md`.
