"""Tính toán định danh và kiểm tra khoảng tròn cho Chord DHT"""

from __future__ import annotations

import hashlib


# Băm giá trị đầu vào thành ID hoặc key trong khoảng [0, 2^m)
# Giúp node ID và resource key dùng chung không gian định danh của Chord
def hash_identifier(value: str | int, m: int = 16) -> int:
    if not 1 <= m <= 160:
        raise ValueError("m must be between 1 and 160")

    digest = hashlib.sha1(str(value).encode("utf-8")).hexdigest()
    return int(digest, 16) % (2**m)


# Kiểm tra giá trị có nằm trong khoảng tròn từ start đến end theo chiều kim đồng hồ
# Cho phép bật tắt biên trái và biên phải để dùng lại cho lookup và Finger Table
def in_clockwise_interval(
    value: int,
    start: int,
    end: int,
    *,
    include_start: bool = False,
    include_end: bool = True,
) -> bool:
    if start == end:
        return True

    left_ok = value > start or (include_start and value == start)
    right_ok = value < end or (include_end and value == end)

    if start < end:
        return left_ok and right_ok

    return left_ok or right_ok
