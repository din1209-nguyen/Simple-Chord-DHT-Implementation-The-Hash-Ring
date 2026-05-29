# Simple Chord DHT Implementation: The Hash Ring (Single-process)

Dự án triển khai Chord DHT theo chế độ mô phỏng **single-process** cho Topic 61.
Tất cả node được mô phỏng trong **một** Flask process (một port), lưu trạng thái vào
`data/state.json`.

## Kiến Trúc

```text
Browser UI
   |
   v
app.py (Flask :5000)
   |
   v
InMemoryChordSimulator (shared memory) -> data/state.json
```

## Quy Tắc Chord

```text
node_id = SHA1("node-<seed>-<k>") mod 2^m
key     = SHA1(resource_id) mod 2^m
owner   = successor(key)

start_i = (n + 2^(i-1)) mod 2^m
finger_i = successor(start_i)
```

## Cài Đặt Và Chạy

```powershell
py -3.10 -m venv .venv
.\.venv\Scripts\activate
python -m pip install -e .
python app.py
```

Mở `http://127.0.0.1:5000/`.

## Kiểm Thử

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```
