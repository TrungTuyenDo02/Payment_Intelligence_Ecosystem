# ADR 0005 — Tầng KPI bằng SQL views thuần, không dùng dbt

- **Trạng thái:** Accepted (chủ dự án chọn trong chat ngày 2026-11-04)
- **Phạm vi:** tầng mô hình dữ liệu và KPI của Product 01 ở Stage D

## Bối cảnh

Stage D cần tính KPI độ tin cậy (tỷ lệ thành công, tỷ lệ retry, độ trễ p50/p95, lỗi theo provider và mã lỗi) từ bảng `payment_events` trong PostgreSQL. Kế hoạch 6 tuần ghi hai lựa chọn: dbt, hoặc phương án dự phòng là SQL views. Stage D chỉ có một tuần.

| Phương án | Ưu điểm | Nhược điểm |
| --- | --- | --- |
| **A. SQL views thuần** trong `infrastructure/database/` | Không thêm thư viện; chạy bằng `make db-init` như schema hiện có; mỗi KPI là một câu SQL đọc được trực tiếp; test bằng pytest như phần còn lại của repo | Không có sẵn tài liệu model, kiểm tra lineage hay test khai báo kiểu dbt; phải tự giữ thứ tự tạo view |
| B. `dbt-postgres` | Chuẩn công nghiệp; có test khai báo (`unique`, `not_null`), tài liệu và đồ thị phụ thuộc tự sinh | Thêm thư viện, thư mục project và `profiles.yml`; nhiều khái niệm mới phải học và giải thích trong tuần 4; với 3–4 view thì lợi ích nhỏ |

## Quyết định

Chọn **A**.

- Các view nằm trong `infrastructure/database/002_kpi_views.sql`, dùng `CREATE OR REPLACE VIEW` để chạy lại an toàn. `make db-init` chạy các file theo thứ tự số.
- Tên view có tiền tố `kpi_`. Mỗi view có chú thích ngắn: hạt (grain) của một dòng và định nghĩa từng cột.
- Kiểm tra số liệu: test tích hợp so sánh kết quả của view với cách tính độc lập bằng Python trên cùng một mô phỏng nhỏ. Test tự bỏ qua kèm lý do khi không có PostgreSQL, như ở Stage C.

## Hệ quả

- Không thêm thư viện nào cho Stage D.
- Nếu sau này số view tăng nhiều hoặc cần tài liệu tự sinh, có thể chuyển sang dbt. Các câu SQL dùng lại được gần như nguyên vẹn làm model dbt. Việc chuyển sẽ cần ADR riêng.
- Báo cáo thực tập nên ghi rõ đây là lựa chọn có chủ đích vì quy mô nhỏ, không phải vì không biết dbt.
