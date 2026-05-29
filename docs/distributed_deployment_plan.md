# Kế Hoạch Triển Khai Chord DHT Đa Node

Tài liệu này ghi nhận thiết kế đã được triển khai cho chế độ nộp bài chính.
Các peer HTTP độc lập giao tiếp qua Chord routing mà không có bộ định tuyến tập trung.

## Kiến Trúc Đã Triển Khai

| Nội dung | Cài đặt |
| --- | --- |
| Số node | `50` process node, tối đa `100` |
| Địa chỉ | `127.0.0.1:<base_port + i>`, mặc định từ `5100` |
| Identity | `SHA1("127.0.0.1:<port>") mod 2^m` |
| Giao tiếp | HTTP/REST JSON giữa các peer |
| Lưu trữ | `data/nodes/node_<node_id>.json` riêng cho từng peer |
| Facade | `app.py`/`DistributedCoordinator` quản lý process và UI snapshot |

```text
Browser -> Coordinator :5000 -> entry node :5100
                                  | HTTP Chord routing
                                  v
                       successor/finger node :51xx -> owner JSON
```

Coordinator không tra owner và không đọc JSON node để định tuyến. `ChordNode`
chỉ biết identity của mình, neighbor, successor list, Finger Table và resource
cục bộ.

## API Peer

| Endpoint | Mục đích |
| --- | --- |
| `GET /health`, `GET /state` | Quan sát identity và state cục bộ |
| `GET /links` | Chia sẻ neighbor phục vụ protocol mà không lộ resource |
| `POST /ring/create`, `POST /join` | Tạo vòng hoặc gia nhập qua bootstrap |
| `POST /find-successor` | Forward route với trace/loop guard |
| `GET /predecessor`, `POST /notify` | Stabilization protocol |
| `POST /maintenance/stabilize` | Kiểm tra successor và notify |
| `POST /maintenance/fix-finger` | Sửa finger qua lookup |
| `POST /maintenance/check-predecessor` | Phát hiện peer chết |
| `POST /maintenance/recover` | Promote replica nếu ownership chuyển |
| `POST /resources/put`, `/resources/get` | CRUD định tuyến |
| `POST /resources/put-batch` | Entry peer tự route dataset ban đầu |
| `POST /replicas`, `DELETE /replicas/<id>` | Replica cục bộ |

## Persistence Và Churn

`JsonNodeStore` khóa ghi, ghi state bằng file tạm và atomic replace. Mỗi process
tự chạy maintenance định kỳ. `Initialize` dọn
state JSON node cũ trong thư mục deployment được chọn. `Stop Node` terminate
process thật; `Restart Node` chạy lại cùng endpoint và đọc JSON persisted.

Primary được sao chép tới số successor cấu hình. Ghi primary thành công nhưng
thiếu replica được báo `degraded`. Khi owner ngừng phản hồi, successor mới chỉ
có thể promote dữ liệu nếu chính nó còn replica; nếu không còn bản sao sống,
resource được trả là unavailable/lost.

## Đánh Giá

Để lập bảng báo cáo cuối, dựng từng deployment `N = 10, 20, 30, 40, 50` và
đo lookup HTTP thật: average/max hops, HTTP messages, local latency, success
rate, degraded/lost resource sau failure. Mọi kết quả dùng trong báo cáo được
đo từ deployment process đang chạy.
