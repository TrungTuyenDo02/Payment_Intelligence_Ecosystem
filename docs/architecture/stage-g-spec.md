# Đặc tả Stage G — Từ xếp hạng đến quyết định (Product 02)

- **Trạng thái:** **Bản nháp, chờ chủ dự án duyệt** (⏸ G01). Chưa có dòng code Stage G nào trước khi đặc tả này được duyệt.
- **Liên quan:** [ADR 0009](../decisions/0009-decision-evaluation-protocol.md) (protocol đánh giá), [ADR 0003](../decisions/0003-label-delay-and-entity-overlap.md) (độ trễ nhãn), [ADR 0006](../decisions/0006-gradient-boosting-sklearn.md), [ADR 0008](../decisions/0008-entity-history-features.md), [báo cáo Stage E](stage-e-report.md).
- **Mọi kết quả Stage G là "thăm dò"** (xem mục 8).

## 1. Mục tiêu

Stage E trả lời "mô hình xếp hạng tốt đến đâu". Stage G trả lời câu hỏi tiếp theo: **dùng điểm số thế nào để ra quyết định** (chặn, đưa đi duyệt, cho qua), và quyết định đó ổn định đến đâu theo thời gian. Ba phần:

1. **Hiệu chỉnh xác suất** (G03): điểm của mô hình có đọc được như xác suất không, và hiệu chỉnh có giúp không.
2. **So sánh chính sách** (G04): ngưỡng tối đa F1, ngưỡng theo chi phí giả định, ngân sách duyệt top-N mỗi ngày; kèm phép thử chuyển ngưỡng.
3. **Độ ổn định** (G05): metric theo tuần và theo nhóm, độ trôi phân phối đặc trưng.

**Không** đổi mô hình, không thêm thuật toán, không mở tập test.

## 2. Dữ liệu và mô hình

- **Dữ liệu phát triển** = train + validation của split đã chốt (60/20/20 theo thời gian, `gbm.yaml`). Train: 354.324 dòng (ngày 1–101). Validation: 118.108 dòng, 4.611 gian lận (3,90%), ngày 101–141 (`TransactionDT // 86400`).
- **Tập test (118.108 dòng, từ `TransactionDT` 12.192.900) không được nạp vào bất kỳ bước nào.** Code lọc `TransactionDT <= 12.192.842` (mốc cuối validation trong `split.json` của `run-f8807cb6f780`) **trước** khi đọc nhãn.
- **Mô hình chính:** HistGradientBoosting đúng cấu hình đã chọn trong `run-f8807cb6f780`: `learning_rate=0,1`, `max_iter=400`, `max_leaf_nodes=15`, `class_weight="balanced"`, `early_stopping=False`, seed 42, cùng đặc trưng `gbm.yaml`. **Không quét lại lưới.** Fit một lần trên train.
- **Mô hình phụ (chỉ cho G03):** Logistic Regression của `baseline.yaml`, fit trên train.
- **Kiểm tra trùng khớp:** trước mọi phân tích, PR-AUC validation của mô hình tái tạo phải bằng 0,497 (GBM) và 0,245 (LR) với sai số ≤ 0,002; lệch hơn thì dừng và báo (nghĩa là không phải cùng mô hình).

## 3. Ba khối validation

Chia validation **theo ngày** (`TransactionDT // 86400`), không cắt giữa ngày, để chính sách top-N mỗi ngày dùng được ngày trọn vẹn.

| Khối | Vai trò | Ngày | Dòng | Gian lận | Tỷ lệ | Tổng tiền gian lận |
| --- | --- | --- | --- | --- | --- | --- |
| **V1** | Fit bộ hiệu chỉnh | 101–113 | 38.426 | 1.523 | 3,96% | 283.466 |
| **V2** | Chọn chính sách (ngưỡng, phương pháp hiệu chỉnh) | 114–126 | 41.426 | 1.741 | 4,20% | 291.362 |
| **V3** | Đánh giá chính sách | 127–141 | 38.256 | 1.347 | 3,52% | 221.292 |

- Ngày 101 và 141 không trọn (train kết thúc và test bắt đầu giữa hai ngày này: ngày 101 có 1.892 dòng validation, ngày 141 có 426).
- Phương án cắt theo số dòng (mỗi khối 39.369–39.370 dòng) cho kích thước đều hơn nhưng cắt giữa ngày 114 và 126; không chọn vì G04 cần ngày trọn.
- Tỷ lệ gian lận V3 (3,52%) thấp hơn V1/V2 (3,96%/4,20%). Đây chính là loại trôi mà G03/G04 cần thấy, không phải lỗi.
- **Quy tắc dùng khối:** nhãn V3 không được dùng để fit hay chọn bất cứ thứ gì. Mọi lựa chọn (phương pháp hiệu chỉnh, ngưỡng, N) được ra trên V1/V2 trong cùng một lần chạy, rồi mới áp lên V3. Bảng V3 báo **toàn bộ** lưới đã đăng ký trước, không chọn dòng đẹp.

## 4. Đánh giá cuốn chiếu (phân tích độ nhạy)

Tuần validation tính từ đầu validation: W0–W5 (W0–W4 mỗi tuần 18,7–22,4 nghìn dòng, 699–1.051 gian lận; W5 chỉ 5,7 ngày, 13.173 dòng, 409 gian lận). Bốn cửa sổ:

| Cửa sổ | Hiệu chỉnh | Chọn | Đánh giá |
| --- | --- | --- | --- |
| R1 | W0 | W1 | W2 |
| R2 | W1 | W2 | W3 |
| R3 | W2 | W3 | W4 |
| R4 | W3 | W4 | W5 |

- Mô hình vẫn là mô hình fit trên train (không fit lại theo cửa sổ): cửa sổ đo việc **chọn chính sách** ổn định đến đâu, không đo việc huấn luyện lại.
- Báo từng cửa sổ riêng và khoảng dao động; **không** gộp thành một con số chính. Kết luận chính lấy từ V1/V2/V3.

## 5. Phân tích đăng ký trước

Mọi config Stage G là `status: draft`, nằm trong `projects/fraud-risk/configs/`, và được commit **trước** lần chạy đầu tiên có số liệu V3. Sửa config sau khi đã thấy V3 là config mới, phải ghi trong báo cáo G06 cùng lý do.

### 5.1 G03 — Hiệu chỉnh (`configs/calibration.yaml`, `make calibration`)

- Mô hình: LR và GBM.
- Phương pháp: (a) gốc; (b) **dịch tiên nghiệm**: bù `class_weight="balanced"` bằng cách đổi log-odds theo tỷ lệ gian lận của train (với LR, công thức chỉ đúng khi mô hình đúng dạng; với GBM chỉ là xấp xỉ); (c) **sigmoid (Platt)** trên logit của điểm gốc, fit trên V1. Isotonic **không** nằm trong danh sách chính (đề xuất; xem câu hỏi Q3).
- Metric: Brier score, log loss, reliability diagram (10 bin theo phân vị điểm), trên V2 và V3, và trên từng tuần.
- Chọn phương pháp hiệu chỉnh cho G04 theo **log loss trên V2**.
- Ghi rõ trong kết quả: hiệu chỉnh đơn điệu không đổi PR-AUC và không đổi chính sách top-N; nó chỉ ảnh hưởng ngưỡng theo chi phí.

### 5.2 G04 — Chính sách (`configs/policy.yaml`, `make policy`)

| Chính sách | Chọn trên V2 | Áp lên V3 |
| --- | --- | --- |
| `max_f1` (mốc) | Ngưỡng tối đa F1 | Ngưỡng cố định đó |
| Theo chi phí (điểm gốc) | Ngưỡng làm nhỏ nhất tổng chi phí trên V2 | Ngưỡng cố định đó |
| Theo chi phí (điểm đã hiệu chỉnh) | Hai cách, báo cả hai: (i) ngưỡng tối ưu trên V2; (ii) ngưỡng lý thuyết từ xác suất `p × loss > c_review + (1 − p) × c_friction`, không cần V2 | Ngưỡng cố định đó |
| Ngân sách duyệt | Không cần chọn | Mỗi ngày đưa N% giao dịch có điểm cao nhất đi duyệt, N ∈ {0,5; 1; 2; 5}% |

**Mô hình chi phí — toàn bộ là giả định, đơn vị tương đối theo đơn vị của `TransactionAmt`:**

- Bỏ sót một gian lận: `loss_rate × TransactionAmt`, `loss_rate` ∈ {0,5; 0,75; 1,0}.
- Mỗi cảnh báo (đúng hay nhầm) cần duyệt: `c_review` ∈ {1; 5; 25}.
- Mỗi cảnh báo nhầm thêm phiền khách hàng: `c_friction` ∈ {0; 1; 10}.
- Tham khảo thang đo (chỉ từ train): trung vị `TransactionAmt` 70, trung vị của giao dịch gian lận 77, phân vị 90 là 280.
- 27 tổ hợp chi phí × các chính sách. Chính sách top-N không phụ thuộc chi phí khi chọn, nhưng chi phí của nó vẫn tính để so.

Báo trên V3 cho mỗi dòng: số gian lận bắt được, **số tiền** gian lận bắt được, cảnh báo nhầm, số giao dịch phải duyệt, tổng chi phí, kèm điểm gốc và điểm đã hiệu chỉnh. Khoảng tin cậy 95%: bootstrap **theo ngày** (lấy lại 15 ngày của V3 có hoàn lại) và bootstrap **theo cụm `card1`**, 1.000 lần, seed cố định. Không bootstrap theo dòng.

**Phép thử chuyển ngưỡng:** chọn trên V2 ngưỡng cho FPR 5%, áp lên V3, báo FPR và recall thực tế trên V3 (và trên từng cửa sổ R1–R4). Mục đích: cho thấy con số "recall @ FPR 5%" chọn ngưỡng bằng nhãn của chính tập đánh giá lạc quan hơn ngưỡng chọn trước.

Kết quả gọi là **phân tích độ nhạy**, không phải ROI. Mỗi kết luận phải nêu vùng giả định chi phí làm nó đúng.

### 5.3 G05 — Độ ổn định (`configs/stability.yaml`, `make stability`)

- PR-AUC và recall @ FPR 5% theo **tuần** của train (chỉ để mô tả, mô hình đã thấy dữ liệu này) và của validation W0–W5.
- Theo nhóm `ProductCD` và `card6` trên validation; nhóm có dưới 30 gian lận được đánh dấu "cỡ mẫu nhỏ, không kết luận".
- PSI cho `TransactionAmt`, `C1`, `C13`, `hour_of_day`: tham chiếu là train, 10 bin theo phân vị của train, so từng tuần validation. Ngưỡng đọc quen thuộc (0,1 / 0,25) chỉ là quy ước, không phải kiểm định.
- Tỷ lệ gian lận và tỷ lệ thiếu theo tuần (train + validation).

## 6. Mã lần chạy

- Dùng `compute_run_hash` hiện có (config, seed, checksum dataset, mốc chia) cộng thêm mốc ngày của V1/V2/V3. Tiền tố: `cal-`, `pol-`, `stab-`.
- Chưa tách `experiment_id` / `execution_id` (việc của G07, ADR 0010). Đến lúc đó, mỗi lần chạy ghi thêm `environment.txt` và `git_sha.txt` như run log hiện tại.

## 7. Kiểm tra bắt buộc (CLAUDE.md mục 8)

| Kiểm tra | Cách làm trong Stage G |
| --- | --- |
| Không chạm test | Test tự động: thêm hoặc đổi các dòng có `TransactionDT` sau mốc validation (kể cả nhãn) không đổi bất kỳ output nào |
| Đảo nhãn | Hoán vị nhãn V3: PR-AUC về gần tỷ lệ gian lận, chi phí của chính sách không còn tốt hơn chính sách ngẫu nhiên cùng số cảnh báo |
| Nhìn tương lai | Đổi nhãn V3 không đổi bộ hiệu chỉnh, ngưỡng và N đã chọn; đổi dữ liệu sau ngày d không đổi chính sách top-N các ngày ≤ d |
| Phá hoại có chủ đích | Cố tình fit bộ hiệu chỉnh trên V3 hoặc chọn ngưỡng trên V3: test phải bắt được (hàm nhận khối sai vai trò thì báo lỗi) |
| Tính độc lập | Tính lại Brier và tổng chi phí trên khoảng 1.000 dòng bằng vòng lặp thuần Python, so với code chính |
| Tái lập | Chạy hai lần: cùng mã lần chạy, cùng số |

## 8. Hạn chế đã biết (ghi lại trong mọi báo cáo Stage G)

1. **Validation đã bị dùng nhiều lần**: chọn lưới GBM, thí nghiệm rò rỉ, đặc trưng lịch sử (ADR 0008), so sánh cặp. Cấu hình GBM được chọn vì có PR-AUC validation cao nhất, nên mọi con số Stage G trên validation có thể lạc quan. V3 không phải dữ liệu "chưa thấy" theo nghĩa của tập test.
2. **Không dùng lại tập test**: test đã dùng một lần cho `gbm-final` (`run-f8807cb6f780`). Chọn chính sách bằng test sẽ làm con số 0,408 mất tính không thiên lệch, và quy tắc test-một-lần không cho phép. Hệ quả: Stage G không có ước lượng không thiên lệch nào cho chính sách; nó chỉ cho thấy **cách** đánh giá và độ nhạy.
3. **Độ trễ nhãn bị bỏ qua giữa các khối**: bộ hiệu chỉnh fit trên V1 được áp ngay lên V2, như thể nhãn V1 có ngay. Thực tế chargeback đến muộn (ADR 0003). Đây là giả định lạc quan.
4. **Mô hình chỉ fit trên train**: V3 cách cuối train 26–40 ngày; một hệ thống thật có thể huấn luyện lại thường xuyên hơn.
5. **Khoảng tin cậy thô**: V3 chỉ có 15 ngày, nên bootstrap theo ngày có ít khối; cụm `card1` không phải định danh khách hàng chắc chắn.
6. **Chi phí là giả định** đơn vị tương đối, không có dữ liệu chi phí thật; `TransactionAmt` không rõ đơn vị tiền tệ.
7. Ý nghĩa của `C1–C14` (mang gần hết tín hiệu) vẫn chưa xác minh.

## 9. Quyết định cần chủ dự án duyệt

| # | Đề xuất | Lý do | Phương án khác |
| --- | --- | --- | --- |
| D1 | V1/V2/V3 theo ngày như mục 3 | Top-N mỗi ngày cần ngày trọn | Cắt theo số dòng (đều hơn, cắt giữa ngày) |
| D2 | Mô hình cố định, không quét lại lưới, không fit lại theo cửa sổ | Stage G đánh giá quyết định, không phải mô hình | Fit lại trên train + V1 (thay đổi mô hình chính, ngoài phạm vi) |
| D3 | Không có khoảng trống giữa các khối (hạn chế 3) | Mỗi khối đã chỉ có 13–15 ngày | Bỏ 7 ngày đầu V2 và V3 (còn khoảng 6–8 ngày mỗi khối) |
| D4 | Lưới chi phí ở mục 5.2 (27 tổ hợp) | Bao vài bậc độ lớn quanh trung vị số tiền | Lưới khác do chủ dự án chọn |
| D5 | Isotonic không nằm trong danh sách chính | Bộ hiệu chỉnh đơn giản đủ cho mục tiêu; isotonic dễ quá khớp theo bậc | Thêm isotonic làm dòng phụ (V1 có 1.523 gian lận, có thể đủ) |
| D6 | Bootstrap 1.000 lần, theo ngày và theo `card1` | Hàng xóm theo thời gian và theo thẻ tương quan | 200 lần như `gbm.yaml` |
| D7 | Chọn phương pháp hiệu chỉnh theo log loss trên V2 | Log loss nhạy với xác suất cực trị, đúng thứ ngưỡng chi phí cần | Brier |
| D8 | Mã lần chạy theo mục 6, tách id để G07 | G07 cần ADR riêng | Làm G07 trước G03 |
