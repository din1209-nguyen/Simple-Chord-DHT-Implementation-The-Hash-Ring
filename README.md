# Simple Chord DHT Implementation

?ng d?ng web m? ph?ng **Chord Distributed Hash Table (DHT)** cho ?? t?i **Topic 61 - Simple Chord DHT Implementation**. D? ?n minh h?a c?ch node v? resource ???c ?nh x? v?o v?ng ??nh danh, c?ch lookup d?ng finger table, c?ch node join/failure ?nh h??ng t?i topology, v? c?ch replication gi?p ph?c h?i d? li?u khi node l?i.

> ??y l? m? ph?ng single-process ph?c v? h?c t?p v? demo. M?i node l? m?t object trong b? nh?, kh?ng ph?i m?t process/m?y ??c l?p trong m?ng P2P th?t.

## Th?ng Tin D? ?n

| M?c | N?i dung |
| --- | --- |
| Ch? ?? | Topic 61 - Simple Chord DHT Implementation |
| M?n h?c | C? S? D? Li?u Ph?n T?n |
| Ng?n ng? | Python, JavaScript, HTML, CSS |
| Backend | Flask |
| Visualization | Matplotlib, NetworkX |
| Ki?u tri?n khai | Single-process Chord simulator |

## T?nh N?ng Ch?nh

- Kh?i t?o Chord ring v?i s? node, s? resource, `m`, `seed` v? `replication_count`.
- Hash node/resource v?o c?ng kh?ng gian ??nh danh `2^m`.
- X?c ??nh owner c?a resource theo quy t?c `successor(resource_key)`.
- Hi?n th? `successor`, `predecessor`, finger table v? local resource c?a t?ng node.
- Lookup resource b?ng Chord routing v? `closest preceding finger`.
- Th?m node m?i v? rebalance ??ng kho?ng key b? ?nh h??ng.
- Kill node ?? m? ph?ng failure, hi?n th? impact tr??c recovery.
- Recover node failure b?ng c?ch s?a ring, s?a finger table, promote primary t? replica s?ng v? ??t l?i replica.
- Hi?n th? topology, lookup path, resource distribution v? metrics.
- L?u tr?ng th?i ring v?o `data/state.json` ?? autoload sau khi restart server.

## L? Thuy?t Chord ???c M? Ph?ng

### V?ng ??nh danh

Chord d?ng kh?ng gian ??nh danh d?ng v?ng:

```text
identifier_space = 2^m
```

V?i c?u h?nh th??ng d?ng `m = 16`, ID n?m trong kho?ng:

```text
0 -> 65535
```

Node ID v? resource key ???c sinh b?ng SHA-1 r?i r?t g?n v?o kh?ng gian `2^m`:

```text
node_id      = SHA1(...) mod 2^m
resource_key = SHA1(resource_id) mod 2^m
```

### Seed

`seed` gi?p k?t qu? random c? th? t?i l?p. N?u d?ng c?ng m?t seed, danh s?ch node ID/resource ID sinh ra s? gi?ng nhau gi?a c?c l?n ch?y. ?i?u n?y gi?p demo v? debug ?n ??nh, v? d? l?i ? node `18652` c? th? t?i hi?n l?i ch?nh x?c.

### Owner C?a Resource

Resource ???c l?u ch?nh t?i node `successor(resource_key)`:

```text
owner(resource) = successor(resource_key)
```

`successor(key)` l? node active ??u ti?n theo chi?u kim ??ng h? c? ID l?n h?n ho?c b?ng key. N?u kh?ng c? node n?o l?n h?n key, k?t qu? quay v?ng v? node nh? nh?t.

V? d?:

```text
active nodes = [18652, 19570, 24076, 30016, 37252]
resource_key = 26844
owner = 30016
```

### Kho?ng S? H?u C?a Node

M?t node `n` s? h?u c?c key n?m trong kho?ng:

```text
(predecessor(n), n]
```

V? d? node `3265` c? predecessor l? `60689`, th? kho?ng s? h?u l?:

```text
(60689, 3265]
```

Kho?ng n?y wrap qua 0, n?n key `1202` thu?c v? node `3265`.

### Finger Table

M?i node c? `m` d?ng finger table. V?i node `n`, d?ng th? `i` ???c t?nh:

```text
start_i = (n + 2^(i - 1)) mod 2^m
end_i   = (n + 2^i) mod 2^m
node_i  = successor(start_i)
```

Finger table kh?ng ch?n node ng?u nhi?n. M?i d?ng ??i di?n cho m?t b??c nh?y theo l?y th?a c?a 2, gi?p lookup ?i nhanh h?n thay v? duy?t t?ng successor.

V? d? v?i node `18652`, `m = 16`:

```text
finger #14:
start = 18652 + 2^13 = 26844
node  = successor(26844)
```

N?u node active ??u ti?n sau `26844` l? `30016`, th? finger #14 ph?i tr? t?i `30016`.

### Lookup

Lookup d?ng finger table ?? ??nh tuy?n t?i owner:

```text
1. B?t ??u t? m?t node active.
2. N?u key thu?c (predecessor(current), current], current l? owner.
3. N?u key thu?c (current, successor], successor l? owner.
4. N?u ch?a t?i owner, ch?n closest preceding finger g?n key nh?t.
5. L?p l?i cho t?i khi t?m ???c owner.
```

?i?m quan tr?ng:

- `closest_preceding_finger` d?ng cho qu? tr?nh lookup/routing.
- Finger table ???c t?nh b?ng `successor(start)`.
- Verify finger table c?ng so v?i `successor(start)`, kh?ng d?ng route ?? tr?nh che l?i khi b?ng ?ang stale.

## Replication

M?i resource c?:

```text
owner_id
replica_node_ids
```

Owner l? node ch?nh. Replica ???c ??t tr?n c?c successor k? ti?p c?a owner, kh?ng tr?ng owner.

V? d?:

```text
owner = 30016
successor chain = 30016 -> 37252 -> 51502
replication_count = 2
replica_node_ids = [37252, 51502]
```

N?u `replication_count` l?n h?n s? node c? th? ??t replica, h? th?ng d?ng `effective_replica_count`:

```text
effective_replica_count = min(replication_count, active_nodes - 1)
```

## Node Join

Khi th?m node m?i:

```text
1. Node m?i ???c g?n node_id.
2. Node ???c ch?n v?o ??ng v? tr? tr?n v?ng.
3. Successor/predecessor ???c stabilize l?i.
4. Finger table ch?y protocol t?i khi stable.
5. Resource thu?c kho?ng (predecessor(new_node), new_node] chuy?n sang node m?i.
6. Replica placement ???c t?nh l?i.
```

? ngh?a l? thuy?t: nh? consistent hashing, node join kh?ng l?m ph?n ph?i l?i to?n b? d? li?u, ch? c?c key trong kho?ng node m?i ch?u tr?ch nhi?m b? ?nh h??ng.

## Node Failure V? Recovery

Flow failure trong d? ?n ???c t?ch th?nh hai b??c ?? d? demo.

### 1. Kill Node

Khi b?m **Kill**, node ???c ??nh d?u inactive v? th?m v?o `failed_nodes`. H? th?ng ch?a ph?c h?i ngay, m? hi?n th? impact:

- Failed node.
- Old predecessor v? old successor.
- C?c finger entry ?ang tr? t?i failed node.
- Primary resource do failed node l?m owner.
- Replica resource ?ang ??t tr?n failed node.

Node failed kh?ng c?n ???c xem l? ngu?n d? li?u tin c?y.

### 2. Recover

Khi b?m **Recover**, h? th?ng th?c hi?n:

```text
1. X?c nh?n node failed.
2. N?i old predecessor v?i old successor ?? v? ring.
3. S?a finger table ?ang tr? t?i node ch?t b?ng successor(entry.start).
4. V?i primary resource b? ?nh h??ng, promote t? replica c?n s?ng.
5. V?i replica resource b? ?nh h??ng, lo?i replica ch?t v? ??t replica m?i.
6. D?n metadata resource b? m?t n?u kh?ng c?n b?n copy active.
```

N?u primary resource kh?ng c?n replica s?ng, resource ???c xem l? lost.

## Protocol Tick V? Stabilization

D? ?n c? hai h?m ch?nh ?? m? ph?ng protocol Chord:

```text
run_protocol_tick()
run_protocol_until_stable()
```

M?t tick th?c hi?n tr?n to?n b? node active:

```text
1. stabilize_one(node)
2. check_predecessor_one(node)
3. fix_fingers_one(node)
```

M?i tick ch? s?a m?t d?ng finger table tr?n m?i node. V? finger table c? `m` d?ng, `run_protocol_until_stable()` ch?y t?i thi?u `m` tick ?? qu?t ?? m?t v?ng finger table, r?i d?ng khi routing snapshot kh?ng c?n thay ??i.

## Ki?n Tr?c

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

| Th?nh ph?n | Vai tr? |
| --- | --- |
| `app.py` | Flask server, API, persist state, ?i?u ph?i metrics/topology |
| `src/chord_dht/chord.py` | L?p `ChordRing`, core Chord logic, lookup, join, recovery, replication |
| `src/chord_dht/models.py` | `Node`, `FingerEntry`, `ResourceRecord`, `LookupResult` |
| `src/chord_dht/identifiers.py` | Hash ID v? ki?m tra interval tr?n v?ng Chord |
| `src/chord_dht/metrics.py` | Benchmark lookup v? d? li?u metrics |
| `src/chord_dht/visualization.py` | Sinh topology graph |
| `templates/index.html` | Giao di?n ch?nh |
| `static/app.js` | Logic frontend v? render UI |
| `tests/test_distributed_chord.py` | Test API v? logic Chord |

## C?u Tr?c Th? M?c

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

## C?i ??t

Y?u c?u:

- Python 3.10 tr? l?n
- pip
- Windows PowerShell ho?c terminal t??ng ???ng

C?i b?ng virtual environment:

```powershell
py -3.10 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Ho?c c?i t? `requirements.txt`:

```powershell
python -m pip install -r requirements.txt
```

## Ch?y ?ng D?ng

```powershell
.\.venv\Scripts\python.exe app.py
```

M?c ??nh server ch?y t?i:

```text
http://127.0.0.1:5000
```

C? th? ??i host/port:

```powershell
$env:HOST = "0.0.0.0"
$env:PORT = "8080"
.\.venv\Scripts\python.exe app.py
```

## API Ch?nh

### State V? Resource

| Method | Endpoint | M? t? |
| --- | --- | --- |
| `GET` | `/` | Giao di?n web |
| `GET` | `/api/state` | L?y tr?ng th?i ring hi?n t?i |
| `GET` | `/api/resources` | L?y danh s?ch resource |
| `POST` | `/api/initialize` | Kh?i t?o l?i ring |

### Node

| Method | Endpoint | M? t? |
| --- | --- | --- |
| `GET` | `/api/node/<node_id>` | Chi ti?t node, finger table v? local resources |
| `POST` | `/api/node` | Th?m node m?i |
| `DELETE` | `/api/node/<node_id>` | X?a node kh?i ring |
| `POST` | `/api/kill` | ??nh d?u node failed v? tr? v? impact |
| `POST` | `/api/recover` | Recover node failed |

### Resource

| Method | Endpoint | M? t? |
| --- | --- | --- |
| `POST` | `/api/resource` | Th?m resource |
| `PUT` | `/api/resource` | ??i resource ID |
| `DELETE` | `/api/resource` | X?a resource |
| `POST` | `/api/lookup` | Lookup resource v? tr? v? trace |

### Metrics V? Topology

| Method | Endpoint | M? t? |
| --- | --- | --- |
| `GET` | `/api/metrics` | Tr? 405 ?? tr?nh ch?y benchmark b?ng GET |
| `POST` | `/api/metrics` | Ch?y benchmark metrics |
| `GET` | `/api/metrics/last` | L?y metrics g?n nh?t |
| `POST` | `/api/topology` | Sinh topology graph |

## V? D? G?i API

Kh?i t?o ring:

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

## D? Li?u L?u Tr?

| File | M? t? |
| --- | --- |
| `data/state.json` | Snapshot ??y ?? c?a ring, nodes, resources, failed nodes v? metrics g?n nh?t |
| `data/node_ids.json` | Danh s?ch node ID sinh ra khi initialize |
| `data/resource_ids.json` | Danh s?ch resource ID/hash/key sinh ra khi initialize |

Khi autoload state, n?u kh?ng c? failed node ?ang pending recovery, h? th?ng ch?y protocol ?? h?i t? l?i routing/finger table t? snapshot ?? l?u.

## Metrics

Metrics d?ng ?? quan s?t h?nh vi lookup:

| Metric | ? ngh?a |
| --- | --- |
| `average_hops` | S? hop trung b?nh |
| `max_hops` | S? hop l?n nh?t |
| `average_latency_ms` | Latency m? ph?ng |
| `message_overhead` | T?ng message suy ra t? lookup |
| `messages_per_lookup` | Message trung b?nh tr?n m?i lookup |
| `success_rate` | T? l? lookup th?nh c?ng |

V? l? thuy?t, Chord lookup k? v?ng kho?ng `O(log N)`, n?n bi?u ?? average hops ???c so v?i `log2(N)`.

## Ki?m Th?

Ch?y to?n b? test:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Ch?y file test ch?nh:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_distributed_chord.py -v
```

L?u ?: n?u m?i tr??ng thi?u `matplotlib`, pytest s? l?i ? b??c import `chord_dht.metrics`. C?i dependency b?ng `python -m pip install -e ".[dev]"` ho?c `python -m pip install -r requirements.txt`.

Nh?m test ch?nh:

- Hash ID n?m ??ng trong kh?ng gian `2^m`.
- Interval x? l? ??ng wraparound.
- Initialize ghi state ??ng.
- Lookup tr? v? owner/path/log.
- Node join rebalance ??ng kho?ng key.
- Kill/Recover s?a ring, finger table v? resource placement.
- Finger table ??ng c?ng th?c `successor(start)`.
- Resource owner ??ng c?ng th?c `successor(key)`.

## Lu?ng Demo G?i ?

1. Initialize m?ng v?i 50 node, 1000 resource, `m = 16`, `seed = 61`.
2. M? m?t node ?? gi?i th?ch predecessor, successor v? finger table.
3. Lookup `resource-0010`, ch? path, hops v? log.
4. Th?m node m?i, gi?i th?ch ch? m?t kho?ng key b? rebalance.
5. Kill m?t node, ch? impact report: primary affected, replica affected, stale fingers.
6. B?m Recover, gi?i th?ch v? ring, s?a finger, promote t? replica v? ??t l?i replica.
7. Ch?y metrics ?? so average hops v?i `log2(N)`.

## Thu?t Ng?

| Thu?t ng? | Gi?i th?ch |
| --- | --- |
| Node | Peer trong m?ng Chord |
| Ring | V?ng ??nh danh k?ch th??c `2^m` |
| Key | ID hash c?a resource |
| Owner | Node ch?u tr?ch nhi?m ch?nh cho resource |
| Successor | Node active ??u ti?n sau m?t ID theo chi?u kim ??ng h? |
| Predecessor | Node active ??ng tr??c m?t node |
| Finger table | B?ng ??nh tuy?n g?m c?c m?c nh?y l?y th?a c?a 2 |
| Lookup path | C?c node m? truy v?n ?i qua |
| Replica | B?n sao resource tr?n successor node |
| Stabilization | Qu? tr?nh c?p nh?t successor, predecessor v? finger table |
| Failed node | Node inactive do Kill v? ?ang ch?/?? recovery |
| Retired node | Node ?? b? lo?i kh?i routing sau recovery |
