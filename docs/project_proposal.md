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

- 1.000 resource có định danh từ `resource-0001` đến `resource-1000`
- 50 node với `Node_ID = SHA1("node:<seed>:<attempt>") mod 2^m`
- Không gian định danh: `m = 16` bit (65.536 giá trị)
- Replication count: 3 bản sao cho mỗi resource

**Kích thước:**  
1.000 bản ghi resource và 50 bản ghi node. Dữ liệu không lớn về dung lượng lưu trữ, nhưng đủ để chứng minh cách Chord phân phối resource, định tuyến lookup và đo số hop.

**Lược đồ dữ liệu:**

| Thực thể | Thuộc tính chính | Ý nghĩa |
| --- | --- | --- |
| Node | `node_id`, `active`, `predecessor`, `successor`, `finger_table`, `local_resources` | Biểu diễn một peer trong vòng Chord |
| FingerEntry | `index`, `start`, `interval_end`, `node_id` | Biểu diễn một dòng trong Finger Table |
| ResourceRecord | `resource_id`, `key`, `owner_id`, `replica_node_ids` | Biểu diễn resource sau khi được băm và gán owner |
| LookupResult | `requested_id`, `key`, `owner_id`, `start_node_id`, `path`, `hops`, `logs`, `found`, `direct_key`, `replica_node_ids` | Biểu diễn kết quả và đường đi của một lần lookup |

**Chiến lược phân mảnh:**  
Dự án không dùng phân mảnh ngang truyền thống. Thay vào đó, dữ liệu được phân phối bằng consistent hashing của Chord:

```text
Resource_Key = SHA-1(Resource_ID) mod 2^m
Owner_Node = successor(Resource_Key)
```

Mỗi node active chịu trách nhiệm cho khoảng key từ predecessor của nó đến chính nó. Khi join node, stop endpoint hoặc restart node, các peer stabilize và owner hiện hành vẫn tuân theo cùng quy tắc successor.

Lý do dùng SHA-1 và consistent hashing là vì định danh gốc của resource không đảm bảo phân phối đều trên overlay. Nếu đặt resource theo tên gốc, URI hoặc thứ tự nhập liệu, nhiều resource có thể tập trung vào một vùng hoặc một node. Theo lý thuyết 9.1.2, DHT thường dùng consistent hashing để tạo phân phối đều hơn, trong đó SHA-1 là một hàm băm phổ biến để ánh xạ resource vào không gian định danh. Trong dự án, SHA-1 được rút gọn bằng modulo `2^m` để phù hợp với quy mô deployment local.

## 4. Kiến Trúc Hệ Thống

**Chế độ triển khai:**  
Hệ thống triển khai ở chế độ **single-process simulation** trong một Flask process duy nhất. Tất cả các node được mô phỏng trong bộ nhớ (in-memory) thay vì chạy trên các port riêng biệt. Trạng thái ring được tự động lưu vào file `data/state.json` và khôi phục khi server khởi động lại.

**Số node:**  
Hệ thống hỗ trợ từ `10` đến `100` node mô phỏng trong không gian định danh `m = 16` bit. Mỗi node có `Node_ID` được sinh bằng:

```text
node_id = SHA1("node:<seed>:<attempt>") mod 2^m
```

**Tầng giao tiếp:**  
Tất cả các node giao tiếp qua lời gọi hàm in-memory trong cùng một Python process. Giao diện web cung cấp REST API để thao tác với ring. Một lookup bắt đầu từ một node, đi qua nhiều hop trong bộ nhớ và kết thúc tại owner của key. Mỗi request ghi lại `node_id`, đường đi (path), số hop và log để hiển thị trace trên giao diện.

**Lưu trữ:**  
Trạng thái ring được lưu trong `data/state.json` với cơ chế atomic write:

```text
data/
  state.json    # Trạng thái toàn bộ ring (nodes, resources, metrics)
```

File JSON chứa toàn bộ thông tin: cấu hình (m, seed, replication_count), danh sách node với trạng thái hoạt động, danh sách resource và metrics gần nhất. Nhờ cơ chế auto-load khi khởi động, hệ thống có thể tiếp tục từ trạng thái đã lưu.

**Topology và Visualization:**  
Topology của hệ thống được trực quan hóa bằng NetworkX và Matplotlib. Ảnh topology vẽ các cạnh successor/predecessor, các liên kết finger, tô màu node đã dừng và highlight lookup path. Biểu đồ metrics hiển thị hops, latency và message overhead theo số node.

**Trạng thái triển khai hiện tại:**  
Phiên bản hiện tại dùng `ChordRing` trong một Flask process. Tất cả lookup, CRUD, join, stabilize và replication đều thực hiện trong bộ nhớ. `Coordinator` trong app.py quản lý trạng thái và cung cấp API REST cho giao diện web. Trạng thái ring được persist vào JSON và tự động load khi khởi động.

## 5. Công Nghệ & Kế Hoạch Cài Đặt

**Ngôn ngữ lập trình:**  
Python 3.10+

**Triển khai:**  
Một Flask application (`app.py`) chạy giao diện web và quản lý trạng thái ring. Các node được mô phỏng trong bộ nhớ (in-memory) trong cùng một process. Trạng thái được persist vào `data/state.json` và tự động khôi phục khi server khởi động.

**Thư viện và framework:**

| Thư viện | Mục đích |
|---|---|
| Flask | REST API và web server |
| NetworkX | Dựng đồ thị topology của vòng Chord |
| Matplotlib | Sinh ảnh topology và biểu đồ metrics |
| Pytest | Kiểm thử thuật toán Chord |

**Các thành phần đã cài đặt:**

1. **ChordRing** (`src/chord_dht/chord.py`): Triển khai core Chord protocol với finger table, successor/predecessor, lookup algorithm
2. **Data Models** (`src/chord_dht/models.py`): Các dataclass Node, FingerEntry, ResourceRecord, LookupResult
3. **Identifiers** (`src/chord_dht/identifiers.py`): Hàm băm SHA-1 và xử lý không gian định danh
4. **Metrics** (`src/chord_dht/metrics.py`): Thu thập và tính toán performance metrics
5. **Visualization** (`src/chord_dht/visualization.py`): Sinh ảnh topology và biểu đồ
6. **Flask API** (`app.py`): REST endpoints cho CRUD operations, lookup, metrics
7. **Web Interface** (`templates/index.html`, `static/app.js`): Giao diện người dùng tương tác
8. **State Persistence**: Auto-save/load ring state từ JSON file
9. **Test Suite** (`tests/test_distributed_chord.py`): Unit tests cho routing, failure recovery

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

**Bảng kết quả cần thu thập từ simulation:**

| Số node | Average Hops | Max Hops | log2(N) | Avg Latency (ms) | Thành công / Thất bại | Messages / Lookup |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 10 | Chạy đo | Chạy đo | 3.322 | Chạy đo | Chạy đo | Chạy đo |
| 20 | Chạy đo | Chạy đo | 4.322 | Chạy đo | Chạy đo | Chạy đo |
| 30 | Chạy đo | Chạy đo | 4.907 | Chạy đo | Chạy đo | Chạy đo |
| 40 | Chạy đo | Chạy đo | 5.322 | Chạy đo | Chạy đo | Chạy đo |
| 50 | Chạy đo | Chạy đo | 5.644 | Chạy đo | Chạy đo | Chạy đo |

Mỗi dòng được thu thập từ benchmark chạy nhiều trials trên simulation. `Average Hops` và `Messages / Lookup` được lấy từ route trace; `Avg Latency` là thời gian thực thi trong bộ nhớ. Metrics về replication và failure recovery được đo sau kịch bản kill node.

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
Dự án mô phỏng việc một node ngừng hoạt động (kill). Khi một node bị dừng:

1. Node được đánh dấu inactive và thêm vào `failed_nodes` set
2. Predecessor và successor của node được kết nối trực tiếp để vá vòng
3. Các finger table trỏ đến node chết được sửa lại
4. Resources của node chết được phục hồi từ replica còn sống (nếu có)
5. Nếu không còn bản sao, resource được báo lost

Hệ thống được xem là thành công nếu lookup vẫn tìm đúng owner mới sau khi node đã bị dừng, với điều kiện còn replica sống. Điều này chứng minh khả năng phục hồi và sửa pointer sau churn.

Trong kịch bản này, không có bước rebuild bảng định tuyến toàn mạng từ coordinator. Mỗi node dùng thông tin cục bộ để hội tụ lại pointer. Nếu resource còn bản sao sống, lookup vẫn tìm được primary đã promote; nếu không, hệ thống báo dữ liệu unavailable/lost.

## 7. Các Mốc Thực Hiện

**Milestone 1 (Tuần 5): Thiết lập môi trường và mô hình dữ liệu**  
Thiết lập cấu trúc project Python, dependencies, test framework, Flask skeleton, dataclass cho node/resource, hàm SHA-1 hashing và các hàm xử lý không gian định danh Chord.

**Milestone 2 (Tuần 8): Hoàn thiện thuật toán Chord cốt lõi**  
Hoàn thành khởi tạo vòng Chord, phân phối resource, tìm successor, xây dựng Finger Table và lookup nhiều hop. Bổ sung test cho hashing, khoảng vòng, owner của resource và tính đúng của lookup.

**Milestone 3 (Tuần 12): Hoàn thiện xử lý lỗi, metrics và phần trình bày**  
Hoàn thành thao tác join/stop/restart node, stabilize sau churn, benchmark HTTP, phân tích hop count, vẽ topology bằng NetworkX, highlight lookup path và hoàn thiện tài liệu nộp bài.

## Phạm Vi Nộp Bài

Sản phẩm cuối cùng gồm:

- Mã nguồn Chord DHT simulation trong một Flask process
- Giao diện web tương tác để demo
- Test chứng minh routing và failure handling
- Benchmark số hop với `N = 10` đến `N = 50`
- Biểu đồ topology và performance metrics
- Báo cáo phân tích tính chất lookup `O(log N)` và các quyết định thiết kế
