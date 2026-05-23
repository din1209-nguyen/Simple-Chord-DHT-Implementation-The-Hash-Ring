# Xử lý các phép toán định danh thuần của Chord DHT
# Cung cấp hàm băm node/resource vào vòng m-bit và hàm kiểm tra khoảng tròn

from __future__ import annotations

import hashlib


# Băm giá trị đầu vào thành ID/key nằm trong khoảng [0, 2^m)
# Giúp node ID và resource key cùng dùng chung không gian định danh của Chord
def hash_identifier(value: str | int, m: int = 16) -> int:
    # Kiểm tra số bit định danh để không vượt quá độ dài 160 bit của SHA-1
    if not 1 <= m <= 160:
        raise ValueError("m must be between 1 and 160")

    # Chuyển value sang chuỗi để mọi loại input đều đi qua cùng một quy trình băm
    digest = hashlib.sha1(str(value).encode("utf-8")).hexdigest()

    # Chuyển digest hệ hex sang số nguyên rồi modulo để đưa kết quả vào vòng m-bit
    return int(digest, 16) % (2**m)


# Kiểm tra value có nằm trong khoảng tròn từ start đến end theo chiều kim đồng hồ hay không
# Cho phép bật/tắt biên trái và biên phải để tái sử dụng cho lookup và Finger Table
def in_clockwise_interval(
    value: int,
    start: int,
    end: int,
    *,
    include_start: bool = False,
    include_end: bool = True,
) -> bool:
    # Xử lý trường hợp vòng chỉ còn một node hoặc khoảng phủ toàn bộ vòng
    if start == end:
        return True

    # Kiểm tra khoảng không quấn qua 0, ví dụ (3, 10]
    # So sánh trực tiếp value với hai đầu mút vì thứ tự tuyến tính vẫn giữ nguyên
    if start < end:
        left_ok = value > start or (include_start and value == start)
        right_ok = value < end or (include_end and value == end)
        return left_ok and right_ok

    # Kiểm tra khoảng quấn qua 0, ví dụ (14, 4] trên vòng 16 vị trí
    # Chấp nhận value nếu nó nằm ở đoạn cuối vòng hoặc đoạn đầu vòng
    left_arc = value > start or (include_start and value == start)
    right_arc = value < end or (include_end and value == end)
    return left_arc or right_arc
