from __future__ import annotations

# Import hashlib để băm định danh theo SHA1
import hashlib


# Băm một định danh đầu vào thành key nằm trong không gian định danh m bit
def hash_identifier(value: str | int, m: int = 16) -> int:
    # Kiểm tra số bit m hợp lệ
    if not 1 <= m <= 160:
        raise ValueError("m must be between 1 and 160")

    # Chuẩn hóa value sang chuỗi để băm nhất quán
    text = str(value).encode("utf-8")

    # Tính digest SHA1 dưới dạng hex
    digest = hashlib.sha1(text).hexdigest()

    # Quy đổi digest sang số nguyên và co lại theo không gian m bit
    return int(digest, 16) % (2**m)


# Kiểm tra một giá trị có thuộc khoảng theo chiều kim đồng hồ trên vòng hay không
def in_clockwise_interval(
    value: int,
    start: int,
    end: int,
    *,
    include_start: bool = False,
    include_end: bool = True,
) -> bool:
    # Trả True khi start trùng end vì khoảng bao phủ toàn vòng
    if start == end:
        return True

    # Kiểm tra điều kiện biên trái
    left_ok = value > start or (include_start and value == start)

    # Kiểm tra điều kiện biên phải
    right_ok = value < end or (include_end and value == end)

    # Trả về điều kiện trong trường hợp khoảng không bị wrap
    if start < end:
        return left_ok and right_ok

    # Trả về điều kiện trong trường hợp khoảng bị wrap qua điểm 0
    return left_ok or right_ok
