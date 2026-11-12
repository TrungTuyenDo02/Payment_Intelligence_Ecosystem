# ADR 0002 — Hai sản phẩm độc lập về dữ liệu, chỉ chung nền tảng

- **Trạng thái:** Accepted (chủ dự án chọn hướng "hai sản phẩm độc lập" trong chat ngày 2026-11-03 và chấp nhận văn bản này trong chat ngày 2026-11-12).
- **Phạm vi:** Product 01 (Payment Reliability), Product 02 (Fraud & Risk), `contracts/`, Stage C–F

## Bối cảnh

- Contract `payment-event` có các trường vận hành: `provider_id`, `merchant_id`, `latency_ms`, `error_code`, `status`.
- IEEE-CIS (dữ liệu của Product 02) không có các trường này. Adapter không được bịa trường (`AGENTS.md`, mục 8).
- Không có dataset công khai nào chứa đồng thời dữ liệu vận hành thanh toán và nhãn gian lận với chung khoá giao dịch.
- Vì vậy Product 01 sẽ chạy trên dữ liệu giả lập (Stage C), còn Product 02 chạy trên IEEE-CIS. Hai bên không có dữ liệu chung.

Trong một hệ thống thật, hai sản phẩm sẽ dùng chung một nguồn sự kiện và chung khoá (`payment_id`) ngay từ đầu. Đây là giới hạn do **nguồn dữ liệu của demo**, không phải lựa chọn kiến trúc.

| Phương án | Ưu điểm | Nhược điểm |
| --- | --- | --- |
| **A. Hai sản phẩm độc lập về dữ liệu, chỉ chung nền tảng** | Trung thực, rẻ, dễ giải thích | Demo không có luồng dữ liệu xuyên suốt hai sản phẩm |
| B. Bộ sinh dữ liệu sinh thêm nhãn gian lận, Product 02 chạy thêm trên dữ liệu giả lập | Có luồng end-to-end | Đánh giá Product 02 trở thành vòng tròn (mô hình học lại luật sinh nhãn); cần schema `risk-context`, đang ngoài phạm vi |
| C. Ánh xạ IEEE-CIS sang `payment-event` | — | Thiếu trường bắt buộc, vi phạm quy tắc không bịa trường |

## Quyết định

Chọn **A**.

- "Hệ sinh thái" nghĩa là **chung nền tảng**: quy ước contract, quản lý dataset (manifest, checksum), quy tắc đánh giá (split theo thời gian, test-once, run log), hạ tầng (Docker, PostgreSQL) và tooling. **Không** chung dữ liệu.
- Product 01 dùng dữ liệu giả lập theo `payment-event`. Product 02 dùng IEEE-CIS. Không so sánh hay kết hợp kết quả giữa hai sản phẩm.
- `contracts/risk-context/` tiếp tục chỉ có README. Nếu sau này có nguồn dữ liệu chung, việc thiết kế schema này cần một ADR mới.
- Stage F trình bày hai sản phẩm như hai ứng dụng song song trên cùng nền tảng, không dựng một luồng tích hợp giả.

## Hệ quả

- Báo cáo phải có một đoạn trong phần "Hạn chế": trong hệ thống thật, dữ liệu của hai sản phẩm dùng chung khoá `payment_id` từ nguồn sự kiện; demo không làm được vì không có dataset công khai phù hợp.
- Contract `payment-event` vẫn giữ `payment_id` và `attempt_id`, để sau này có thể nối thêm dữ liệu rủi ro mà không phải đổi contract.
- Mục "Kết nối hai sản phẩm" trong `docs/product/project-overview.md` được thay bằng mô tả theo ADR này.
- Cách trình bày từ Stage G: **một nền tảng, hai pipeline song song**: `make demo` (Product 01) và `make score-model` / `make score` (Product 02) chạy riêng, không nối dữ liệu.
- Nếu sau này muốn một demo tích hợp kỹ thuật (API chấm điểm nhận sự kiện giả lập), phải có ADR riêng và ghi rõ đó không phải bằng chứng hiệu năng.
