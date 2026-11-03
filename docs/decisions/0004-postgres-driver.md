# ADR 0004 — Dùng psycopg 3 để kết nối PostgreSQL

- **Trạng thái:** Accepted (chủ dự án đồng ý trong chat ngày 2026-11-03)
- **Phạm vi:** ingestion ở Stage C (task C04) và các truy vấn ở Stage D

## Bối cảnh

Stage C cần nạp sự kiện giả lập vào PostgreSQL 16 (đã có trong `compose.yaml`). Danh sách thư viện của Stage A/B không có driver PostgreSQL. Theo quy tắc 11, thêm thư viện phải có lý do được ghi lại.

| Phương án | Ưu điểm | Nhược điểm |
| --- | --- | --- |
| **A. `psycopg[binary]` (psycopg 3)** | Driver chính thức, phổ biến; viết SQL trực tiếp nên dễ giải thích; hỗ trợ `COPY` để nạp nhanh | Phải tự viết SQL |
| B. SQLAlchemy + psycopg | Có ORM, quản lý kết nối | Thêm một tầng trừu tượng; nhiều khái niệm phải giải thích cho mentor |
| C. `pandas.to_sql` | Ít code | Vẫn cần SQLAlchemy; khó kiểm soát khoá chính và cách xử lý bản ghi trùng |

## Quyết định

Chọn **A**: thêm `psycopg[binary]` vào `dependencies` trong `pyproject.toml` ở task C04, không thêm sớm hơn.

- Schema bảng viết bằng SQL thuần trong `infrastructure/database/`.
- Chống trùng bằng khoá chính `event_id` và `INSERT ... ON CONFLICT DO NOTHING`.
- Thông tin kết nối lấy từ biến môi trường (`.env`, không commit), mẫu nằm trong `.env.example`.

## Hệ quả

- Test tích hợp với PostgreSQL phải tự bỏ qua kèm lý do rõ khi database không chạy, để `make test` vẫn pass trên máy không có Docker.
- Nếu Stage D dùng dbt, dbt có adapter riêng (`dbt-postgres`) và cần ADR riêng.
