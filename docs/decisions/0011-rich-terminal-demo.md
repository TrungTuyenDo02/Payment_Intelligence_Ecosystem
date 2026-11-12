# ADR 0011 — Giao diện terminal của `make demo` dùng thư viện `rich`

- **Trạng thái:** Accepted (chủ dự án chọn "dùng rich + ADR 0011" trong chat ngày 2026-11-12)
- **Phạm vi:** `scripts/demo.py`, nhóm phụ thuộc `dev` trong `pyproject.toml`

## Bối cảnh

`make demo` là thứ mentor và giám khảo nhìn đầu tiên. Bản tự viết bằng `print` (thanh tiến độ bằng ký tự, bảng căn cột thủ công) chạy đúng, nhưng chủ dự án đánh giá "chưa đẹp mắt": bảng lệch khi tên dài, không có màu để phân biệt đạt/không đạt, thanh tiến độ chỉ nhảy sau mỗi bước.

Quy tắc 9: thêm thư viện phải có ADR.

| Phương án | Ưu điểm | Nhược điểm |
| --- | --- | --- |
| **A. `rich`** | Thư viện phổ biến nhất cho giao diện terminal Python: bảng có khung tự căn cột, thanh tiến độ động có thời gian, panel, màu; tự tắt màu khi không phải terminal hoặc khi đặt `NO_COLOR`; chạy được trên Windows Terminal, PowerShell, VS Code, CI | Thêm một phụ thuộc (thuần Python, kéo theo `markdown-it-py`, `pygments`) |
| B. Tự viết bằng mã ANSI | Không thêm thư viện | Tự lo căn cột theo độ rộng ký tự Unicode, phát hiện terminal, tắt màu; nhiều code hơn mà kém hơn |
| C. Giữ nguyên | Không tốn gì | Không đáp ứng yêu cầu |

## Quyết định

Chọn **A**, với giới hạn:

- `rich` nằm trong nhóm **`dev`** của `pyproject.toml` (như `matplotlib`), không nằm trong phụ thuộc chính. Chỉ `scripts/demo.py` dùng nó; mã của hai sản phẩm (`fraud_risk`, `payment_reliability`, `synthetic_generator`, `dashboard`) không import `rich`.
- Phiên bản do `uv.lock` khoá, như mọi phụ thuộc khác.
- Logic của demo (chạy bước, đọc kết quả, danh sách kiểm tra) tách khỏi phần hiển thị, để test không phụ thuộc định dạng terminal.

## Hệ quả

- `make setup` (hoặc `uv sync`) cài thêm `rich`. CI cài nhóm `dev` sẵn nên job `demo` chạy được.
- Khi đầu ra bị chuyển hướng (CI, `> file.txt`), `rich` tự in dạng không màu.
- Không đổi kết quả hay mã lần chạy nào: `rich` chỉ ảnh hưởng cách in.
