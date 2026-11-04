# ADR 0007 — Dashboard là một trang HTML tĩnh sinh từ kết quả các lần chạy

- **Trạng thái:** Accepted (đề xuất của agent, chủ dự án uỷ quyền "tự động theo đề xuất" trong chat ngày 2026-11-04)
- **Phạm vi:** Stage F, `shared/dashboard/`

## Bối cảnh

Kế hoạch tuần 6 có "dashboard" và điểm dừng "ADR framework dashboard". Dashboard phải chạy được trên máy cá nhân, giải thích được với mentor, và không phá các quy tắc đã có: không đọc nhãn trong phần vận hành, không chạm tập test.

| Phương án | Ưu điểm | Nhược điểm |
| --- | --- | --- |
| **A. Trang HTML tĩnh** do `make dashboard` sinh ra từ `artifacts/` (matplotlib, không thư viện mới) | Không thêm thư viện; mở bằng trình duyệt, không cần server hay mạng; tái lập được; đính kèm hoặc chụp vào báo cáo PDF được | Không có tương tác (lọc, rê chuột); muốn số mới phải chạy lại lệnh |
| B. Streamlit | Tương tác, viết nhanh bằng Python | Thêm một thư viện lớn và một server; khó đưa vào báo cáo PDF |
| C. Grafana hoặc Metabase trong Docker, đọc view KPI PostgreSQL | Giống hệ thống giám sát thật | Thêm dịch vụ Docker và cấu hình JSON; không có chỗ cho kết quả Product 02 (file JSON); tốn nhiều thời gian nhất trong tuần cuối |

## Quyết định

Chọn **A**.

- Dashboard chỉ đọc kết quả đã có: KPI Parquet, thư mục detector, thư mục run của Product 02 và thí nghiệm rò rỉ. Không đọc dataset, không fit mô hình.
- Thiếu kết quả nào thì phần đó ghi rõ lệnh cần chạy, không báo lỗi.
- Phần "Đối chiếu với sự cố đã cài sẵn" (đọc kết quả đánh giá) được tách riêng và thu gọn, vì người vận hành thật không có nhãn.
- Trang được ghi vào `artifacts/dashboard/index.html` (không commit).

## Hệ quả

- Không thêm thư viện.
- Nếu cần tương tác sau này, có thể chuyển sang B hoặc C mà giữ nguyên nguồn dữ liệu. Việc đó cần ADR mới.
