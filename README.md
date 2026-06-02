# Simple Chord DHT Implementation

Ung dung web mo phong **Chord Distributed Hash Table (DHT)** cho de tai **Topic 61 - Simple Chord DHT Implementation**. Du an minh hoa cach node va resource duoc anh xa vao vong dinh danh, cach lookup dung finger table, cach node join/failure anh huong toi topology, va cach replication giup phuc hoi du lieu khi node loi.

> Day la mo phong single-process phuc vu hoc tap va demo. Moi node la mot object trong bo nho, khong phai mot process/may doc lap trong mang P2P that.

## Thong Tin Du An

| Muc | Noi dung |
| --- | --- |
| Chu de | Topic 61 - Simple Chord DHT Implementation |
| Mon hoc | Co So Du Lieu Phan Tan |
| Ngon ngu | Python, JavaScript, HTML, CSS |
| Backend | Flask |
| Visualization | Matplotlib, NetworkX |
| Kieu trien khai | Single-process Chord simulator |

## Tinh Nang Chinh

- Khoi tao Chord ring voi so node, so resource, `m`, `seed` va `replication_count`.
- Hash node/resource vao cung khong gian dinh danh `2^m`.
- Xac dinh owner cua resource theo quy tac `successor(resource_key)`.
- Hien thi `successor`, `predecessor`, finger table va local resource cua tung node.
- Lookup resource bang Chord routing va `closest preceding finger`.
- Them node moi va rebalance dung khoang key bi anh huong.
- Kill node de mo phong failure, hien thi impact truoc recovery.
- Recover node failure bang cach sua ring, sua finger table, promote primary tu replica song va dat lai replica.
- Hien thi topology, lookup path, resource distribution va metrics.
- Luu trang thai ring vao `data/state.json` de autoload sau khi restart server.

## Ly Thuyet Chord Duoc Mo Phong

### Vong dinh danh

Chord dung khong gian dinh danh dang vong:

```text
identifier_space = 2^m
```

Voi cau hinh thuong dung `m = 16`, ID nam trong khoang:

```text
0 -> 65535
```

Node ID va resource key duoc sinh bang SHA-1 roi rut gon vao khong gian `2^m`:

```text
node_id      = SHA1(...) mod 2^m
resource_key = SHA1(resource_id) mod 2^m
```

### Seed

`seed` giup ket qua random co the tai lap. Neu dung cung mot seed, danh sach node ID/resource ID sinh ra se giong nhau giua cac lan chay. Dieu nay giup demo va debug on dinh, vi du loi o node `18652` co the tai hien lai chinh xac.

### Owner cua resource

Resource duoc luu chinh tai node `successor(resource_key)`:

```text
owner(resource) = successor(resource_key)
```

`successor(key)` la node active dau tien theo chieu kim dong ho co ID lon hon hoac bang key. Neu khong co node nao lon hon key, ket qua quay vong ve node nho nhat.

Vi du:

```text
active nodes = [18652, 19570, 24076, 30016, 37252]
resource_key = 26844
owner = 30016
```

### Khoang so huu cua node

Mot node `n` so huu cac key nam trong khoang:

```text
(predecessor(n), n]
```

Vi du node `3265` co predecessor la `60689`, thi khoang so huu la:

```text
(60689, 3265]
```

Khoang nay wrap qua 0, nen key `1202` thuoc ve node `3265`.

### Finger table

Moi node co `m` dong finger table. Voi node `n`, dong thu `i` duoc tinh:

```text
start_i = (n + 2^(i - 1)) mod 2^m
end_i   = (n + 2^i) mod 2^m
node_i  = successor(start_i)
```

Finger table khong chon node ngau nhien. Moi dong dai dien cho mot buoc nhay theo luy thua cua 2, giup lookup di nhanh hon thay vi duyet tung successor.

Vi du voi node `18652`, `m = 16`:

```text
finger #14:
start = 18652 + 2^13 = 26844
node  = successor(26844)
```

Neu node active dau tien sau `26844` la `30016`, thi finger #14 phai tro toi `30016`.

### Lookup

Lookup dung finger table de dinh tuyen toi owner:

```text
1. Bat dau tu mot node active.
2. Neu key thuoc (predecessor(current), current], current la owner.
3. Neu key thuoc (current, successor], successor la owner.
4. Neu chua toi owner, chon closest preceding finger gan key nhat.
5. Lap lai cho toi khi tim duoc owner.
```

Diem quan trong:

- `closest_preceding_finger` dung cho qua trinh lookup/routing.
- Finger table duoc tinh bang `successor(start)`.
- Verify finger table cung so voi `successor(start)`, khong dung route de tranh che loi khi bang dang stale.

## Replication

Moi resource co:

```text
owner_id
replica_node_ids
```

Owner la node chinh. Replica duoc dat tren cac successor ke tiep cua owner, khong trung owner.

Vi du:

```text
owner = 30016
successor chain = 30016 -> 37252 -> 51502
replication_count = 2
replica_node_ids = [37252, 51502]
```

Neu `replication_count` lon hon so node co the dat replica, he thong dung `effective_replica_count`:

```text
effective_replica_count = min(replication_count, active_nodes - 1)
```

## Node Join

Khi them node moi:

```text
1. Node moi duoc gan node_id.
2. Node duoc chen vao dung vi tri tren vong.
3. Successor/predecessor duoc stabilize lai.
4. Finger table chay protocol toi khi stable.
5. Resource thuoc khoang (predecessor(new_node), new_node] chuyen sang node moi.
6. Replica placement duoc tinh lai.
```

Y nghia ly thuyet: nho consistent hashing, node join khong lam phan phoi lai toan bo du lieu, chi cac key trong khoang node moi chiu trach nhiem bi anh huong.

## Node Failure Va Recovery

Flow failure trong du an duoc tach thanh hai buoc de de demo.

### 1. Kill node

Khi bam **Kill**, node duoc danh dau inactive va them vao `failed_nodes`. He thong chua phuc hoi ngay, ma hien thi impact:

- Failed node.
- Old predecessor va old successor.
- Cac finger entry dang tro toi failed node.
- Primary resource do failed node lam owner.
- Replica resource dang dat tren failed node.

Node failed khong con duoc xem la nguon du lieu tin cay.

### 2. Recover

Khi bam **Recover**, he thong thuc hien:

```text
1. Xac nhan node failed.
2. Noi old predecessor voi old successor de va ring.
3. Sua finger table dang tro toi node chet bang successor(entry.start).
4. Voi primary resource bi anh huong, promote tu replica con song.
5. Voi replica resource bi anh huong, loai replica chet va dat replica moi.
6. Don metadata resource bi mat neu khong con ban copy active.
```

Neu primary resource khong con replica song, resource duoc xem la lost.

## Protocol Tick Va Stabilization

Du an co hai ham chinh de mo phong protocol Chord:

```text
run_protocol_tick()
run_protocol_until_stable()
```

Mot tick thuc hien tren toan bo node active:

```text
1. stabilize_one(node)
2. check_predecessor_one(node)
3. fix_fingers_one(node)
```

Moi tick chi sua mot dong finger table tren moi node. Vi finger table co `m` dong, `run_protocol_until_stable()` chay toi thieu `m` tick de quet du mot vong finger table, roi dung khi routing snapshot khong con thay doi.

## Kien Truc

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

| Thanh phan | Vai tro |
| --- | --- |
| `app.py` | Flask server, API, persist state, dieu phoi metrics/topology |
| `src/chord_dht/chord.py` | Lop `ChordRing`, core Chord logic, lookup, join, recovery, replication |
| `src/chord_dht/models.py` | `Node`, `FingerEntry`, `ResourceRecord`, `LookupResult` |
| `src/chord_dht/identifiers.py` | Hash ID va kiem tra interval tren vong Chord |
| `src/chord_dht/metrics.py` | Benchmark lookup va du lieu metrics |
| `src/chord_dht/visualization.py` | Sinh topology graph |
| `templates/index.html` | Giao dien chinh |
| `static/app.js` | Logic frontend va render UI |
| `tests/test_distributed_chord.py` | Test API va logic Chord |

## Cau Truc Thu Muc

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

## Cai Dat

Yeu cau:

- Python 3.10 tro len
- pip
- Windows PowerShell hoac terminal tuong duong

Cai bang virtual environment:

```powershell
py -3.10 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Hoac cai tu `requirements.txt`:

```powershell
python -m pip install -r requirements.txt
```

## Chay Ung Dung

```powershell
.\.venv\Scripts\python.exe app.py
```

Mac dinh server chay tai:

```text
http://127.0.0.1:5000
```

Co the doi host/port:

```powershell
$env:HOST = "0.0.0.0"
$env:PORT = "8080"
.\.venv\Scripts\python.exe app.py
```

## API Chinh

### State va resource

| Method | Endpoint | Mo ta |
| --- | --- | --- |
| `GET` | `/` | Giao dien web |
| `GET` | `/api/state` | Lay trang thai ring hien tai |
| `GET` | `/api/resources` | Lay danh sach resource |
| `POST` | `/api/initialize` | Khoi tao lai ring |

### Node

| Method | Endpoint | Mo ta |
| --- | --- | --- |
| `GET` | `/api/node/<node_id>` | Chi tiet node, finger table va local resources |
| `POST` | `/api/node` | Them node moi |
| `DELETE` | `/api/node/<node_id>` | Xoa node khoi ring |
| `POST` | `/api/kill` | Danh dau node failed va tra ve impact |
| `POST` | `/api/recover` | Recover node failed |

### Resource

| Method | Endpoint | Mo ta |
| --- | --- | --- |
| `POST` | `/api/resource` | Them resource |
| `PUT` | `/api/resource` | Doi resource ID |
| `DELETE` | `/api/resource` | Xoa resource |
| `POST` | `/api/lookup` | Lookup resource va tra ve trace |

### Metrics va topology

| Method | Endpoint | Mo ta |
| --- | --- | --- |
| `GET` | `/api/metrics` | Tra 405 de tranh chay benchmark bang GET |
| `POST` | `/api/metrics` | Chay benchmark metrics |
| `GET` | `/api/metrics/last` | Lay metrics gan nhat |
| `POST` | `/api/topology` | Sinh topology graph |

## Vi Du Goi API

Khoi tao ring:

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

## Du Lieu Luu Tru

| File | Mo ta |
| --- | --- |
| `data/state.json` | Snapshot day du cua ring, nodes, resources, failed nodes va metrics gan nhat |
| `data/node_ids.json` | Danh sach node ID sinh ra khi initialize |
| `data/resource_ids.json` | Danh sach resource ID/hash/key sinh ra khi initialize |

Khi autoload state, neu khong co failed node dang pending recovery, he thong chay protocol de hoi tu lai routing/finger table tu snapshot da luu.

## Metrics

Metrics dung de quan sat hanh vi lookup:

| Metric | Y nghia |
| --- | --- |
| `average_hops` | So hop trung binh |
| `max_hops` | So hop lon nhat |
| `average_latency_ms` | Latency mo phong |
| `message_overhead` | Tong message suy ra tu lookup |
| `messages_per_lookup` | Message trung binh tren moi lookup |
| `success_rate` | Ty le lookup thanh cong |

Ve ly thuyet, Chord lookup ky vong khoang `O(log N)`, nen bieu do average hops duoc so voi `log2(N)`.

## Kiem Thu

Chay toan bo test:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Chay file test chinh:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_distributed_chord.py -v
```

Luu y: neu moi truong thieu `matplotlib`, pytest se loi o buoc import `chord_dht.metrics`. Cai dependency bang `python -m pip install -e ".[dev]"` hoac `python -m pip install -r requirements.txt`.

Nhom test chinh:

- Hash ID nam dung trong khong gian `2^m`.
- Interval xu ly dung wraparound.
- Initialize ghi state dung.
- Lookup tra ve owner/path/log.
- Node join rebalance dung khoang key.
- Kill/Recover sua ring, finger table va resource placement.
- Finger table dung cong thuc `successor(start)`.
- Resource owner dung cong thuc `successor(key)`.

## Luong Demo Goi Y

1. Initialize mang voi 50 node, 1000 resource, `m = 16`, `seed = 61`.
2. Mo mot node de giai thich predecessor, successor va finger table.
3. Lookup `resource-0010`, chi path, hops va log.
4. Them node moi, giai thich chi mot khoang key bi rebalance.
5. Kill mot node, chi impact report: primary affected, replica affected, stale fingers.
6. Bam Recover, giai thich va ring, sua finger, promote tu replica va dat lai replica.
7. Chay metrics de so average hops voi `log2(N)`.

## Thuat Ngu

| Thuat ngu | Giai thich |
| --- | --- |
| Node | Peer trong mang Chord |
| Ring | Vong dinh danh kich thuoc `2^m` |
| Key | ID hash cua resource |
| Owner | Node chiu trach nhiem chinh cho resource |
| Successor | Node active dau tien sau mot ID theo chieu kim dong ho |
| Predecessor | Node active dung truoc mot node |
| Finger table | Bang dinh tuyen gom cac moc nhay luy thua cua 2 |
| Lookup path | Cac node ma truy van di qua |
| Replica | Ban sao resource tren successor node |
| Stabilization | Qua trinh cap nhat successor, predecessor va finger table |
| Failed node | Node inactive do Kill va dang cho/da recovery |
| Retired node | Node da bi loai khoi routing sau recovery |

