# ADR 0006 — Gradient Boosting bằng `HistGradientBoostingClassifier` của scikit-learn

- **Trạng thái:** Accepted (đề xuất của agent, chủ dự án uỷ quyền "tự động theo đề xuất" trong chat ngày 2026-11-04)
- **Phạm vi:** mô hình Stage E của Product 02 (`fraud_risk/models/gbm.py`)

## Bối cảnh

Kế hoạch có Gradient Boosting ở Stage E (tổng quan, tài liệu 8: Grinsztajn và cộng sự, 2022, cho thấy mô hình cây vẫn mạnh trên dữ liệu bảng). Quy tắc 11: không thêm thư viện khi chưa ghi lý do.

| Phương án | Ưu điểm | Nhược điểm |
| --- | --- | --- |
| **A. `HistGradientBoostingClassifier` (scikit-learn)** | Đã có trong dự án; cùng API `Pipeline` như baseline; tự xử lý giá trị thiếu và biến phân loại; có `class_weight` | Ít tuỳ chọn hơn LightGBM; tốc độ chậm hơn một chút |
| B. LightGBM | Nhanh, phổ biến trong cuộc thi IEEE-CIS | Thêm thư viện có phần biên dịch; dễ bị so với các notebook công khai (quy tắc 13) |
| C. XGBoost | Phổ biến, nhiều tài liệu | Thêm thư viện; nhiều tham số hơn mức cần cho demo |

## Quyết định

Chọn **A**.

- Tắt `early_stopping`, vì phần validation nội bộ của nó chia ngẫu nhiên (trái quy tắc 7). Số vòng (`max_iter`) nằm trong lưới chọn trên validation.
- Biến phân loại được mã hoá thứ tự bằng `OrdinalEncoder` fit trên train; giá trị chưa gặp thành giá trị thiếu.

## Hệ quả

- Không thêm thư viện.
- Nếu cần mô hình mạnh hơn, chuyển sang LightGBM là một ADR mới; code đánh giá và run log dùng lại được.
