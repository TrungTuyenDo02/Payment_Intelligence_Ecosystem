# Tổng quan đề tài — Payment Intelligence Ecosystem

> Tài liệu giới thiệu ban đầu cho các team. Nguồn quy định chi tiết và có tính ràng buộc: [`AGENTS.md`](../../AGENTS.md). Nếu hai tài liệu mâu thuẫn, `AGENTS.md` được ưu tiên.

## 1. Đề tài là gì

Một nền tảng dữ liệu và AI dạng module cho lĩnh vực thanh toán, gồm **một nền tảng dùng chung** và **hai sản phẩm độc lập**:

| Thành phần | Mục đích |
| --- | --- |
| **Shared Foundation** | Hợp đồng dữ liệu (data contract), bộ sinh dữ liệu thanh toán giả lập, adapter cho dataset công khai, kiểm tra dữ liệu, hạ tầng chung |
| **Product 01 — Payment Reliability** | Theo dõi độ tin cậy giao dịch: KPI, phát hiện bất thường, quản lý sự cố, API, dashboard |
| **Product 02 — Fraud & Risk** | Phát hiện gian lận: đặc trưng, mô hình, đánh giá, chấm điểm rủi ro, hỗ trợ điều tra |

Bối cảnh: demo 6 tuần cho báo cáo thực tập, có thể phát triển thành đề xuất nội bộ. Chạy cục bộ bằng Docker.

**Tiêu chí ưu tiên:** đánh giá trung thực (không rò rỉ dữ liệu, tái lập được, báo cáo đúng số thật) quan trọng hơn điểm số mô hình. Mọi bước phải giải thích được cho mentor.

## 2. Nguyên tắc không được vi phạm

- **Không dùng dữ liệu thật hay dữ liệu công ty.** Chỉ dùng dataset công khai (IEEE-CIS từ Kaggle) và dữ liệu giả lập. Không có dữ liệu thẻ, thông tin xác thực hay secret trong repo.
- **Chia dữ liệu theo thời gian**, không chia ngẫu nhiên. Tập test chỉ dùng **một lần** cho mỗi cấu hình đã đóng băng (`frozen`).
- **Mọi thứ được "học" (scaler, encoder, imputer, ngưỡng) chỉ fit trên tập train**; ngưỡng quyết định chọn trên validation.
- **Nhãn tách khỏi đặc trưng** — code tạo feature không đọc được cột nhãn.
- **Quyết định tiền xử lý phải có bằng chứng** từ tập train và được chủ dự án duyệt trong `docs/data-analysis/eda-summary.md`.
- **Điểm rủi ro chỉ để hỗ trợ quyết định**, không tự động chặn giao dịch.
- **Không dùng mô hình pretrained** từ Internet (dễ nhiễm dữ liệu test và có rủi ro bảo mật).

## 3. Kế hoạch theo giai đoạn

| Giai đoạn | Nội dung | Trạng thái |
| --- | --- | --- |
| **A — Khung dự án** | Cấu trúc repo, tooling, Docker Compose (PostgreSQL 16), hợp đồng `payment-event` bản nháp, công cụ manifest dataset | Đang làm (T01 xong) |
| **B — Baseline gian lận** | Adapter IEEE-CIS, chia theo thời gian, EDA, metrics, baseline luật + Logistic Regression, run log tái lập | Chưa bắt đầu |
| C | Bộ sinh dữ liệu giả lập và pipeline ingestion | Sau |
| D | dbt marts, KPI, bộ phát hiện bất thường (Product 01) | Sau |
| E | Thí nghiệm rò rỉ dữ liệu, Gradient Boosting, API chấm điểm | Sau |
| F | Dashboard, tích hợp, báo cáo cuối | Sau |

Hiện tại **chỉ làm Giai đoạn A và B**. Các giai đoạn C–F chưa được bắt đầu.

## 4. Việc cần làm (Giai đoạn A/B)

| ID | Việc | Kết quả mong đợi |
| --- | --- | --- |
| T01 | Khung repo và tooling | `make setup lint test` chạy được, Postgres healthy — **xong** |
| T02 | Hợp đồng `payment-event` (draft) | JSON Schema + ví dụ hợp lệ/không hợp lệ + test. **Dừng chờ duyệt** |
| T03 | Công cụ manifest dataset | CLI tính SHA-256, ghi manifest YAML |
| T04 | Adapter IEEE-CIS | Trả về `X`, `y`, `time`; báo lỗi rõ nếu thiếu file |
| T05 | Chia dữ liệu theo thời gian | 60/20/20, không chồng lấn, tất định |
| T05b | Script EDA (6 bước) | Bảng bằng chứng cho tiền xử lý, chỉ trên train. **Dừng chờ duyệt** |
| T06 | Metrics | PR-AUC, precision, recall, F1, FPR, recall@precision, bootstrap CI |
| T07 | Baseline dựa trên luật | Ngưỡng tính từ train, điểm trong [0, 1] |
| T08 | Baseline Logistic Regression | Pipeline fit trên train, ngưỡng chọn trên validation |
| T09 | Run log và CLI | `make baseline` / `make baseline-final` với quy tắc test-một-lần |
| T10 | Test chống rò rỉ dữ liệu | Test fail nếu nhãn lọt vào feature, dùng random split, hoặc fit ngoài train |

Mỗi task một branch, chỉ xong khi `make lint` và `make test` đều pass.

## 5. Định hướng

- **Nền tảng trước, sản phẩm sau.** Hợp đồng dữ liệu và quy tắc đánh giá là nền móng cho mọi giai đoạn sau, nên cần làm sạch và đúng ngay từ đầu.
- **Baseline đơn giản, trung thực** làm mốc so sánh trước khi thử mô hình phức tạp hơn ở Giai đoạn E.
- **Tái lập được:** mọi lần chạy có `run_id` tất định, lưu config, seed, checksum dữ liệu và ranh giới split.
- **Chủ dự án duyệt:** kiến trúc, hợp đồng, quyết định EDA và việc đóng băng config đều do chủ dự án phê duyệt.

## 6. Bắt đầu nhanh

```bash
make setup   # cài môi trường
make lint    # kiểm tra code style
make test    # chạy test
make up      # khởi động PostgreSQL
```

Dataset IEEE-CIS phải được chủ dự án tải thủ công từ Kaggle và đặt vào `datasets/raw/ieee-cis/` (không commit).
