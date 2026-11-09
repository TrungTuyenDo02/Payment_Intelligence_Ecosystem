# Dàn ý báo cáo thực tập

> Dàn ý để chủ dự án viết bản PDF. Mỗi số có run id, mỗi hình có file nguồn, để khi mentor hỏi thì truy lại được.
> Cập nhật: 2026-11-04.

## 1. Giới thiệu (1–2 trang)

- Hai câu hỏi của vận hành thanh toán: hệ thống có chạy ổn không (Product 01); giao dịch có đáng nghi không (Product 02).
- Vì sao hai sản phẩm: một bài toán chuỗi thời gian không nhãn, một bài toán phân loại có nhãn và mất cân bằng; cả hai làm được mà không cần dữ liệu thật.
- Ràng buộc: 6 tuần, chạy trên máy cá nhân, không dữ liệu công ty.
- **Thông điệp chính:** dự án ưu tiên **đánh giá trung thực** hơn điểm cao.
- Hình: `docs/assets/diagrams/system-overview.svg`.

## 2. Phạm vi và cách làm (1–2 trang)

- Trong và ngoài phạm vi: tổng quan đề tài, mục 3.
- Quy tắc đánh giá: chia theo thời gian, fit chỉ trên train, chọn ngưỡng trên validation, test một lần cho mỗi config đã chốt, run id tất định.
- Quy trình: đặc tả, rồi chủ dự án duyệt, rồi code và test, rồi báo cáo. Có ADR 0001–0008.
- Hình: `docs/assets/diagrams/roadmap.svg`, `docs/assets/diagrams/workflow.svg`.

## 3. Nền tảng dùng chung (1 trang)

- Contract `payment-event` 1.0.0: JSON Schema, quy tắc giữa các attempt, không có trường thẻ.
- Manifest dataset với checksum SHA-256.
- PostgreSQL 16, ingestion kiểm tra contract và chống trùng.

## 4. Product 02 — Rủi ro gian lận trên IEEE-CIS

### 4.1 Dữ liệu và EDA

- 590.540 giao dịch; train 354.324, validation 118.108, test 118.108. Tỷ lệ gian lận lần lượt 3,38% / 3,90% / 3,44%. Hình: `docs/assets/results/split.png`.
- 9 quyết định tiền xử lý, mỗi quyết định có bằng chứng từ train: `docs/data-analysis/eda-summary.md`. Ví dụ: skew của `TransactionAmt` 19,44 giảm còn 0,50 sau `log1p`.

### 4.2 Baseline (Stage B), lần chạy `run-d6faa4699008`, config `frozen`

| Mô hình | PR-AUC validation | PR-AUC test [95% CI] | Recall @ FPR 5% (test) |
| --- | --- | --- | --- |
| Luật | 0,089 | 0,078 [0,074; 0,082] | 0,22 |
| Logistic Regression | 0,245 | 0,165 [0,155; 0,176] | 0,28 |

- Logistic Regression trên test cao gấp khoảng 4,8 lần mô hình ngẫu nhiên.
- Kết quả giảm từ validation sang test: dữ liệu thay đổi theo thời gian.
- Ghi rõ có 2 lần chạy test (`run-515a1190a0a4` và `run-d6faa4699008`); mọi metric chung trùng khớp (README, mục Kết quả).
- Hình: `docs/assets/results/results.png`.

### 4.3 Thí nghiệm rò rỉ (Stage E) — `leak-827d929eaa73`

- 7 biến thể, chỉ trên validation (118.108 dòng). Bảng đầy đủ: báo cáo Stage E, mục 2.
- Mã hoá `card1` rò nhãn: PR-AUC 0,245 → 0,308 (+0,063); bản hợp lệ chỉ +0,007.
- Tiền xử lý trên mọi dòng, khoảng trống 7 và 14 ngày: thay đổi không quá 0,004, nhỏ hơn độ rộng khoảng tin cậy.
- Chia ngẫu nhiên: PR-AUC *giảm* 0,068 (0,177). Tỷ lệ gian lận thấp hơn chỉ giải thích khoảng một phần ba; phần còn lại chưa giải thích.
- Thực thể lặp lại: 98,7% dòng validation có `card1` đã gặp trong train; 85,9% với `card1+addr1+P_emaildomain`.
- Trích Kapoor và Narayanan (2023) cho cách phân loại rò rỉ.

### 4.4 Gradient Boosting (Stage E) — `run-f8807cb6f780`

- Chọn `learning_rate` 0,1, `max_iter` 400, `max_leaf_nodes` 15; ngưỡng 0,853. Config `frozen` ở commit `89a8ed5`, test chạy một lần.
- PR-AUC validation 0,497 [0,483; 0,514], test **0,408** [0,390; 0,424], gấp khoảng 2,5 lần Logistic Regression; recall tại FPR 5% là 0,51.
- Tại ngưỡng: precision 0,516, recall 0,371, F1 0,432, FPR 1,24%.
- Hạn chế: tổ hợp tốt nhất ở cạnh lưới; chỉ 20 đặc trưng, chưa dùng bảng identity.

## 5. Product 01 — Độ ổn định thanh toán

### 5.1 Dữ liệu giả lập (Stage C)

- Bộ sinh theo luật, tái lập bằng `simulation_id`; 7 ngày, 3 provider, 150 payment/giờ.
- Bộ tuning `sim-485cacc9c858`: 25.573 payment, 30.050 sự kiện. Bộ report `sim-f6e6749ff0bf`: 25.151 payment, 29.340 sự kiện. Mỗi bộ 4 sự cố cài sẵn, nhãn tách riêng khỏi dữ liệu.
- Vì sao tăng từ 30 lên 150 payment/giờ: ở 30/giờ, tỷ lệ lỗi trong một khung 15 phút dao động ±22 điểm %, lớn hơn chính tỷ lệ lỗi 15% (`stage-c-spec.md`, sửa đổi A1).

### 5.2 KPI và detector (Stage D)

- KPI 15 phút bằng SQL views (ADR 0005), tách lỗi kỹ thuật khỏi lỗi nghiệp vụ.
- D-A: z-score bền vững (mốc so sánh). D-B: điểm nhị thức gộp cửa sổ (tính đến số attempt).

| Detector | Tuning `det-3ddc26cff253` | Report `det-08335c6af086` (một lần) |
| --- | --- | --- |
| D-B | 3/4 sự cố, 0 báo nhầm/ngày | 2/4 sự cố, 0 báo nhầm/ngày |
| D-A | 2/4, 1,0 báo nhầm/ngày | 0/4, 2,0 báo nhầm/ngày |

- Hình: `docs/assets/results/stage-d-tuning.png`, `docs/assets/results/stage-d-report.png`, và ảnh chụp dashboard (`make dashboard`).
- Điểm nên nhấn mạnh: D-A báo nhầm 14 lần, tất cả trong 01:45–05:45 giờ Việt Nam; D-B trượt sự cố mất lưu lượng vì ngưỡng được chỉnh trên loại sự cố khác; sự cố x1,5 nằm dưới giới hạn phát hiện.

## 6. Đánh giá trung thực và hạn chế (1–2 trang)

- Test một lần cho mỗi config đã chốt. Ở Stage D, config detector được commit và push (`e331ec1`) trước khi chạy bộ report; với Stage B, chủ dự án tự xác nhận thứ tự.
- Dữ liệu Product 01 là giả lập: kết quả là "kiểm chứng trên bất thường đã biết".
- IEEE-CIS: nhãn lan theo tài khoản, có thực thể lặp lại giữa các tập (ADR 0003).
- Mỗi bộ chỉ có 4 sự cố cài sẵn: là ví dụ minh hoạ, không phải tỷ lệ phát hiện.
- PostgreSQL mới chỉ kiểm chứng trên một bản cài tạm, chưa thử `make up` từ WSL.

## 7. Kết luận và hướng phát triển (1 trang)

- Đã làm được: hai sản phẩm có quy trình đánh giá giải thích được từng bước.
- Hướng tiếp: API chấm điểm (đã cắt khỏi phạm vi); ngưỡng riêng cho từng loại KPI (cần bộ report mới); LightGBM; dbt; dữ liệu thật có phê duyệt.

## Phụ lục

- Lệnh tái lập: README, mục "Chạy thử" và "Các lệnh khác".
- Danh sách ADR 0001–0008 và các đặc tả Stage C–F.
- Tài liệu tham khảo: tổng quan đề tài, mục 7.
