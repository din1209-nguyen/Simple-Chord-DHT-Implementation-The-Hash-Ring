# Luồng Hoạt Động API Và Đánh Giá Tính Thực Tế

Tài liệu này mô tả luồng xử lý của các API trong `app.py`, cách các API gọi xuống `ChordRing` trong `src/chord_dht/chord.py`, vì sao hệ thống được thiết kế như vậy, và mức độ mô phỏng này có đúng với thực tế của Chord DHT hay chưa.

## 1. Tổng Quan Kiến Trúc

Dự án là một web app Flask mô phỏng Chord DHT trong một tiến trình duy nhất.

Luồng tổng quát:

```text
Frontend / HTTP client
        |
        v
Flask API trong app.py
        |
        v
coordinator_lock + autoload state
        |
        v
ChordRing trong src/chord_dht/chord.py
        |
        v
Node, finger table, resource metadata, local_resources
        |
        v
Persist JSON + trả response cho frontend
```

Các API không trực tiếp xử lý thuật toán Chord. `app.py` chủ yếu làm nhiệm vụ:

- Nhận request JSON.
- Validate dữ liệu đầu vào.
- Khóa thao tác bằng `coordinator_lock`.
- Tự nạp state từ JSON bằng `_autoload_once()`.
- Chặn thao tác khi có node đang pending recovery.
- Gọi các method của `ChordRing`.
- Lưu lại state bằng `_save_ring_state(ring)`.
- Trả JSON cho frontend.

`ChordRing` mới là nơi thực hiện logic Chord: tạo vòng định danh, join node, stabilize, fix finger table, lookup, thêm/xóa resource, đánh dấu node lỗi, recover dữ liệu từ replica.

## 2. Vì Sao API Luôn Autoload, Lock Và Persist State

Hầu hết API đều có mẫu xử lý giống nhau:

```text
Nhận payload
  -> with coordinator_lock
  -> _autoload_once()
  -> kiểm tra pending recovery nếu thao tác có thể làm sai trạng thái
  -> gọi ChordRing
  -> _save_ring_state(ring)
  -> trả state/report/trace
```

Làm như vậy là hợp lý vì hệ thống đang là simulator single-process:

- `coordinator_lock` tránh hai request cùng lúc sửa chung một object `ring`.
- `_autoload_once()` giúp server khôi phục trạng thái từ `data/state.json` sau khi restart.
- `_save_ring_state()` giúp UI refresh hoặc server restart vẫn giữ được topology, resource, failed node và metric gần nhất.
- Pending recovery được dùng để ép người dùng xử lý lỗi node trước khi tiếp tục lookup/add/delete. Nếu bỏ qua bước này, finger table và resource owner có thể đang ở trạng thái cũ, dẫn tới kết quả mô phỏng khó giải thích.

Trong hệ phân tán thật, mỗi node sẽ có state riêng và không có một global lock trung tâm như vậy. Tuy nhiên với mục tiêu mô phỏng và demo thuật toán, cách này đúng hướng vì giúp trạng thái nhất quán, dễ kiểm thử và dễ trình bày.

## 3. Luồng API State Và Resource

### `GET /`

Trả giao diện chính từ `templates/index.html`.

Mục đích là cung cấp dashboard để người dùng thao tác với mạng Chord thay vì phải gọi API thủ công.

### `GET /api/state`

Luồng:

```text
Client gọi /api/state
  -> lock
  -> autoload state nếu cần
  -> ring.summary(sample_size=None)
  -> trả toàn bộ snapshot ring
```

API này dùng để frontend render lại toàn bộ trạng thái: node active, failed node, finger table, resource distribution, sample resource, thông tin cấu hình.

Làm vậy đúng với mô phỏng vì UI cần một snapshot tập trung. Trong Chord thật, không có node nào tự nhiên biết toàn bộ trạng thái toàn mạng; muốn có dashboard như vậy phải có monitoring service riêng.

### `GET /api/resources`

Luồng:

```text
autoload ring
  -> ring.summary()
  -> lấy resource_count và sample_resources
  -> trả danh sách resource
```

API này phục vụ quan sát dữ liệu đang được ring quản lý. Nó lấy dữ liệu từ metadata tổng hợp của simulator.

Trong thực tế, resource thường nằm phân tán ở các node owner/replica. Việc có một endpoint trả toàn bộ resource là tiện cho demo, nhưng mang tính tập trung.

### `POST /api/initialize`

Payload chính:

```json
{
  "nodes": 50,
  "resources": 1000,
  "m": 16,
  "seed": 61,
  "replication_count": 1
}
```

Luồng:

```text
Nhận cấu hình
  -> parse nodes/resources/m/seed/replication_count
  -> tạo ChordRing mới
  -> initialize_network()
      -> sinh node ID bằng SHA-1 mod 2^m
      -> tạo node đầu tiên
      -> các node còn lại join qua known node
      -> chạy stabilize/notify/fix_fingers tới khi ổn định
      -> sinh resource
      -> hash resource thành key
      -> route Put qua Chord để tìm owner
      -> đặt resource vào owner và replica
  -> lưu state.json, node_ids.json, resource_ids.json
  -> trả state mới
```

Lý do làm vậy:

- `seed` giúp kết quả tái lập, rất hữu ích cho báo cáo và test.
- Node/resource đều được đưa vào không gian `2^m`, đúng nguyên tắc Chord.
- Join từng node và chạy protocol hội tụ mô phỏng cách Chord xây ring thay vì dựng sẵn toàn bộ bằng oracle.
- Resource được route qua `_route_key()` để tìm owner, giúp trace và metrics phản ánh đường đi Chord.

Đánh giá thực tế: đúng về mặt nguyên lý Chord, nhưng vẫn là mô phỏng tập trung. Trong thực tế, node join diễn ra bằng RPC giữa các peer, không phải một object Python tạo hết node cùng lúc.

## 4. Luồng API Lookup

### `POST /api/lookup`

Payload:

```json
{
  "resource_id": "resource-0010",
  "start_node_id": 12345
}
```

`start_node_id` là tùy chọn. Nếu không truyền, hệ thống chọn node active nhỏ nhất làm điểm bắt đầu.

Luồng:

```text
Validate resource_id
  -> autoload
  -> chặn nếu đang pending recovery
  -> chuẩn hóa start_node_id
  -> ring.lookup(resource_id, start_node_id)
      -> nếu resource_id là số: dùng trực tiếp như key
      -> nếu là chuỗi: hash thành key
      -> _route_key()
          -> bắt đầu từ start node
          -> nếu node hiện tại sở hữu key thì dừng
          -> nếu successor sở hữu key thì đi tới successor
          -> nếu không, chọn closest preceding finger
          -> fallback successor nếu không có finger tốt
          -> ghi path, hops, logs
      -> kiểm tra resource có tồn tại tại owner không
      -> trả owner, path, hops, logs, found, replicas
  -> tạo lookup_metric nhanh
  -> persist state
  -> trả result + metric
```

Vì sao làm vậy:

- Chord lookup tìm successor của key, tức node đầu tiên theo chiều kim đồng hồ có ID >= key.
- Finger table giúp giảm số hop so với đi successor từng bước.
- Trace `path/logs` giúp chứng minh request không nhảy thẳng bằng danh sách global mà đi theo overlay.
- Metric tức thời giúp UI so sánh số hop với kỳ vọng `O(log N)`.

Đánh giá thực tế: khá đúng với Chord ở mức thuật toán lookup. Điểm chưa hoàn toàn thực tế là các node vẫn nằm trong cùng một process và `_route_key()` có thể dùng một số helper toàn cục để sửa view hoặc tính successor trong mô phỏng.

## 5. Luồng API Node

### `GET /api/node/<node_id>`

Luồng:

```text
autoload
  -> ring.node_details(node_id)
  -> trả node, predecessor, successor, finger table, local resources
```

API này phục vụ kiểm tra chi tiết một node. Nó rất hữu ích để giải thích vì sao lookup đi theo một finger cụ thể.

Trong thực tế, muốn lấy chi tiết như vậy phải query trực tiếp node đó hoặc dùng hệ thống monitoring.

### `POST /api/node`

Payload:

```json
{
  "node_id": 12345
}
```

`node_id` là tùy chọn. Nếu không truyền, hệ thống tự tìm ID còn trống.

Luồng:

```text
autoload
  -> chặn pending recovery
  -> ring.add_node(node_id)
      -> validate ID
      -> nếu node cũ inactive thì bật lại
      -> nếu node mới thì tạo Node
      -> chọn một known node active
      -> join(new_node, known_node)
          -> route để tìm successor ban đầu
          -> gán successor
      -> run_protocol_until_stable()
      -> rebalance resource trong khoảng key node mới nhận
      -> refresh replica set quanh node mới
  -> persist
  -> trả report + state
```

Vì sao làm vậy:

- Chord join cần biết ít nhất một node đang ở trong ring.
- Node mới chỉ nhận các key trong khoảng `(predecessor, new_node]`, không cần di chuyển toàn bộ dữ liệu.
- Sau khi node chen vào vòng, replica trên successor chain có thể thay đổi nên cần refresh.

Đánh giá thực tế: đúng với nguyên lý join của Chord. Điểm mô phỏng là protocol được chạy tới ổn định ngay trong một request; hệ thật thường hội tụ dần theo chu kỳ nền.

### `DELETE /api/node/<node_id>`

Luồng:

```text
autoload
  -> chặn pending recovery
  -> kiểm tra node tồn tại
  -> nếu node đang active thì ring.kill_node(node_id)
  -> xóa node khỏi metadata
  -> xóa khỏi failed_nodes
  -> stabilize()
  -> persist
  -> trả state
```

API này khác `kill`: nó xóa node khỏi mô hình quản lý, không chỉ đánh dấu failed.

Trong thực tế, node rời mạng graceful có thể chuyển dữ liệu cho successor trước khi rời. Ở đây nếu node active bị xóa, code gọi `kill_node()` trước, tức mô phỏng theo hướng node lỗi/rời đột ngột rồi mới loại khỏi metadata.

### `POST /api/kill`

Payload:

```json
{
  "node_id": 12345
}
```

Luồng:

```text
autoload
  -> chặn nếu đã có pending recovery
  -> ring.mark_node_failed(node_id)
      -> kiểm tra không kill node cuối cùng
      -> active = False
      -> thêm vào failed_nodes
      -> tạo failure_impact_report()
          -> stale finger entries
          -> affected resources
          -> node bị cảnh báo
  -> persist
  -> trả impact report + state
```

Vì sao `kill` chỉ đánh dấu lỗi mà chưa sửa ngay:

- UI có thể hiển thị hậu quả thật của failure: finger nào trỏ tới node chết, resource nào bị ảnh hưởng.
- Người dùng thấy rõ sự khác nhau giữa trạng thái lỗi và trạng thái sau recovery.
- Các API khác bị chặn pending recovery để tránh tiếp tục thao tác trên ring đang không ổn định.

Đánh giá thực tế: cách tách failure và recovery là hợp lý để demo. Trong hệ thật, failure detection và repair thường diễn ra bất đồng bộ, không đợi người dùng bấm nút.

### `POST /api/recover`

Payload:

```json
{
  "node_id": 12345
}
```

Luồng:

```text
autoload
  -> ring.recover_failed_node(node_id)
      -> kiểm tra node đang failed
      -> lưu predecessor/successor cũ
      -> ngắt routing view của node chết
      -> nối predecessor cũ với successor cũ nếu còn active
      -> sửa finger table trỏ tới node chết
      -> khôi phục resource từ active local replica copies
      -> reconcile owner/resource mapping
      -> xóa node khỏi failed_nodes
  -> persist
  -> trả recovery report + state
```

Vì sao làm vậy:

- Khi node chết, các node khác có thể còn finger trỏ tới nó, cần sửa để lookup không đi vào node inactive.
- Resource primary trên node chết chỉ khôi phục được nếu còn replica sống.
- Sau recovery cần đồng bộ lại owner và replica set để mapping `successor(key)` đúng với topology mới.

Đánh giá thực tế: đúng về ý tưởng fault recovery và replication. Tuy nhiên recovery trong code là tập trung và khá “mạnh tay”: một coordinator sửa nhiều node cùng lúc. Hệ Chord thật thường để từng node tự stabilize, check predecessor, fix fingers và sao chép dữ liệu qua RPC.

## 6. Luồng API Resource

### `POST /api/resource`

Payload:

```json
{
  "resource_id": "my-file"
}
```

Luồng:

```text
Validate resource_id
  -> autoload
  -> chặn pending recovery
  -> ring.add_resource(resource_id)
      -> hash resource_id thành digest SHA-1 và key mod 2^m
      -> route Put để tìm owner
      -> kiểm tra trùng tại owner
      -> tạo ResourceRecord
      -> đặt copy tại owner và replica nodes
  -> persist
  -> trả resource + trace put + state
```

Vì sao làm vậy:

- Resource không được gán ngẫu nhiên mà theo `successor(key)`, đúng nguyên tắc DHT.
- Việc route Put qua finger table giúp thao tác ghi cũng có path/hops giống lookup.
- Replica giúp recover khi owner chết.

Đánh giá thực tế: đúng về mapping key-owner và replication successor. Chưa thực tế ở phần dữ liệu chỉ là metadata/resource ID, chưa có payload file/value thật.

### `PUT /api/resource`

Payload:

```json
{
  "old_resource_id": "my-file",
  "new_resource_id": "my-file-v2"
}
```

Luồng:

```text
Validate old/new ID
  -> autoload
  -> chặn pending recovery
  -> route key cũ để tìm owner thật
  -> kiểm tra resource cũ tồn tại tại owner
  -> nếu ID không đổi thì trả nguyên resource
  -> hash ID mới thành key mới
  -> route Put để tìm owner mới
  -> kiểm tra trùng ID mới
  -> xóa mọi copy cũ
  -> tạo ResourceRecord mới
  -> đặt copy mới tại owner/replica mới
  -> persist
  -> trả trace put
```

Vì sao update được làm bằng delete + put:

- Trong Chord, ID resource quyết định key.
- Đổi ID nghĩa là đổi hash key, nên owner có thể thay đổi.
- Vì vậy cách đúng là xóa bản cũ và ghi bản mới theo key mới.

Đánh giá thực tế: hợp lý. Nếu hệ thật lưu value lớn, có thể tối ưu bằng cách giữ payload và chỉ chuyển metadata/value khi owner thay đổi.

### `DELETE /api/resource`

Payload:

```json
{
  "resource_id": "my-file"
}
```

Luồng:

```text
Validate resource_id
  -> autoload
  -> chặn pending recovery
  -> hash resource_id thành key
  -> route Delete tới owner thật
  -> kiểm tra resource tồn tại tại owner
  -> xóa metadata
  -> xóa copy ở owner và replica
  -> persist
  -> trả trace delete + state
```

Vì sao route trước khi xóa:

- Không nên chỉ tin vào metadata tập trung.
- Cần tìm owner theo key hiện tại, giống cách client trong DHT thật gửi request tới một peer bất kỳ rồi được route tới owner.

Đánh giá thực tế: đúng về mặt DHT. Trong hệ thật, xóa replica cần cơ chế đồng bộ/xác nhận giữa các node.

## 7. Luồng API Metrics Và Topology

### `GET /api/metrics`

Trả lỗi 405.

Lý do: chạy metrics có thể tốn thời gian và tạo biểu đồ, nên không nên cho GET vô tình kích hoạt benchmark.

### `POST /api/metrics`

Payload chính:

```json
{
  "trials": 5,
  "lookups": 100,
  "metric_seed": 123
}
```

Luồng:

```text
Parse trials/lookups/metric_seed
  -> autoload
  -> chặn pending recovery
  -> lấy live resources từ active nodes
  -> lấy node IDs, m, replication_count hiện tại
  -> chạy run_current_ring_metrics()
  -> build node_sizes cho sweep
  -> run_lookup_metrics() trên các kích thước mạng
  -> save_metric_charts_from_points()
  -> lưu last_metrics_payload
  -> persist state
  -> trả sweep_points + chart URLs
```

Vì sao làm vậy:

- Metric cần đo số hop trung bình, max hop, success rate, message overhead.
- Sweep theo số node giúp so sánh thực nghiệm với kỳ vọng Chord `O(log N)`.
- Dùng `plot_lock` để tránh nhiều request cùng lúc ghi/vẽ biểu đồ.

Đánh giá thực tế: đúng với mục tiêu benchmark thuật toán. Latency chỉ là mô phỏng/đo trong process, không phản ánh latency mạng thật.

### `GET /api/metrics/last`

Trả lại metrics gần nhất đã lưu trong bộ nhớ/state.

Mục đích là để frontend refresh vẫn hiển thị biểu đồ hoặc kết quả gần nhất.

### `POST /api/topology`

Payload:

```json
{
  "include_last_path": true,
  "lookup_path": [10, 20, 35]
}
```

Luồng:

```text
autoload
  -> đọc include_last_path
  -> chuẩn hóa lookup_path nếu có
  -> save_topology_graph()
  -> trả chart_url chống cache
```

Vì sao làm vậy:

- Topology graph giúp nhìn vòng Chord, liên kết node và đường lookup.
- Highlight lookup path giúp giải thích vì sao request đi qua các node cụ thể.

Đánh giá thực tế: đây là công cụ quan sát mô phỏng, không phải thành phần bắt buộc của Chord thật.

## 8. Cách Hash Và Xác Định Owner

Trong `identifiers.py`:

- `hash_identifier(value, m)` dùng SHA-1 rồi lấy modulo `2^m`.
- `hash_resource(resource_id, m)` trả digest SHA-1 đầy đủ và key đã co về không gian `m` bit.
- `in_clockwise_interval()` kiểm tra một giá trị có nằm trong khoảng trên vòng, kể cả trường hợp wrap qua 0.

Owner của key là node active đầu tiên theo chiều kim đồng hồ sao cho:

```text
key thuộc (predecessor, node]
```

Đây là định nghĩa đúng của Chord: node successor của key chịu trách nhiệm cho key đó.

## 9. Những Điểm Đúng Với Chord Thực Tế

Các phần sau bám khá sát Chord:

- Không gian định danh dạng vòng `0..2^m-1`.
- Node ID và resource key được hash bằng SHA-1 rồi co về `m` bit.
- Resource được quản lý bởi `successor(key)`.
- Finger table có `m` dòng, mỗi dòng trỏ tới `successor(node + 2^(i-1))`.
- Lookup dùng `closest preceding finger` để giảm hop.
- Node join thông qua một known node.
- Có `stabilize`, `notify`, `check_predecessor`, `fix_fingers`.
- Khi node join chỉ một khoảng key bị chuyển owner.
- Có replication trên successor chain để phục hồi khi owner chết.
- Metrics so sánh số hop với xu hướng `O(log N)`.

Với mục tiêu môn học/mô phỏng, cách triển khai này là đúng hướng và có thể giải thích tốt bản chất của Chord DHT.

## 10. Những Điểm Chưa Hoàn Toàn Thực Tế

Một số điểm mang tính simulator:

- Toàn bộ node chạy trong một process Python, không phải nhiều máy/nhiều process.
- Flask API là coordinator trung tâm, trong khi Chord thật là peer-to-peer.
- Có `coordinator_lock` và metadata global `ring.resources`; hệ thật không có global lock như vậy.
- Persist state bằng một file JSON tập trung; hệ thật mỗi node thường lưu state riêng.
- Recovery được kích hoạt bằng API và sửa nhiều node cùng lúc; hệ thật thường phát hiện lỗi và sửa dần bằng heartbeat/RPC nền.
- Latency/message overhead chủ yếu là metric mô phỏng, chưa có network latency thật.
- Resource hiện là record metadata, chưa phải value/file thật được truyền qua mạng.
- Một số helper dùng snapshot active node toàn cục để đảm bảo mô phỏng hội tụ và dễ kiểm thử.

Các điểm này không làm sai ý tưởng Chord, nhưng cần nói rõ trong báo cáo: đây là **single-process Chord simulator**, không phải deployment DHT production.

## 11. Kết Luận

Luồng API hiện tại hợp lý cho một hệ mô phỏng Chord DHT:

- API rõ ràng theo nhóm state, node, resource, lookup, metrics, topology.
- Các thao tác thay đổi state đều lock, autoload và persist.
- Lookup, put, delete đều route theo key thay vì gán trực tiếp.
- Join, failure, recovery và replication có đủ logic để demo các tình huống quan trọng.
- Thiết kế giúp frontend dễ hiển thị trace, metric và impact report.

Về tính thực tế, hệ thống đúng ở tầng thuật toán và mô hình khái niệm của Chord, nhưng chưa phải hệ phân tán thật. Nếu muốn tiến gần thực tế hơn, bước tiếp theo nên là tách mỗi node thành một service/process riêng, giao tiếp qua HTTP/gRPC, lưu state cục bộ từng node, chạy stabilize/fix_fingers định kỳ nền, và thay recovery tập trung bằng phát hiện lỗi phân tán.

## 12. Giải Thích Kỹ Các Helper Trong `app.py`

Các helper trong `app.py` là lớp điều phối bên ngoài thuật toán Chord. Chúng giúp API an toàn hơn, giữ được state sau khi server restart, và chuẩn hóa response cho frontend.

### `_ring_state_to_json(ring)`

Hàm này chuyển object `ChordRing` đang nằm trong RAM thành một dictionary có thể ghi xuống JSON.

Nó lưu các phần sau:

- `schema_version`: phiên bản format state.
- `saved_at`: thời điểm lưu.
- `config`: gồm `m`, `seed`, `replication_count`.
- `nodes`: toàn bộ node, trạng thái active/failed/retired, predecessor, successor, finger table.
- `resources`: toàn bộ resource metadata.
- `metrics`: metric gần nhất nếu đã chạy benchmark.

Vì sao cần hàm này: object Python như `ChordRing`, `Node`, `FingerEntry`, `ResourceRecord` không thể tự ghi thẳng xuống JSON. Cần chuyển chúng thành kiểu dữ liệu cơ bản như dict, list, int, str, bool.

### `_ring_state_from_json(payload)`

Hàm này làm ngược lại `_ring_state_to_json`: nhận payload từ `data/state.json` và dựng lại một object `ChordRing`.

Luồng chi tiết:

```text
Đọc metrics cũ
  -> đọc config m/seed/replication_count
  -> tạo ChordRing mới
  -> khôi phục từng node
  -> khôi phục predecessor/successor/finger table nếu state có lưu
  -> đánh dấu failed node nếu status là failed
  -> nếu state cũ thiếu routing thì nối vòng theo active node
  -> nếu có routing và không có failed node thì chạy protocol cho hội tụ
  -> khôi phục resource metadata
  -> đặt resource vào owner và replica còn active
  -> trả ring đã dựng lại
```

Vì sao làm như vậy: khi server restart, RAM mất hết. Nếu không dựng lại ring từ JSON, UI sẽ quay về ring mặc định và mất topology/resource trước đó.

Điểm cần chú ý: nếu đang có failed node, hàm này không tự recover. Nó giữ trạng thái lỗi để frontend yêu cầu người dùng bấm Recover, nhờ vậy demo vẫn thấy được tình huống failure.

### `_save_ring_state(ring)`

Hàm này ghi snapshot ring xuống `data/state.json`.

Nó không ghi trực tiếp vào file chính ngay. Thay vào đó:

```text
Tạo file tạm
  -> json.dump state vào file tạm
  -> flush + fsync để đẩy dữ liệu xuống đĩa
  -> replace file tạm thành state.json
  -> nếu Windows khóa file tạm thời thì retry vài lần
```

Vì sao làm vậy: cách ghi file tạm rồi replace giúp giảm nguy cơ `state.json` bị hỏng giữa chừng nếu app crash khi đang ghi.

### `_save_node_ids(ring)`

Hàm này lưu danh sách node ID ra `data/node_ids.json`.

Nó phục vụ báo cáo, kiểm thử và tái kiểm tra dataset ban đầu. File này không phải core state để chạy Chord, vì core state chính nằm ở `state.json`.

### `_save_resource_ids(ring)`

Hàm này lưu danh sách resource ID và hash ra `data/resource_ids.json`.

Mục đích là giúp người dùng xem các resource ban đầu đã được hash như thế nào. Nó hữu ích khi cần chứng minh resource được đưa vào không gian định danh Chord bằng SHA-1.

### `_save_initial_dataset_files(ring)`

Hàm này gọi `_save_node_ids()` và `_save_resource_ids()`, sau đó đọc lại hai file vừa ghi để kiểm tra số lượng.

Vì sao cần đọc lại: để đảm bảo file dataset ban đầu thật sự được ghi đúng. Nếu số lượng node/resource trong file không khớp với ring vừa initialize, hàm báo lỗi ngay.

### `_load_ring_state()`

Hàm này đọc `data/state.json` nếu file tồn tại.

Luồng:

```text
Nếu không có state.json
  -> trả None
Nếu có
  -> json.load()
  -> kiểm tra payload là dict
  -> gọi _ring_state_from_json(payload)
  -> trả ChordRing đã khôi phục
```

Vì sao tách riêng hàm này: `_autoload_once()` chỉ cần biết “có load được ring không”, còn chi tiết dựng lại ring nằm trong `_ring_state_from_json()`.

### `_autoload_once()`

`_autoload_once()` dùng để tự động nạp state từ `data/state.json` đúng một lần trong vòng đời server.

Đây là hàm rất quan trọng vì server Flask khi khởi động chỉ tạo một ring mặc định:

```python
ring = ChordRing(m=16, seed=61, replication_count=1)
ring_startup_completed = False
startup_lock = Lock()
```

Nếu đã từng initialize hoặc thao tác trước đó, state thật nằm trong `data/state.json`. `_autoload_once()` giúp thay ring mặc định bằng state đã lưu.

Luồng chi tiết:

```text
API gọi _autoload_once()
  -> nếu ring_startup_completed = True thì return ngay
  -> nếu chưa, lấy startup_lock
  -> kiểm tra lại ring_startup_completed sau khi có lock
  -> gọi _load_ring_state()
  -> nếu load được ring hợp lệ thì gán global ring = loaded
  -> nếu load lỗi thì ghi warning và vẫn cho server chạy
  -> đặt ring_startup_completed = True
```

Vì sao cần `startup_lock`: request Flask có thể đến cùng lúc. Nếu hai request đầu tiên cùng gọi autoload, cả hai có thể cùng đọc và gán `ring`. Lock đảm bảo chỉ một request được nạp state trước, request còn lại thấy `ring_startup_completed = True` và bỏ qua.

Vì sao chỉ chạy một lần: nếu request nào cũng load lại từ disk, các thay đổi vừa làm trong RAM có thể bị state cũ ghi đè. Autoload chỉ dùng để khôi phục lúc server vừa bắt đầu nhận request.

Vì sao lỗi load không làm server chết: file JSON có thể bị lỗi, bị sửa tay hoặc thiếu field. App chọn cách ghi warning rồi tiếp tục bằng ring mặc định, giúp server vẫn mở được UI.

Nói ngắn gọn: `_autoload_once()` là cơ chế “khôi phục state lúc startup”, không phải cơ chế đồng bộ dữ liệu liên tục.

### `json_error(message, status_code, **extra)`

Hàm này chuẩn hóa lỗi API thành JSON:

```json
{
  "ok": false,
  "message": "..."
}
```

Nếu có thông tin thêm như `requires_recovery` hoặc `failed_nodes`, hàm cũng đưa vào payload.

Vì sao cần: frontend chỉ cần đọc cùng một format lỗi cho mọi API.

### `_require_no_pending_recovery()`

Hàm này kiểm tra `ring.failed_nodes`.

Nếu không có failed node, trả `None`, nghĩa là API được chạy tiếp. Nếu có failed node, trả response lỗi `409`:

```json
{
  "ok": false,
  "message": "A node is failed. Press Recover before running this operation.",
  "requires_recovery": true,
  "failed_nodes": [...]
}
```

Vì sao cần: sau khi `kill`, ring đang ở trạng thái cố ý chưa repair. Nếu vẫn cho add/delete/lookup/metrics chạy, kết quả có thể khó giải thích vì routing còn stale. API ép người dùng recover trước để luồng demo rõ ràng.

### `parse_int_field(payload, field, default)`

Hàm này lấy một field từ JSON payload rồi ép sang `int`.

Nó cũng xử lý trường hợp field bắt buộc bị thiếu hoặc rỗng. Ví dụ `node_id` trong `/api/kill` không có default, nên thiếu sẽ báo lỗi.

### `save_metric_charts_from_points(points)`

Hàm này nhận danh sách metric points và sinh ba biểu đồ:

- Average hops so với `log2(N)`.
- Latency trung bình.
- Message overhead.

Nó trả về URL ảnh trong `/static/metrics/...` để frontend hiển thị.

Vì sao nằm ở `app.py`: đây là phần phục vụ UI/API response, không phải thuật toán Chord cốt lõi.

### `handle_http_error(exc)` và `handle_unexpected_error(exc)`

Hai hàm này bắt lỗi Flask/Werkzeug.

Nếu request bắt đầu bằng `/api/`, lỗi được trả dưới dạng JSON. Nếu là route giao diện thường, lỗi được Flask xử lý theo mặc định.

Vì sao cần: API client/frontend không nên nhận HTML error page khi gọi `/api/...`.

## 13. Giải Thích Kỹ Từng Endpoint Trong `app.py`

### `index()` - `GET /`

Hàm này chỉ render `templates/index.html`.

Luồng:

```text
Browser mở /
  -> Flask gọi index()
  -> render_template("index.html")
  -> trả HTML dashboard
```

Nó không gọi `_autoload_once()` vì trang HTML chỉ là shell giao diện. State thật sẽ được frontend gọi qua `/api/state`.

### `state()` - `GET /api/state`

Hàm này trả snapshot đầy đủ của ring.

Luồng:

```text
Client gọi /api/state
  -> lấy coordinator_lock
  -> _autoload_once()
  -> ring.summary(sample_size=None)
  -> jsonify({ok: true, state: ...})
```

`ring.summary()` gom thông tin node, resource, failed node, distribution, finger table summary. API này thường được gọi sau khi mở UI hoặc sau thao tác để render lại màn hình.

### `list_resources()` - `GET /api/resources`

Hàm này trả danh sách resource.

Luồng:

```text
Lock
  -> _autoload_once()
  -> summary = ring.summary(sample_size=None)
  -> lấy summary["resource_count"]
  -> lấy summary["sample_resources"]
  -> trả JSON
```

Tên `sample_resources` trong summary được dùng lại, nhưng vì truyền `sample_size=None`, ý nghĩa là lấy đầy đủ theo cách summary hỗ trợ.

### `node_details(node_id)` - `GET /api/node/<node_id>`

Hàm này trả chi tiết một node.

Luồng:

```text
Lock
  -> _autoload_once()
  -> ring.node_details(node_id)
  -> trả JSON
```

`ring.node_details()` kiểm tra node tồn tại rồi trả predecessor, successor, finger table, local resources. Endpoint này rất quan trọng khi giải thích vì sao lookup chọn finger nào.

### `initialize_network()` - `POST /api/initialize`

Hàm này tạo lại toàn bộ ring.

Luồng đầy đủ:

```text
Đọc JSON payload
  -> lock
  -> _autoload_once()
  -> parse nodes/resources/m/seed/replication_count
  -> tạo ChordRing mới
  -> ring.initialize_network(...)
  -> _save_ring_state(ring)
  -> _save_initial_dataset_files(ring)
  -> trả state mới
```

Các hàm sâu được gọi:

- `ChordRing.__init__()`: tạo ring rỗng với `m`, `seed`, `replication_count`.
- `ChordRing.initialize_network()`: sinh node/resource, cho node join, chạy protocol, đặt resource.
- `_save_ring_state()`: persist trạng thái chính.
- `_save_initial_dataset_files()`: lưu node/resource dataset ban đầu.

Vì sao initialize được phép chạy dù có pending recovery: initialize tạo ring mới hoàn toàn, nên trạng thái failed cũ không còn ý nghĩa.

### `lookup_resource()` - `POST /api/lookup`

Hàm này lookup resource hoặc key.

Luồng đầy đủ:

```text
Đọc payload
  -> lấy resource_id
  -> nếu rỗng thì json_error
  -> lấy start_node_id tùy chọn
  -> lock
  -> _autoload_once()
  -> _require_no_pending_recovery()
  -> chuẩn hóa start_node_id
  -> ring.lookup(resource_id, start_node_id=start)
  -> result_obj.to_dict()
  -> ring.summary()
  -> _save_ring_state(ring)
  -> tự tạo lookup_metric từ hops
  -> trả result + lookup_metric
```

Các hàm sâu được gọi:

- `ChordRing.lookup()`: chuẩn hóa key, gọi `_route_key()`, kiểm tra resource có tại owner không.
- `_route_key()`: đi nhiều hop qua successor/finger table.
- `_resolve_lookup_key()`: phân biệt lookup theo resource ID hay key số.
- `_resolve_start_node()`: chọn node bắt đầu.
- `_select_next_hop()`: chọn successor hoặc closest preceding finger.

Vì sao lookup cũng save state: lookup có thể phát hiện finger/successor stale và sửa local routing view trong `_route_key()`, nên state sau lookup có thể thay đổi.

### `kill_node()` - `POST /api/kill`

Hàm này mô phỏng node bị lỗi nhưng chưa recover.

Luồng:

```text
Đọc payload
  -> lock
  -> _autoload_once()
  -> _require_no_pending_recovery()
  -> parse node_id
  -> ring.mark_node_failed(node_id)
  -> _save_ring_state(ring)
  -> trả impact report + state
```

Các hàm sâu được gọi:

- `mark_node_failed()`: chuyển `active=False`, thêm vào `failed_nodes`.
- `failure_impact_report()`: tìm finger table stale và resource bị ảnh hưởng.
- `_stale_finger_entries()`: tìm finger trỏ tới failed node.
- `_affected_resources()`: tìm resource có owner/replica bị ảnh hưởng.

Vì sao không tự recover ngay: để UI có thể hiển thị trạng thái lỗi trước khi sửa.

### `recover_node()` - `POST /api/recover`

Hàm này sửa trạng thái sau khi node bị kill.

Luồng:

```text
Đọc payload
  -> lock
  -> _autoload_once()
  -> parse node_id
  -> ring.recover_failed_node(node_id)
  -> _save_ring_state(ring)
  -> trả report + state
```

Các hàm sâu được gọi:

- `recover_failed_node()`: điều phối toàn bộ recovery.
- `_repair_fingers_referencing()`: sửa finger trỏ tới failed node.
- `_recover_resources_after_node_failure()`: lấy resource từ replica còn sống.
- `_reconcile_resource_owners_after_recovery()`: sửa owner theo topology mới.
- `_place_resource_copies()`: đặt lại owner/replica copy.

Vì sao recover không bị `_require_no_pending_recovery()` chặn: recover chính là thao tác giải quyết pending recovery.

### `delete_node(node_id)` - `DELETE /api/node/<node_id>`

Hàm này xóa node khỏi mô hình.

Luồng:

```text
Lock
  -> _autoload_once()
  -> _require_no_pending_recovery()
  -> kiểm tra node tồn tại
  -> nếu node active thì ring.kill_node(node_id)
  -> del ring.nodes[node_id]
  -> ring.failed_nodes.discard(node_id)
  -> ring.stabilize()
  -> _save_ring_state(ring)
  -> trả state
```

Lưu ý: `ring.kill_node()` trong `ChordRing` khác API `/api/kill`. Method `kill_node()` của `ChordRing` gọi `mark_node_failed()` rồi recover ngay. Còn API `/api/kill` chỉ gọi `mark_node_failed()` để giữ trạng thái pending.

### `add_node()` - `POST /api/node`

Hàm này thêm node mới hoặc bật lại node inactive.

Luồng:

```text
Đọc payload
  -> lock
  -> _autoload_once()
  -> _require_no_pending_recovery()
  -> đọc node_id tùy chọn
  -> ring.add_node(...)
  -> _save_ring_state(ring)
  -> trả report + state
```

Các hàm sâu được gọi:

- `_next_available_node_id()` nếu không truyền ID.
- `_validate_identifier()` nếu có truyền ID.
- `join()` để node mới tham gia qua known node.
- `run_protocol_until_stable()` để routing hội tụ.
- `_rebalance_resources_after_node_join()` để chuyển các key thuộc node mới.

### `add_resource()` - `POST /api/resource`

Hàm này thêm resource.

Luồng:

```text
Đọc resource_id
  -> validate không rỗng
  -> lock
  -> _autoload_once()
  -> _require_no_pending_recovery()
  -> ring.add_resource(resource_id)
  -> _save_ring_state(ring)
  -> trả resource + state + trace put
```

Các hàm sâu được gọi:

- `hash_resource()`: tạo SHA-1 digest và key.
- `_route_key(operation="Put")`: tìm owner qua overlay.
- `_place_resource_copies()`: ghi vào owner và replica.

### `update_resource()` - `PUT /api/resource`

Hàm này đổi ID resource.

Luồng:

```text
Đọc old_resource_id và new_resource_id
  -> validate cả hai không rỗng
  -> lock
  -> _autoload_once()
  -> _require_no_pending_recovery()
  -> ring.update_resource(old_id, new_id)
  -> _save_ring_state(ring)
  -> trả resource mới + trace put + state
```

Vì đổi ID làm đổi key, hệ thống phải route lại như một resource mới. Đây là lý do update được triển khai như “xóa copy cũ rồi put copy mới”.

### `delete_resource()` - `DELETE /api/resource`

Hàm này xóa resource khỏi owner và replica.

Luồng:

```text
Đọc resource_id
  -> validate không rỗng
  -> lock
  -> _autoload_once()
  -> _require_no_pending_recovery()
  -> ring.delete_resource(resource_id)
  -> _save_ring_state(ring)
  -> trả resource đã xóa + trace delete + state
```

Các hàm sâu được gọi:

- `hash_resource()`: tính key của resource.
- `_route_key(operation="Delete")`: tìm owner thật.
- `_remove_resource_copies()`: xóa copy ở owner và replica.

### `metrics_requires_post()` - `GET /api/metrics`

Hàm này luôn trả 405.

Vì sao: chạy benchmark có side effect như tốn CPU, tạo ảnh chart, cập nhật last metrics. GET không nên dùng cho thao tác như vậy.

### `metrics_current_ring()` - `POST /api/metrics`

Hàm này chạy benchmark lookup.

Luồng:

```text
Đọc trials/lookups/metric_seed
  -> lock
  -> _autoload_once()
  -> _require_no_pending_recovery()
  -> lấy live_resources
  -> lấy node IDs, m, replication_count
  -> run_current_ring_metrics()
  -> nhả coordinator_lock
  -> lấy plot_lock
  -> build_growth_node_sizes()
  -> run_lookup_metrics()
  -> save_metric_charts_from_points()
  -> lưu last_metrics_payload
  -> lock lại
  -> _autoload_once()
  -> _save_ring_state(ring)
  -> trả sweep_points + charts
```

Vì sao có hai lock:

- `coordinator_lock` bảo vệ ring.
- `plot_lock` bảo vệ matplotlib và file ảnh chart vì matplotlib không nên bị nhiều request vẽ song song.

### `metrics_last()` - `GET /api/metrics/last`

Hàm này trả metric gần nhất trong `last_metrics_payload`.

Luồng:

```text
Lock
  -> _autoload_once()
  -> nếu chưa có metric thì ok=false
  -> nếu có thì trả metrics
```

Metric này có thể được khôi phục từ `state.json` nhờ `_ring_state_from_json()`.

### `topology()` - `POST /api/topology`

Hàm này sinh ảnh topology graph.

Luồng:

```text
Đọc include_last_path và lookup_path
  -> lock
  -> _autoload_once()
  -> nếu cần highlight thì chuẩn hóa lookup_path thành list int
  -> plot_lock
  -> save_topology_graph(ring, path, lookup_path, title)
  -> trả chart_url có query timestamp chống cache
```

Vì sao cần timestamp trong URL: nếu không thêm `?_={time.time_ns()}`, browser có thể cache ảnh cũ và không hiển thị topology mới.

## 14. Giải Thích Kỹ Các Hàm Chính Trong `ChordRing`

### Nhóm khởi tạo và cấu hình

| Hàm | Làm gì | Vì sao cần |
| --- | --- | --- |
| `__init__()` | Tạo ring rỗng, đặt `m`, `identifier_space = 2^m`, `seed`, `replication_count`, `nodes`, `failed_nodes`, `resources`. | Chuẩn bị trạng thái nền cho mô phỏng Chord. |
| `_validate_replication_count()` | Ép `replication_count` sang int và không cho âm. | Replica âm không có nghĩa trong lưu trữ. |
| `active_node_ids` | Trả danh sách node active đã sort. | Chord cần thứ tự vòng để tìm successor/predecessor và render trạng thái. |

### Nhóm initialize và join

| Hàm | Làm gì | Vì sao cần |
| --- | --- | --- |
| `initialize_network()` | Xóa ring cũ, sinh node ID, cho node join, chạy protocol hội tụ, sinh resource và đặt copy. | Tạo mạng demo hoàn chỉnh từ cấu hình người dùng. |
| `_generate_unique_ids()` | Sinh ID duy nhất bằng `hash_identifier(prefix:seed:attempt)`. | Đảm bảo node ID tái lập theo seed và không trùng. |
| `join()` | Cho node mới tham gia thông qua known node, route để tìm successor ban đầu. | Đúng mô hình Chord: node mới cần biết ít nhất một peer trong ring. |
| `_routing_snapshot()` | Chụp predecessor/successor/finger table của active nodes. | Dùng để biết protocol đã hội tụ chưa. |

### Nhóm protocol Chord

| Hàm | Làm gì | Vì sao cần |
| --- | --- | --- |
| `run_protocol_tick()` | Mỗi tick chạy `stabilize_one`, `check_predecessor_one`, `fix_fingers_one` cho từng node. | Mô phỏng chu kỳ bảo trì nền của Chord. |
| `run_protocol()` | Chạy nhiều tick. | Tiện cho các thao tác cần chạy protocol một số vòng cố định. |
| `run_protocol_until_stable()` | Chạy tick tới khi snapshot không đổi sau ít nhất `m` tick. | Finger table có `m` dòng, cần đủ tick để cập nhật hết. |
| `stabilize_one()` | Sửa successor của một node và gửi notify cho successor. | Đây là bước chính giúp ring tự ổn định khi join/failure. |
| `notify()` | Cho node đích cập nhật predecessor nếu caller nằm gần hơn. | Đúng với Chord stabilize: successor biết predecessor mới qua notify. |
| `check_predecessor_one()` | Nếu predecessor chết thì xóa predecessor. | Tránh node giữ liên kết tới peer không còn active. |
| `fix_fingers_one()` | Cập nhật một dòng finger table theo công thức `successor(node + 2^(i-1))`. | Giữ finger table đúng để lookup đạt gần `O(log N)`. |
| `stabilize()` | Chạy protocol tới ổn định và trả report. | Dùng sau khi xóa node hoặc cần sửa routing state. |

### Nhóm định tuyến và lookup

| Hàm | Làm gì | Vì sao cần |
| --- | --- | --- |
| `find_successor()` | Trả owner/successor của một key bằng `_route_key()`. | API nhỏ để tìm node chịu trách nhiệm key. |
| `_active_successor_for_key()` | Tìm successor của key từ danh sách active node. | Dùng trong mô phỏng để tính finger target chuẩn và sửa routing. |
| `_route_key()` | Định tuyến nhiều hop từ start node tới owner của key, ghi path/hops/logs. | Đây là lõi lookup/put/delete/join theo overlay Chord. |
| `lookup()` | Chuẩn hóa resource/key, route tới owner, kiểm tra resource tồn tại, trả `LookupResult`. | Là hàm phục vụ `/api/lookup`. |
| `_resolve_lookup_key()` | Nếu input là số thì dùng làm key trực tiếp, nếu là chuỗi thì hash. | Cho phép demo cả lookup theo resource ID và key số. |
| `_resolve_start_node()` | Chọn node bắt đầu hoặc validate node người dùng truyền. | Lookup trong Chord có thể bắt đầu từ một peer bất kỳ. |
| `_node_owns_key()` | Kiểm tra key thuộc khoảng `(predecessor, node]`. | Đây là định nghĩa owner trong Chord. |
| `_select_next_hop()` | Chọn bước tiếp theo: owner successor, closest preceding finger, hoặc fallback successor. | Quyết định đường đi từng hop của lookup. |
| `_closest_preceding_finger()` | Duyệt finger table từ xa về gần để chọn finger nằm trước key. | Đây là heuristic chuẩn giúp Chord nhảy nhanh. |
| `_repair_node_after_failure()` | Khi route phát hiện successor/finger chết, sửa view cục bộ node hiện tại. | Giúp lookup không kẹt vào node lỗi; data recovery vẫn để workflow recover xử lý. |

### Nhóm node CRUD

| Hàm | Làm gì | Vì sao cần |
| --- | --- | --- |
| `_validate_identifier()` | Kiểm tra node ID nằm trong `0..2^m-1`. | Node ID ngoài không gian ring là không hợp lệ. |
| `_next_available_node_id()` | Tự tìm một ID chưa dùng. | Hỗ trợ thêm node không cần nhập ID tay. |
| `add_node()` | Tạo/bật lại node, join ring, chạy protocol, rebalance resource. | Mô phỏng node join trong Chord. |
| `kill_node()` | Gọi `mark_node_failed()` rồi `recover_failed_node()` ngay. | Dùng cho thao tác xóa node cần kill và repair liền. |
| `mark_node_failed()` | Đánh dấu node inactive và đưa vào `failed_nodes`, chưa sửa routing/resource. | Phục vụ demo trạng thái failure trước recovery. |
| `recover_failed_node()` | Sửa link, finger table, resource và replica sau failure. | Khôi phục ring về trạng thái có thể hoạt động tiếp. |
| `failure_impact_report()` | Tạo report về finger/resource bị ảnh hưởng bởi failed node. | Giúp UI giải thích hậu quả của kill. |

### Nhóm resource CRUD và replication

| Hàm | Làm gì | Vì sao cần |
| --- | --- | --- |
| `add_resource()` | Hash resource, route Put tới owner, tạo record, đặt copy. | Ghi resource đúng node `successor(key)`. |
| `update_resource()` | Route owner cũ, xóa copy cũ, hash ID mới, route Put copy mới. | Đổi ID làm đổi key nên phải định tuyến lại. |
| `delete_resource()` | Hash ID, route Delete tới owner, xóa owner và replica copy. | Xóa đúng nơi resource đang được quản lý. |
| `_rebalance_resources_after_node_join()` | Điều phối chuyển primary và refresh replica khi node mới join. | Node mới chỉ nhận một khoảng key, không di chuyển toàn bộ dữ liệu. |
| `_adopt_primary_resources_for_joined_node()` | Chuyển resource trong `(predecessor, new_node]` từ successor cũ sang node mới. | Đúng quy tắc successor ownership của Chord. |
| `_refresh_replica_sets_around_joined_node()` | Cập nhật replica quanh node mới. | Successor chain thay đổi khi node chen vào vòng. |
| `_replica_nodes_for_owner()` | Tìm các node successor sau owner để đặt replica. | Replication theo successor chain giúp recover khi owner chết. |
| `_copy_holder_ids()` | Gom owner và replica holder của resource. | Cần biết các node đang giữ copy trước khi sync/xóa. |
| `_remove_resource_copies()` | Xóa resource khỏi owner/replica cũ. | Tránh copy stale sau delete/update/rebalance. |
| `_place_resource_copies()` | Tính replica mới rồi gọi sync. | Dùng chung cho add/update/recovery/rebalance. |
| `_sync_resource_copies()` | Xóa copy không còn hợp lệ và ghi copy vào owner/replica active. | Đảm bảo local storage của node khớp metadata. |

### Nhóm recovery sâu

| Hàm | Làm gì | Vì sao cần |
| --- | --- | --- |
| `_find_active_successor()` | Tìm successor active dựa trên view cục bộ, rồi fallback theo danh sách active. | Sửa successor khi node hiện tại biết successor đã chết. |
| `_find_active_predecessor()` | Tìm predecessor active gần nhất. | Sửa predecessor khi predecessor cũ chết. |
| `_unique_active_local_resources()` | Gom resource còn có copy trên node active. | Dùng làm nguồn sự thật khi recover/metrics. |
| `_drop_lost_resources_from_metadata()` | Xóa metadata của resource không còn copy sống. | Nếu mất hết replica thì không thể khôi phục. |
| `_live_resource_copy_holders()` | Tìm các node active đang giữ copy của một resource. | Xác định resource còn phục hồi được không. |
| `_recover_resources_after_node_failure()` | Promote/copy resource từ replica sống sau khi owner/replica chết. | Khôi phục dữ liệu sau failure. |
| `_reconcile_resource_owners_after_recovery()` | Sửa owner theo `successor(key)` sau recovery. | Đảm bảo metadata đúng topology mới. |
| `_repair_fingers_referencing()` | Tìm và sửa finger entries trỏ tới failed node. | Tránh lookup đi vào node chết. |

### Nhóm báo cáo và kiểm tra

| Hàm | Làm gì | Vì sao cần |
| --- | --- | --- |
| `resource_distribution()` | Đếm số resource theo owner. | Hiển thị phân bố dữ liệu. |
| `_stale_finger_entries()` | Liệt kê finger trỏ tới failed node. | Dùng trong impact report. |
| `_affected_resources()` | Liệt kê resource có owner/replica bị failed. | Dùng trong impact report. |
| `node_details()` | Trả chi tiết một node. | Phục vụ `/api/node/<id>`. |
| `summary()` | Trả snapshot tổng quan ring. | Phục vụ `/api/state` và nhiều API trả state. |
| `export_finger_tables()` | Xuất finger table dạng dict. | Hỗ trợ kiểm tra/báo cáo. |
| `verify_resource_mapping()` | Kiểm tra mỗi resource có owner đúng `successor(key)`. | Đảm bảo mapping dữ liệu đúng Chord. |
| `verify_finger_tables()` | Kiểm tra finger table đúng công thức successor(start). | Đảm bảo routing table đúng Chord. |
| `choose_random_resource()` | Chọn resource ngẫu nhiên. | Dùng cho demo/metrics. |
| `choose_random_node()` | Chọn node active ngẫu nhiên. | Dùng cho demo/metrics. |

## 15. Giải Thích Các Hàm Trong `identifiers.py`

| Hàm | Làm gì | Vì sao đúng với Chord |
| --- | --- | --- |
| `hash_identifier(value, m)` | SHA-1 input rồi lấy modulo `2^m`. | Chord ánh xạ node/key vào cùng một vòng định danh. |
| `hash_resource(resource_id, m)` | Trả cả SHA-1 digest đầy đủ và key `mod 2^m`. | Digest để hiển thị, key để định tuyến. |
| `in_clockwise_interval(value, start, end, ...)` | Kiểm tra value có nằm trong khoảng clockwise, kể cả wrap qua 0. | Vòng Chord có điểm wrap, nên interval thường không thể kiểm tra bằng so sánh tuyến tính đơn giản. |

Ví dụ với `m = 4`, không gian ID là `0..15`. Khoảng `(12, 3]` là khoảng wrap qua 0, nên chứa `13, 14, 15, 0, 1, 2, 3`. Đây là lý do `in_clockwise_interval()` phải xử lý riêng trường hợp `start > end`.

## 16. Giải Thích Các Hàm Metrics Và Topology

### Trong `metrics.py`

| Hàm | Vai trò |
| --- | --- |
| `_empty_metric_accumulator()` | Tạo bộ đếm rỗng cho benchmark. |
| `_record_lookup_sample()` | Ghi một mẫu lookup: thành công/thất bại, hops, latency, message overhead. |
| `_copy_resource_records()` | Copy resource records để benchmark không phá state thật. |
| `_join_metric_node()` | Cho node join vào ring metric. |
| `_place_existing_resources_on_metric_ring()` | Đặt lại resource có sẵn lên ring metric. |
| `_build_metric_point()` | Tổng hợp accumulator thành một điểm metric. |
| `run_current_ring_metrics()` | Chạy benchmark trên ring hiện tại. |
| `build_growth_node_sizes()` | Sinh danh sách kích thước node để sweep. |
| `run_lookup_metrics()` | Chạy benchmark nhiều kích thước node. |
| `_save_metric_chart()` | Lưu biểu đồ metric ra file ảnh. |

Metrics dùng để kiểm tra hành vi lookup có gần xu hướng `O(log N)` không. Đây là kiểm chứng thực nghiệm cho phần lý thuyết Chord.

### Trong `visualization.py`

| Hàm | Vai trò |
| --- | --- |
| `build_topology_graph()` | Tạo graph từ node, successor, finger table, resource/failure metadata. |
| `circular_identifier_positions()` | Tính vị trí node trên đường tròn theo ID. |
| `save_topology_graph()` | Vẽ graph ra ảnh PNG và trả report. |

Topology không phải thuật toán Chord cốt lõi. Nó là công cụ trực quan hóa để thấy vòng, liên kết và đường lookup.

## 17. Một Luồng Demo Đầy Đủ Theo Thứ Tự Hàm

Ví dụ người dùng mở app, initialize, lookup, kill, recover:

```text
GET /
  -> index()

GET /api/state
  -> state()
  -> _autoload_once()
  -> _load_ring_state()
  -> _ring_state_from_json()
  -> ring.summary()

POST /api/initialize
  -> initialize_network() trong app.py
  -> parse_int_field()
  -> ChordRing.__init__()
  -> ChordRing.initialize_network()
  -> _generate_unique_ids()
  -> join()
  -> _route_key(operation="Join")
  -> run_protocol_until_stable()
  -> stabilize_one()
  -> notify()
  -> check_predecessor_one()
  -> fix_fingers_one()
  -> hash_resource()
  -> _route_key(operation="Put")
  -> _place_resource_copies()
  -> _save_ring_state()
  -> _save_initial_dataset_files()

POST /api/lookup
  -> lookup_resource()
  -> _require_no_pending_recovery()
  -> ChordRing.lookup()
  -> _resolve_lookup_key()
  -> _resolve_start_node()
  -> _route_key(operation="Lookup")
  -> _node_owns_key()
  -> _select_next_hop()
  -> _closest_preceding_finger()
  -> _save_ring_state()

POST /api/kill
  -> kill_node() trong app.py
  -> _require_no_pending_recovery()
  -> mark_node_failed()
  -> failure_impact_report()
  -> _stale_finger_entries()
  -> _affected_resources()
  -> _save_ring_state()

POST /api/recover
  -> recover_node()
  -> recover_failed_node()
  -> _repair_fingers_referencing()
  -> _recover_resources_after_node_failure()
  -> _reconcile_resource_owners_after_recovery()
  -> _save_ring_state()
```

Nhìn theo chuỗi này có thể thấy rõ vai trò của từng lớp:

- `app.py` nhận HTTP, khóa state, validate, persist.
- `ChordRing` xử lý thuật toán Chord.
- `identifiers.py` xử lý hash và interval vòng.
- `metrics.py` đo hiệu năng lookup.
- `visualization.py` sinh ảnh để giải thích topology.
