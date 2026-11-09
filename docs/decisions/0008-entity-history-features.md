# ADR 0008 — Đặc trưng lịch sử thực thể, chỉ dùng giao dịch trước đó

- **Trạng thái:** Accepted (chủ dự án đồng ý tạo ADR trong chat ngày 2026-11-09)
- **Phạm vi:** `fraud_risk/features/baseline_features.py` (`_history`, `_window_count`, `_aggregate`), các config `gbm-history-*`, `gbm-window-*`, `gbm-agg-*`, `gbm-noC*`, `gbm-wide-grid`; công cụ `fraud_risk/experiments/split_diagnostics.py` và `paired_comparison.py`

## Bối cảnh

AGENTS.md mục 2 xếp "advanced feature engineering" ngoài phạm vi Stage A/B. Sau Stage E còn hai câu hỏi mở trong báo cáo (vì sao chia ngẫu nhiên cho PR-AUC thấp hơn; vì sao đặc trưng lịch sử thực thể không giúp). Trả lời chúng cần thêm đặc trưng theo thực thể và công cụ so sánh hai mô hình, nên phải ghi lại quyết định mở rộng phạm vi này.

Các giải pháp công khai của cuộc thi IEEE-CIS dựng khoá khách hàng (`card1`, `addr1`, `D1n`) và gộp thống kê theo khoá trên **toàn bộ** dữ liệu (theo bài viết thứ cấp, chưa xác minh). Cách đó dùng cả giao dịch tương lai và tập đánh giá.

| Phương án | Ưu điểm | Nhược điểm |
| --- | --- | --- |
| **A. Đặc trưng chỉ nhìn giao dịch trước đó của thực thể** | Đúng với hệ thống thật; không vi phạm quy tắc 8 (fit trên train); kiểm thử được bằng "đổi giao dịch sau không đổi đặc trưng trước" | Thông tin ít hơn ở đầu lịch sử mỗi thực thể |
| B. Gộp trên toàn bộ dữ liệu như bài viết công khai | Gần với điểm số cuộc thi | Nhìn thấy tương lai và tập đánh giá; không dùng được khi chấm điểm thật |
| C. Không làm | Giữ đúng phạm vi ban đầu | Hai câu hỏi mở không có câu trả lời |

## Quyết định

Chọn **A**.

- Khoá thực thể: `card1`; `card1+addr1+P_emaildomain` (uid); uid + `D1n` (`D1n` = ngày giao dịch trừ `D1`).
- Đặc trưng: đếm tích luỹ, đếm trong 24 giờ và 7 ngày, số tiền chia trung bình trước, số giây từ giao dịch trước, độ lệch chuẩn và z-score số tiền, số giá trị `ProductCD` và `C13` khác nhau đã gặp. Không dùng nhãn.
- Giao dịch cùng giây chỉ thấy giao dịch đứng trước trong file.
- Mọi config dùng các đặc trưng này là `draft` và **chỉ chạy trên validation**. Mở tập test cho chúng cần quyết định riêng của chủ dự án và phải ghi trong báo cáo.
- So sánh hai mô hình dùng bootstrap cặp trên cùng dòng validation, báo cả lấy mẫu theo dòng và theo cụm `card1`; kết luận dựa trên bản theo cụm.
- `split_diagnostics.py` được dùng `random_split` (thêm vào danh sách được phép của test chống rò rỉ), chỉ trên 80% dòng đầu (train + validation), không chạm test.

## Hệ quả

- Không thêm thư viện.
- Kết quả (báo cáo Stage E mục 2b, 3b; báo cáo thực tập mục 4.5): không biến thể nào cải thiện đo được so với `gbm.yaml` khi lấy mẫu theo cụm; khoá có `D1n` chỉ có recall tại FPR 5% loại trừ 0, sát 0. Cấu hình đã chốt `run-f8807cb6f780` và kết quả test 0,408 giữ nguyên.
- Muốn dùng một biến thể cho tập test là một ADR hoặc quyết định mới, kèm giai đoạn dữ liệu chưa dùng để chọn biến thể.
