# Báo Cáo Phân Tích Thiết Kế

**Dự án:** Simple Chord DHT Implementation: *The Hash Ring*
**Chủ đề:** #61 - Peer-to-Peer Data Management / Chord Distributed Hash Table

## 1. Tổng Quan

Dự án cài đặt giao thức **Chord DHT** ở chế độ single-process simulation trong một Flask process duy nhất. Chord là một giao thức P2P có cấu trúc cho phép tìm kiếm dữ liệu với độ phức tạp O(log N), trong đó mỗi node chỉ cần duy trì thông tin định tuyến cục bộ thay vì toàn bộ mạng.

**Đặc điểm chính của triển khai:**

- **Single-process simulation**: Tất cả node được mô phỏng trong bộ nhớ
- **In-memory routing**: Lookup thực hiện qua lời gọi hàm thay vì HTTP
- **State persistence**: Trạng thái ring được lưu vào JSON
- **Visualization**: Topology graph và performance metrics được vẽ bằng Matplotlib

## 2. Đối Chiếu Yêu Cầu Topic 61

| Yêu cầu | Triển khai |
|----------|------------|
| 10-50 node | Hỗ trợ 10-100 node trong không gian m=16 bit |
| 1.000 Resource_IDs | Sinh tự động từ `resource-0001` đến `resource-1000` |
| SHA-1 hashing | Dùng SHA-1 cho cả node_id và resource key |
| Finger Table | Mỗi node duy trì m entries (m=16 mặc định) |
| Lookup O(log N) | Closest preceding finger algorithm |
| Node churn | Thêm, xóa, dừng node với stabilization |
| Replication | Mỗi resource có r bản sao (mặc định r=3) |
| Failure recovery | Phục hồi từ replica còn sống |

## 3. Thiết Kế Lõi

### 3.1 Consistent Hashing

Chord sử dụng consistent hashing để phân phối resource đều trên các node:

```text
Resource_Key = SHA1(Resource_ID) mod 2^m
Owner_Node = successor(Resource_Key)
```

**Nguyên tắc successor:**
- Node `n` chịu trách nhiệm cho tất cả key trong khoảng `(predecessor(n), n]`
- Key luôn được gán cho node đầu tiên ≥ key theo chiều kim đồng hồ

**Lợi ích:**
- Không cần bảng `resource → owner` tập trung
- Khi node join/leave, chỉ vùng lân cận cần thay đổi
- Phân phối đều do SHA-1 có tính ngẫu nhiên tốt

### 3.2 Finger Table

Mỗi node duy trì finger table với m entries:

```text
start_i = (n + 2^(i-1)) mod 2^m
finger_i = successor(start_i)
```

**Ví dụ với m=4 (không gian 16 giá trị):**

| i | start_i | Khoảng cách | Mục đích |
|---|---------|-------------|-----------|
| 1 | n+1 | 1 | Kiểm tra node kế tiếp |
| 2 | n+2 | 2 | Kiểm tra 2 nodes |
| 3 | n+4 | 4 | Kiểm tra 4 nodes |
| 4 | n+8 | 8 | Kiểm tra 8 nodes |

### 3.3 Lookup Algorithm

```python
def lookup(key):
    if key in (predecessor, current]:
        return current  # current is owner
    else:
        n = closest_preceding_finger(key)
        return n.lookup(key)  # recursive
```

**Closest Preceding Finger:**
```python
def closest_preceding_finger(key):
    for i in reversed(range(m)):
        if finger[i].node in (current, key):
            return finger[i].node
    return successor
```

## 4. Phân Tích Độ Phức Tạp O(log N)

### 4.1 Tại Sao O(log N)?

Nếu chỉ đi qua successor từng bước, trường hợp xấu nhất là O(N) khi key nằm ngược chiều kim đồng hồ.

**Finger Table giải quyết vấn đề:**

```
Khoảng cách từ node đến các finger:
  finger[1]: 1
  finger[2]: 2  
  finger[3]: 4
  finger[4]: 8
  ...
  finger[m]: 2^(m-1)
```

### 4.2 Phân Tích Toán Học

Sau mỗi hop qua closest preceding finger, số ứng viên còn lại giảm khoảng một nửa:

```
Số ứng viên còn lại ≈ N / 2^h
```

Lookup kết thúc khi chỉ còn 1 ứng viên:

```
N / 2^h ≤ 1
⇒ h ≥ log₂(N)
```

### 4.3 Kết Quả Kỳ Vọng

| Số node (N) | log₂(N) | Max hops lý thuyết |
|-------------|---------|---------------------|
| 10 | 3.32 | ~4 |
| 20 | 4.32 | ~5 |
| 30 | 4.91 | ~5 |
| 40 | 5.32 | ~6 |
| 50 | 5.64 | ~6 |

## 5. Replication Và Fault Tolerance

### 5.1 Chiến Lược Replication

Mỗi resource được lưu trên `r` nodes:
- 1 owner (primary)
- `r-1` successors (replicas)

**Ví dụ với r=3:**

```
Resource R có key K
  → Owner: successor(K)
  → Replica 1: successor(owner)
  → Replica 2: successor(replica1)
```

### 5.2 Failure Recovery

**Khi node chết:**

1. **Detection**: Predecessor/successor được đánh dấu inactive
2. **Link Repair**: Predecessor và successor được nối trực tiếp
3. **Finger Fix**: Các finger trỏ đến node chết được sửa
4. **Data Recovery**: Resources được migrate từ replica còn sống

**Recovery Algorithm:**

```python
def recover_resources_after_failure(failed_node):
    for resource in resources_with_failed_owner:
        if has_live_replica(resource):
            new_owner = successor(resource.key)
            promote_replica_to_owner(new_owner, resource)
        else:
            mark_resource_lost(resource)
```

### 5.3 Trade-offs

| Kịch bản | Availability | Consistency |
|-----------|--------------|-------------|
| Owner chết, replica sống | ✅ Recovered | ✅ Primary promoted |
| Owner chết, không replica | ❌ Lost | N/A |
| Replica thiếu | ⚠️ Degraded | ✅ Write succeeds |

## 6. Đo Lường Và Benchmark

### 6.1 Metrics Thu Thập

| Chỉ số | Mô tả | Cách đo |
|---------|--------|---------|
| Average hops | Số hop trung bình | Đếm từ lookup trace |
| Max hops | Số hop tối đa | Max từ trace |
| Success rate | Tỷ lệ thành công | Số thành công / tổng |
| Latency | Thời gian lookup | Thời gian thực thi |
| Overhead | Message/lookup | Số hop trung bình |

### 6.2 Benchmark Configuration

```python
config = {
    "node_sizes": [10, 20, 30, 40, 50],
    "trials": 5,
    "lookups_per_trial": 100,
    "resource_count": 1000,
    "m": 16,
    "seed": 61
}
```

### 6.3 Visualization Outputs

- **Topology Graph**: Cấu trúc vòng Chord với fingers
- **Hops Chart**: So sánh hops thực tế với O(log N)
- **Latency Chart**: Thời gian lookup theo số node
- **Overhead Chart**: Message overhead

## 7. Thiết Kế State Persistence

### 7.1 Atomic Write

```python
def save_ring_state(ring):
    # 1. Tạo file tạm
    tmp = Path(f"state.json.tmp-{pid}-{timestamp}")
    
    # 2. Ghi JSON
    json.dump(state, tmp, ensure_ascii=False, indent=2)
    tmp.flush()
    os.fsync(tmp.fileno())
    
    # 3. Atomic rename
    tmp.replace("state.json")
```

### 7.2 Auto-load

Trạng thái được tự động load khi Flask app khởi động:

```python
def _autoload_once():
    if STATE_PATH.exists():
        ring = load_ring_state(STATE_PATH)
        return ring
    return None
```

## 8. So Sánh Với Lý Thuyết

### 8.1 Chord Protocol Gốc vs Triển Khai

| Khía cạnh | Chord gốc | Triển khai |
|------------|-----------|-------------|
| Giao tiếp | RPC thực | In-memory calls |
| Persistence | Database/file per node | Single JSON |
| Process model | Multi-process | Single-process |
| Failure detection | Timeout/heartbeat | In-memory flag |
| Network | Real P2P network | Localhost simulation |

### 8.2 Điểm Giống Nhau

- ✅ Finger table structure
- ✅ Successor rule
- ✅ Closest preceding finger
- ✅ O(log N) lookup complexity
- ✅ Stabilization protocol
- ✅ Replication scheme

## 9. Kết Luận

Triển khai Chord DHT simulation đạt được các mục tiêu:

1. **Đúng protocol**: Finger table, successor rule, lookup algorithm tuân thủ Chord gốc
2. **O(log N)**: Số hops tăng theo logarithm của số node
3. **Fault tolerance**: Replication và recovery hoạt động đúng
4. **Visualization**: Topology và metrics được trực quan hóa
5. **Persistence**: State được lưu và khôi phục

Điểm khác biệt chính với deployment thực:
- Single-process thay vì multi-process
- In-memory thay vì HTTP/RPC
- Centralized JSON thay vì distributed files

Những khác biệt này phù hợp với mục đích mô phỏng và giáo dục của dự án.

## Tài Liệu Tham Khảo

1. Ion Stoica et al., *Chord: A Scalable Peer-to-Peer Lookup Service for Internet Applications*, [MIT PDOS](https://pdos.csail.mit.edu/6.824/papers/stoica-chord.pdf)

2. M. T. Özsu và P. Valduriez, *Principles of Distributed Database Systems*, phần structured P2P/DHT

3. Các tài liệu trong dự án:
   - `README.md` - Hướng dẫn sử dụng
   - `docs/design_document.md` - Thiết kế chi tiết
   - `docs/project_proposal.md` - Đề xuất dự án
