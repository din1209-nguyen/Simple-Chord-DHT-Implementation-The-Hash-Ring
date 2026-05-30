# Import socket để tạo server giả chiếm cổng
import socket


# Chiếm một cổng TCP để mô phỏng port đã bị dùng
def occupy_port(port: int, host: str = "127.0.0.1") -> socket.socket:
    # Tạo socket TCP
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    # Bật reuse address để tránh kẹt TIME_WAIT khi test
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    # Bind socket vào host và port yêu cầu
    sock.bind((host, port))

    # Bắt đầu lắng nghe với backlog tối thiểu
    sock.listen(1)

    # Trả về socket để caller tự đóng
    return sock
