# ADR 0003 — Độ trễ nhãn và thực thể lặp lại giữa các tập (IEEE-CIS)

- **Trạng thái:** Proposed. Chờ chủ dự án quyết định. Đề xuất này có liên quan đến quy tắc split nên cần duyệt trước khi làm.
- **Phạm vi:** `fraud_risk/evaluation/split.py`, báo cáo đánh giá Product 02, Stage E

## Bối cảnh

1. **Cách gán nhãn.** Theo mô tả của ban tổ chức trên diễn đàn cuộc thi Kaggle, giao dịch có chargeback được gán `isFraud = 1`. Các giao dịch **sau đó** liên kết với cùng tài khoản người dùng, email hoặc địa chỉ thanh toán cũng bị gán gian lận. Giao dịch không bị báo cáo trong khoảng 120 ngày thì được coi là hợp lệ.
   *Chủ dự án cần tự đọc lại nguồn này trên trang thảo luận của cuộc thi trước khi trích dẫn.*
2. **Hệ quả thứ nhất — độ trễ nhãn.** Trong thực tế, nhãn gian lận chỉ có sau vài tuần (thời gian xử lý chargeback). Trong IEEE-CIS, nhãn đã có sẵn ngay tại thời điểm giao dịch. Split hiện tại (train kết thúc ngay trước validation) giả định mô hình biết nhãn của cả những giao dịch sát thời điểm chấm điểm, nên ước lượng hiệu năng có thể lạc quan.
3. **Hệ quả thứ hai — thực thể lặp lại.** Cùng một thẻ hoặc người dùng có thể xuất hiện ở cả train và test. Mô hình có thể học nhận ra **thực thể** đã gian lận thay vì học **hành vi** gian lận. Chia theo thời gian không ngăn được điều này.
4. Không có chuẩn chung cho việc đánh giá có độ trễ nhãn. Dự án phải tự định nghĩa giao thức và biện minh cho nó.
5. IEEE-CIS dài khoảng 6 tháng. Với split 60/20/20, validation và test mỗi phần dài khoảng 5 tuần. Vì vậy không thể dùng khoảng trống 120 ngày như logic gán nhãn.

## Phương án

| Phương án | Nội dung | Nhược điểm |
| --- | --- | --- |
| A. Không làm gì, chỉ ghi vào phần hạn chế | Rẻ nhất | Không biết mức độ lạc quan của kết quả |
| **B. Đo và phân tích độ nhạy ở Stage E, không đổi split của baseline** | (1) Đo tỷ lệ giao dịch validation/test có định danh thẻ đã xuất hiện trong train. (2) Thêm tham số `gap_days` (mặc định 0) cho split; ở Stage E chạy thêm config có khoảng trống, ví dụ 7 và 14 ngày, rồi báo cáo hiệu năng thay đổi thế nào | Thêm một tham số và một thí nghiệm |
| C. Đổi split của baseline ngay bây giờ | Kết quả baseline "sạch" hơn | Config đã `frozen` sẽ thành config mới; mất so sánh với baseline đã chốt; độ dài khoảng trống chưa có căn cứ |

## Đề xuất

Chọn **B**.

- `gap_days` là một trường trong config. Vì thay đổi mốc split, nó tự động thay đổi `run_id` (D6). Giá trị 7 và 14 ngày là **phân tích độ nhạy**, không phải "giá trị đúng". Báo cáo phải trình bày như vậy.
- Định danh thẻ để đo thực thể lặp lại: bắt đầu với `card1`, sau đó thử một tổ hợp nhiều cột (ví dụ `card1` + `addr1` + `P_emaildomain`). Tổ hợp này là heuristic phổ biến trong các notebook công khai của cuộc thi. Theo quy tắc 13, báo cáo phải ghi rõ nguồn của ý tưởng, và không sao chép code.
- Số đo thực thể lặp lại là **số mô tả**, không dùng để chọn feature hay ngưỡng.
- Các config Stage E có `gap_days > 0` được đưa vào danh sách config đăng ký trước khi chạy test (xem kế hoạch thí nghiệm rò rỉ).

## Câu hỏi cho chủ dự án

- Chủ dự án xác nhận ngày 2026-11-03: `make baseline-final` **chưa chạy**. Vì vậy phương án C vẫn còn mở. Nếu chọn C, phải quyết định trước khi chạy test lần đầu; mọi config Stage E sau đó dùng chung giá trị `gap_days` đã chọn.
- Có chấp nhận thêm `gap_days` vào spec split (`AGENTS.md`, mục 8) không? Đây là thay đổi đối với quy tắc split.

## Hệ quả (nếu chọn B)

- Thêm tham số `gap_days` vào `split.py`, kèm test: không có dòng nào nằm trong khoảng trống, và khoảng trống không bị đưa vào train.
- Thêm bảng "thực thể lặp lại" vào phần đánh giá.
- Báo cáo có mục "Độ trễ nhãn và thực thể lặp lại", trình bày giao thức là **của dự án**, không phải một chuẩn có sẵn.
