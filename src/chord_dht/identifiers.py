from __future__ import annotations

import hashlib

# Băm định danh vào không gian m bit
def hash_identifier(value: str | int, m: int = 16) -> int:

    # Kiểm tra số bit định danh nằm trong miền SHA-1 hỗ trợ
    if not 1 <= m <= 160:
        raise ValueError("m must be between 1 and 160")

    # Chuẩn hóa giá trị đầu vào thành bytes UTF-8
    text = str(value).encode("utf-8")

    # Tính digest SHA-1 dạng hex cho định danh
    digest = hashlib.sha1(text).hexdigest()

    # Co digest về không gian định danh m bit
    return int(digest, 16) % (2**m)

# Băm mã tài nguyên thành digest và key
def hash_resource(resource_id: str, m: int = 16) -> tuple[str, int]:
    # Kiểm tra số bit định danh nằm trong miền SHA-1 hỗ trợ
    if not 1 <= m <= 160:
        raise ValueError("m must be between 1 and 160")
    # Chuẩn hóa resource_id thành bytes UTF-8
    text = str(resource_id).encode("utf-8")
    # Tính digest SHA-1 đầy đủ để hiển thị hashed_resource_id
    digest = hashlib.sha1(text).hexdigest()
    # Co digest về key Chord trong không gian m bit
    key = int(digest, 16) % (2**m)
    # Trả về digest đầy đủ và key dùng để định tuyến
    return digest, key

# Kiểm tra giá trị nằm trong khoảng theo chiều kim đồng hồ
def in_clockwise_interval(
    value: int,
    start: int,
    end: int,
    *,
    include_start: bool = False,
    include_end: bool = True,
) -> bool:

    # Xem khoảng trùng điểm đầu cuối là bao phủ toàn vòng
    if start == end:
        # Trả về True vì mọi giá trị đều thuộc toàn vòng
        return True

    # Kiểm tra biên trái theo tùy chọn include_start
    left_ok = value > start or (include_start and value == start)

    # Kiểm tra biên phải theo tùy chọn include_end
    right_ok = value < end or (include_end and value == end)

    # Kiểm tra khoảng không bị wrap qua điểm 0
    if start < end:
        # Trả về kết quả khi giá trị thỏa cả hai biên
        return left_ok and right_ok

    # Trả về kết quả khi khoảng bị wrap qua điểm 0
    return left_ok or right_ok
