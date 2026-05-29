# Đề Xuất Dự Án Cơ Sở Dữ Liệu Phân Tán

**Hạn nộp:** Tuần 3 - nhóm tự điền ngày nộp chính xác  
**Mã dự án & Danh mục:** #61: Simple Chord DHT Implementation - Category 7

## 1. Thông Tin Dự Án

**Tên nhóm:** The Hash Ring  
**Thành viên nhóm:** Nguyễn Đông Din  
**Tên dự án:** Simple Chord DHT Implementation: The Hash Ring

## 2. Mục Tiêu & Phát Biểu Bài Toán

**Lý do thực hiện:**  
Dự án giải quyết bài toán định vị dữ liệu trong môi trường cơ sở dữ liệu phân tán ngang hàng P2P. Các mạng P2P không cấu trúc thường cho phép peer kết nối và đặt dữ liệu khá tự do. Cách tiếp cận này đơn giản và linh hoạt, nhưng khi số lượng node tăng lên, việc tìm kiếm tài nguyên thường phải dựa vào cơ chế gần giống flooding, random walk hoặc quét nhiều peer. Hệ quả là chi phí tìm kiếm khó dự đoán, số message có thể tăng nhanh, và hệ thống khó chứng minh được tính mở rộng.

Ngược lại, mạng P2P có cấu trúc kiểm soát chặt chẽ hai yếu tố: topology của overlay network và vị trí đặt resource. Đổi lại, mỗi peer mất một phần quyền tự chủ vì dữ liệu không được đặt tùy ý, mà phải tuân theo quy tắc của hệ thống. Tuy nhiên, sự đánh đổi này giúp hệ thống có khả năng mở rộng tốt hơn và có thể định tuyến truy vấn theo một thuật toán rõ ràng.

Vì vậy, dự án chọn Chord DHT để triển khai một mạng P2P có cấu trúc trên localhost. Thay vì hỏi toàn bộ node hoặc dùng một node trung tâm để tra cứu, Chord đặt node và resource vào cùng một vòng định danh. Resource được tìm thông qua key đã băm và routing protocol giữa các endpoint peer. Cách này bám sát mục tiêu trong lý thuyết: giải quyết hai vấn đề cốt lõi của structured P2P là resource được đánh chỉ mục như thế nào và resource được tìm kiếm như thế nào.

Thách thức chính của dự án gồm ba phần. Thứ nhất, ánh xạ `Resource_ID` thành key và xác định node chịu trách nhiệm mà không dùng bảng tập trung. Thứ hai, định tuyến truy vấn qua nhiều peer với số hop nhỏ bằng Finger Table. Thứ ba, duy trì routing state nhất quán khi có node rời mạng, vì nếu predecessor, successor hoặc finger pointer bị sai, lookup có thể đi nhầm hoặc thất bại.

**Logic cốt lõi:**  
Dự án cài đặt giao thức Chord DHT dựa trên consistent hashing và vòng định danh. Theo lý thuyết, DHT cung cấp mô hình logic gần với hai thao tác:

```text
put(key, data)
get(key)
```

Trong dự án, `put` là request HTTP được forward tới successor chịu trách nhiệm cho `Resource_Key`; node owner ghi primary JSON cục bộ và gửi replica. `get` băm lại `Resource_ID` hoặc nhận key trực tiếp, rồi định tuyến request tới node owner qua các finger/successor cục bộ.

Node và resource đều được băm vào cùng một không gian định danh `m` bit. Mỗi resource được gán cho node active đầu tiên có `Node_ID` lớn hơn hoặc bằng key của resource theo chiều kim đồng hồ; node này được gọi là successor của key. Đây là quy tắc quan trọng để hệ thống không cần lưu một bảng tập trung dạng `resource -> node`.

Mỗi node duy trì các thông tin:

- `predecessor`: node active đứng trước nó trên vòng Chord;
- `successor`: node active đứng sau nó trên vòng Chord;
- `finger_table`: các liên kết tắt dùng để định tuyến lookup hiệu quả hơn.

Với một node `n`, mỗi dòng trong Finger Table được tính theo công thức Chord:

```text
start_i = (n + 2^(i-1)) mod 2^m
finger_i = successor(start_i)
```

Khi lookup, node hiện tại chọn finger gần key nhất nhưng vẫn đứng trước key. Cách này tránh việc đi tuần tự qua từng successor và giúp lookup đạt xu hướng `O(log N)`.

Chord thuộc nhóm DHT có routing geometry dạng ring. Các node được đặt trên một không gian định danh hình tròn một chiều, khoảng cách giữa hai node được tính theo chiều kim đồng hồ. Với node có identifier là `a`, Chord duy trì các neighbor gần các vị trí `a + 2^(i-1)` trên vòng. Các liên kết này chính là fingers, cho phép Chord route tới node đích trong khoảng `log n` hop.

## 3. Đặc Tả Dữ Liệu

**Nguồn dữ liệu:**  
Dữ liệu được sinh tự động theo đúng yêu cầu của Topic 61. Cấu hình mặc định gồm:

- 1.000 resource có định danh từ `resource-0001` đến `resource-1000`;
- 50 node có `Node_ID = SHA1("127.0.0.1:<port>") mod 2^m`, với port riêng cho từng process.

**Kích thước:**  
1.000 bản ghi resource và 50 bản ghi node. Dữ liệu không lớn về dung lượng lưu trữ, nhưng đủ để chứng minh cách Chord phân phối resource, định tuyến lookup và đo số hop.

**Lược đồ dữ liệu:**

| Thực thể | Thuộc tính chính | Ý nghĩa |
| --- | --- | --- |
| Node | `node_id`, `active`, `predecessor`, `successor`, `finger_table` | Biểu diễn một peer trong vòng Chord |
| FingerEntry | `index`, `start`, `interval_end`, `node_id` | Biểu diễn một dòng trong Finger Table |
| ResourceRecord | `resource_id`, `key`, `owner_id` | Biểu diễn resource sau khi được băm và gán owner |
| LookupResult | `requested_id`, `key`, `owner_id`, `start_node_id`, `path`, `hops`, `logs` | Biểu diễn kết quả và đường đi của một lần lookup |

**Chiến lược phân mảnh:**  
Dự án không dùng phân mảnh ngang truyền thống. Thay vào đó, dữ liệu được phân phối bằng consistent hashing của Chord:

```text
Resource_Key = SHA-1(Resource_ID) mod 2^m
Owner_Node = successor(Resource_Key)
```

Mỗi node active chịu trách nhiệm cho khoảng key từ predecessor của nó đến chính nó. Khi join node, stop endpoint hoặc restart node, các peer stabilize và owner hiện hành vẫn tuân theo cùng quy tắc successor.

Lý do dùng SHA-1 và consistent hashing là vì định danh gốc của resource không đảm bảo phân phối đều trên overlay. Nếu đặt resource theo tên gốc, URI hoặc thứ tự nhập liệu, nhiều resource có thể tập trung vào một vùng hoặc một node. Theo lý thuyết 9.1.2, DHT thường dùng consistent hashing để tạo phân phối đều hơn, trong đó SHA-1 là một hàm băm phổ biến để ánh xạ resource vào không gian định danh. Trong dự án, SHA-1 được rút gọn bằng modulo `2^m` để phù hợp với quy mô deployment local.

## 4. Kiến Trúc Hệ Thống

**Số node:**  
Hệ thống triển khai mục tiêu hỗ trợ từ `10` đến `50` node active trong không gian định danh `m = 16` bit. Mỗi node là một site độc lập chạy trên một port riêng của máy local. Với cấu hình mặc định `base_port = 5100`, các site sử dụng dải địa chỉ `http://127.0.0.1:5100` đến tối đa `http://127.0.0.1:5149`. `Node_ID` biểu diễn vị trí logic trên vòng Chord, còn port chỉ biểu diễn địa chỉ truyền thông của tiến trình node.

**Tầng giao tiếp:**  
Mỗi node cung cấp Flask REST API và trao đổi payload JSON trực tiếp với các node khác. Các message chính gồm tìm successor, `join`, `notify`, `stabilize`, `put/get/delete` resource và sao chép replica. Một web coordinator được dùng để khởi động/dừng site, gửi thao tác demo và tổng hợp trạng thái cho giao diện; coordinator không đóng vai trò bảng tra cứu owner tập trung.

Một lookup bắt đầu từ endpoint của node nguồn, sau đó được chuyển tiếp bằng HTTP qua các endpoint trung gian dựa trên Finger Table và kết thúc tại owner của key. Mỗi request ghi lại `node_id`, port, path, số HTTP message và thời gian phản hồi để giao diện hiển thị multi-hop trace thực tế.

**Lưu trữ:**  
Mỗi site quản lý một file JSON cục bộ, ví dụ:

```text
data/nodes/
  node_<node_id_1>.json
  node_<node_id_2>.json
  ...
```

File của node chứa `node_id`, `host`, `port`, predecessor, successor, Finger Table, primary resources và replica resources. Khi nhận thao tác cập nhật, node chỉ ghi kho JSON của chính mình bằng cơ chế atomic write; resource được chuyển hoặc replicate qua REST request đến site đích. Nhờ vậy dữ liệu được phân bố vật lý trên nhiều kho cục bộ thay vì nằm trong một dictionary chung.

Về routing state, mỗi node chỉ duy trì predecessor, successor và Finger Table. Khi một port ngừng phản hồi, các node còn sống phát hiện failure thông qua timeout/health check, chạy stabilize và phục hồi primary resource từ file JSON replica còn sống.

Topology của hệ thống được trực quan hóa bằng NetworkX. Ảnh demo chỉ vẽ các cạnh Finger Table phục vụ định tuyến, tô đỏ node đã dừng và có thể highlight lookup path HTTP gần nhất; vị trí replica không được biểu diễn thành cạnh topology.

**Trạng thái triển khai hiện tại:**  
Phiên bản triển khai dùng `DistributedCoordinator` và các process `node_server.py`: mọi lookup, CRUD, join, stabilize và replication đều được trao đổi qua HTTP giữa các node và persisted trong JSON cục bộ. Runtime không có core ring tập trung để trả lời ownership thay cho peer; coordinator chỉ khởi chạy process và tổng hợp snapshot quan sát.

## 5. Công Nghệ & Kế Hoạch Cài Đặt

**Ngôn ngữ lập trình:**  
Python 3.10+

**Triển khai:**  
Một coordinator Flask chạy giao diện quản lý, còn mỗi node Chord chạy như một Flask service riêng trên port cấu hình và lưu dữ liệu vào file JSON cục bộ. Coordinator chỉ quản lý vòng đời process và tổng hợp snapshot; node tự định tuyến qua predecessor, successor và Finger Table cục bộ.

**Thư viện và framework:**

- Flask: xây dựng REST API và web server;
- NetworkX: dựng đồ thị topology của vòng Chord;
- Matplotlib: sinh ảnh topology và biểu đồ metrics;
- Pytest: kiểm thử hashing, routing, churn handling và metrics.

**Các thành phần đã cài đặt:**

1. UI deployment cấu hình `10-50` site, dải port, thư mục JSON và node pills thể hiện process sống/chết.
2. `JsonNodeStore` để mỗi node đọc/ghi primary resource và replica trong file riêng bằng atomic replace.
3. `node_server.py` và coordinator để khởi chạy/dừng/restart tối đa 50 Flask process ở các port riêng.
4. REST message cho successor lookup, `join`, `notify`, `stabilize`, put/get/delete và replication.
5. Failure detection, promote replica và repair bản sao sau khi một endpoint ngừng phản hồi.
6. Trace HTTP, topology từ endpoint snapshot và metrics đo deployment thật.
7. Integration test cho persistence, identity theo port, routing, recovery và restart.
8. Benchmark báo cáo cần chạy tại `N = 10, 20, 30, 40, 50` bằng runtime distributed.

## 6. Tiêu Chí Thành Công & Phân Tích

**Chỉ số định lượng:**  
Metric chính là số hop cần để tìm một key khi số node `N` tăng từ 10 đến 50. Ngoài ra, benchmark còn ghi nhận:

- average hops;
- average lookup latency tính bằng millisecond;
- số lookup thành công và thất bại;
- message overhead, được xấp xỉ bằng tổng số hop.

Kết quả kỳ vọng là số hop trung bình tăng chậm theo `O(log N)`, thay vì tăng tuyến tính theo số node. Đây là điểm khác biệt quan trọng so với cách tìm kiếm không cấu trúc. Nếu một mạng không có topology và routing state rõ ràng, truy vấn có thể phải lan truyền tới nhiều node. Với Chord, mỗi hop dùng Finger Table để tiến gần hơn tới key, nên số hop cần thiết tăng theo logarithm của số node.

Cấu hình benchmark hiện tại:

```text
Số node: 10, 20, 30, 40, 50
Số resource mỗi mạng: 1.000
Số trial mỗi kích thước mạng: 5
Số lookup mỗi trial: 100
Hàm băm: SHA-1
Không gian định danh mặc định: m = 16 bit
```

**Bảng kết quả cần thu thập từ deployment multi-process:**

| Số node | Average Hops | Max Hops | log2(N) | Avg HTTP Latency (ms) | Thành công / Thất bại | HTTP Messages / Lookup | Degraded / Lost |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 10 | Chạy đo | Chạy đo | 3.322 | Chạy đo | Chạy đo | Chạy đo | Chạy đo |
| 20 | Chạy đo | Chạy đo | 4.322 | Chạy đo | Chạy đo | Chạy đo | Chạy đo |
| 30 | Chạy đo | Chạy đo | 4.907 | Chạy đo | Chạy đo | Chạy đo | Chạy đo |
| 40 | Chạy đo | Chạy đo | 5.322 | Chạy đo | Chạy đo | Chạy đo | Chạy đo |
| 50 | Chạy đo | Chạy đo | 5.644 | Chạy đo | Chạy đo | Chạy đo | Chạy đo |

Mỗi dòng phải được ghi từ request lookup đi qua các port node thật. `Average Hops` và `HTTP Messages / Lookup` được lấy từ route trace; `Avg HTTP Latency` là thời gian request local giữa các process; `Degraded / Lost` được đo sau kịch bản stop owner.

Về mặt lý thuyết, nếu chỉ đi qua successor từng bước, lookup có thể gần `O(N)` trong trường hợp key nằm xa node bắt đầu. Finger Table khắc phục điều này bằng các bước nhảy theo lũy thừa của 2. Với node `n`, finger thứ `i` trỏ tới successor của vị trí:

```text
start_i = (n + 2^(i-1)) mod 2^m
```

Do các mốc finger có khoảng cách `1, 2, 4, 8, ...`, node hiện tại không cần thử từng node kế tiếp. Khi lookup key `k`, nó chọn finger gần `k` nhất nhưng không vượt quá `k`. Cách chọn này làm truy vấn nhảy qua một đoạn lớn trên vòng và thu hẹp nhanh phần còn lại cần tìm.

Có thể xem số node còn nằm giữa node hiện tại và owner của key là số ứng viên còn lại. Ban đầu, trong trường hợp xấu có thể còn khoảng `N` node. Sau mỗi hop qua closest preceding finger, số ứng viên còn lại xấp xỉ giảm một nửa. Sau `h` hop:

```text
số node còn lại ≈ N / 2^h
```

Lookup kết thúc khi phần còn lại chỉ còn nhiều nhất một node:

```text
N / 2^h <= 1
=> N <= 2^h
=> h >= log2(N)
```

Vì vậy số hop kỳ vọng tăng theo `O(log N)`: khi số node tăng gấp đôi, lookup thường chỉ cần thêm khoảng một hop. Đây là cơ sở lý thuyết để giải thích vì sao benchmark dùng `log2(N)` làm đường tham chiếu và vì sao average hops không tăng tuyến tính theo `N`.

**Kịch bản lỗi:**  
Dự án dừng process của một node active. Khi endpoint rời mạng:

1. process ngừng phản hồi HTTP;
2. các peer phát hiện predecessor/successor không phản hồi bằng health check;
3. từng peer chạy `stabilize`, `notify` và `fix_finger` từ state cục bộ;
4. node trở thành owner mới promote replica JSON còn sống thành primary;
5. replica được gửi lại đến các successor, hoặc resource được báo lost nếu không còn bản sao.

Hệ thống được xem là thành công nếu lookup vẫn tìm đúng owner mới sau khi process owner cũ đã dừng, với điều kiện còn replica sống. Điều này chứng minh khả năng phục hồi và sửa pointer sau churn mà không giả lập dữ liệu đã mất.

Trong kịch bản này, không có bước rebuild bảng định tuyến toàn mạng từ coordinator. Mỗi node dùng timeout và giao thức Chord cục bộ để hội tụ lại pointer. Nếu resource còn bản sao sống, lookup qua HTTP vẫn tìm được primary đã promote; nếu không, UI báo dữ liệu unavailable/lost thay vì giả lập dữ liệu còn tồn tại.

## 7. Các Mốc Thực Hiện

**Milestone 1 (Tuần 5): Thiết lập môi trường và mô hình dữ liệu**  
Thiết lập cấu trúc project Python, dependencies, test framework, Flask skeleton, dataclass cho node/resource, hàm SHA-1 hashing và các hàm xử lý không gian định danh Chord.

**Milestone 2 (Tuần 8): Hoàn thiện thuật toán Chord cốt lõi**  
Hoàn thành khởi tạo vòng Chord, phân phối resource, tìm successor, xây dựng Finger Table và lookup nhiều hop. Bổ sung test cho hashing, khoảng vòng, owner của resource và tính đúng của lookup.

**Milestone 3 (Tuần 12): Hoàn thiện xử lý lỗi, metrics và phần trình bày**  
Hoàn thành thao tác join/stop/restart node, stabilize sau churn, benchmark HTTP, phân tích hop count, vẽ topology bằng NetworkX, highlight lookup path và hoàn thiện tài liệu nộp bài.

## Phạm Vi Nộp Bài

Sản phẩm cuối cùng gồm:

- mã nguồn Chord DHT multi-process trên localhost;
- giao diện web Flask để demo;
- test chứng minh routing và churn handling;
- benchmark số hop với `N = 10` đến `N = 50`;
- biểu đồ topology và metrics;
- báo cáo phân tích tính chất lookup `O(log N)` và các quyết định thiết kế.
