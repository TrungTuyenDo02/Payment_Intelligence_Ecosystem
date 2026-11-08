# Báo cáo Stage E — Thí nghiệm rò rỉ dữ liệu và Gradient Boosting

- **Ngày:** 2026-11-04 (tuần 5 của lịch 6 tuần)
- **Đặc tả:** [`stage-e-spec.md`](stage-e-spec.md), [ADR 0006](../decisions/0006-gradient-boosting-sklearn.md).
- **Trạng thái:** E01–E04 xong code và test. Thí nghiệm rò rỉ (`leak-827d929eaa73`) và Gradient Boosting trên validation (`run-f8807cb6f780`) đã chạy trên IEEE-CIS ngày 2026-11-06. Config `gbm.yaml` đã `frozen`; `gbm-final` đã chạy **một lần** (2026-11-06, cùng mã lần chạy `run-f8807cb6f780`, thư mục `test/`).

## 1. Đã làm gì

| Task | Nội dung | Kiểm chứng (trên fixture tổng hợp) |
| --- | --- | --- |
| E01 | `gap_days` trong `time_split` và config | Bỏ đúng các dòng cuối train, validation và test không đổi; `gap_days = 0` giữ nguyên mốc split nên mã lần chạy của baseline đã chốt không đổi |
| E02 | Thực thể lặp lại; mã hoá theo nhãn, có bản ngoài fold | Khớp ví dụ tính tay; không đọc nhãn test; mã hoá ngoài fold không dùng nhãn của chính dòng |
| E03 | `make leakage`: 7 biến thể, chỉ trên validation | Mọi biến thể chấm cùng số dòng validation; đảo nhãn test không đổi kết quả; test T10 chỉ cho phép `random_split` ở `split.py` và file thí nghiệm |
| E04 | `make gbm`, `make gbm-final` | Fit trên train, chọn trên validation; hai lần chạy cho `metrics.json` giống hệt; `gbm-final` từ chối config `draft` và từ chối chạy lại |

Thời gian chạy đo trên dữ liệu tổng hợp cùng kích thước IEEE-CIS (590.540 dòng): thí nghiệm rò rỉ khoảng 70 giây, mỗi điểm lưới Gradient Boosting tối đa khoảng 6 giây, chưa tính thời gian đọc CSV.

**Kiểm tra cơ chế trên fixture** (3.000 dòng tổng hợp, không có ý nghĩa về gian lận thật): mã hoá `card1` bằng nhãn validation đẩy PR-AUC validation từ 0,168 lên 0,967; mã hoá đúng cách cho 0,166. Đây chỉ chứng minh code phát hiện được rò rỉ, không phải kết quả của đề tài.

## 2. Thí nghiệm rò rỉ trên IEEE-CIS

Lần chạy `leak-827d929eaa73`, **chỉ đánh giá trên validation** (118.108 dòng, Logistic Regression của Stage B):

| Biến thể | PR-AUC [95% CI] | Chênh so với đúng quy tắc | Recall @ FPR 5% |
| --- | --- | --- | --- |
| Đúng quy tắc (baseline Stage B) | 0,245 [0,235; 0,257] | +0,000 | 0,33 |
| Chia ngẫu nhiên thay vì theo thời gian | 0,177 [0,168; 0,190] | −0,068 | 0,31 |
| Fit tiền xử lý trên mọi dòng | 0,244 [0,234; 0,256] | −0,001 | 0,33 |
| Thêm mã hoá `card1` bằng nhãn train | 0,252 [0,242; 0,264] | +0,007 | 0,37 |
| Mã hoá `card1` bằng nhãn train + validation (rò nhãn) | 0,308 [0,297; 0,321] | **+0,063** | 0,43 |
| Khoảng trống 7 ngày trước validation | 0,244 [0,233; 0,256] | −0,002 | 0,32 |
| Khoảng trống 14 ngày trước validation | 0,241 [0,231; 0,253] | −0,004 | 0,32 |

Thực thể lặp lại: 98,7% dòng validation có `card1` đã gặp trong train; với `card1+addr1+P_emaildomain` là 85,9%.

**Đọc kết quả.**

- Rò nhãn rõ nhất là mã hoá `card1` bằng nhãn validation: PR-AUC tăng 0,063, và chỉ số này gần như không đổi khi dùng nhãn train đúng cách (+0,007).
- Fit tiền xử lý trên mọi dòng và khoảng trống 7–14 ngày chỉ đổi PR-AUC không quá 0,004, nhỏ hơn độ rộng khoảng tin cậy (khoảng 0,02). Với cấu hình baseline này, các biến thể đó **không tạo khác biệt đo được**.
- **Kết quả ngược kỳ vọng:** chia ngẫu nhiên cho PR-AUC *thấp hơn* 0,068, trong khi rò rỉ thời gian thường làm điểm cao lên. Điều chưa giải thích được hết:
  - Tỷ lệ gian lận của validation bị chia ngẫu nhiên là 3,55% so với 3,90% của validation theo thời gian. PR-AUC phụ thuộc tỷ lệ gian lận; nếu chỉ nhân theo tỷ lệ này, 0,245 chỉ xuống khoảng 0,223. Phần này giải thích khoảng một phần ba mức giảm. **Khoảng 0,046 còn lại chưa có lời giải thích.**
  - Tỷ lệ gian lận không đứng yên theo thời gian: theo tuần dao động từ 1,85% đến 5,06% (train 3,38%, validation 3,90%). Điều này cho thấy dữ liệu thay đổi theo thời gian, nhưng validation **không nổi bật như một đợt bùng phát**: các tuần 4–10 của train cũng cao (3,8–4,6%). Vì vậy giả thuyết "giai đoạn bùng phát" chỉ được hỗ trợ yếu.
  - Cơ chế của mô hình tuyến tính (gian lận dồn theo đợt khiến dễ phân tách hơn) là **giả thuyết, chưa kiểm tra**.

## 3. Gradient Boosting trên IEEE-CIS

Lần chạy `run-f8807cb6f780` (validation). Lưới 8 tổ hợp, chọn theo PR-AUC validation: `learning_rate = 0,1`, `max_iter = 400`, `max_leaf_nodes = 15` (PR-AUC validation 0,497). Ngưỡng 0,853 chọn trên validation (tối đa F1). Cùng đặc trưng với baseline Logistic Regression.

| Mô hình | PR-AUC validation | PR-AUC test | Recall @ FPR 5% (test) | Lần chạy |
| --- | --- | --- | --- | --- |
| Luật (Stage B) | 0,089 | 0,078 | 0,22 | `run-d6faa4699008` |
| Logistic Regression (Stage B) | 0,245 | 0,165 | 0,28 | `run-d6faa4699008` |
| Gradient Boosting | 0,497 [0,483; 0,514] | **0,408** [0,390; 0,424] | **0,51** | `run-f8807cb6f780` |

Trên validation, Gradient Boosting có recall 0,588 tại FPR 5% và 0,480 khi giữ precision 0,50. PR-AUC trên train là 0,584, cao hơn validation 0,497, nên mô hình khớp train tốt hơn. **Hạn chế:** tổ hợp tốt nhất nằm ở cạnh lưới (`max_iter = 400` là giá trị lớn nhất), nên chưa biết tăng thêm có tốt hơn không. Kết quả validation còn có thể hơi lạc quan vì đã chọn tổ hợp trên chính tập này; chỉ số test mới là con số để báo cáo.

**Kết quả trên test** (118.108 dòng, tỷ lệ gian lận 3,44%; ngưỡng 0,853 chọn trên validation, config `frozen`, commit `89a8ed5`, chạy một lần không `--force`):

- PR-AUC 0,408 [0,390; 0,424], giảm 0,089 so với validation (0,497). Logistic Regression giảm 0,080 (0,245 xuống 0,165). Gradient Boosting vẫn cao gấp khoảng 2,5 lần Logistic Regression trên test (0,408 so với 0,165), khoảng tin cậy hai mô hình không giao nhau.
- Tại ngưỡng đã chọn: precision 0,516, recall 0,371, F1 0,432, FPR 1,24%.
- Recall tại FPR 5%: 0,514 (Logistic Regression 0,28). Giữ precision 0,50 thì recall là 0,379.
- **Hạn chế:** sự sụt giảm từ validation sang test cho thấy chọn tổ hợp và ngưỡng trên validation hơi lạc quan, và dữ liệu thay đổi theo thời gian (mục 2). Chưa có giải thích nguyên nhân cụ thể, và mô hình chỉ dùng 20 đặc trưng, chưa dùng bảng identity.

## 3b. Thí nghiệm bổ sung: đặc trưng lịch sử thực thể (2026-11-08, chỉ validation)

Câu hỏi: thêm hành vi quá khứ của cùng thực thể có giúp Gradient Boosting không? Ba đặc trưng, chỉ dùng các giao dịch **trước đó**, không dùng nhãn (`_history` trong `baseline_features.py`, có test "đổi giao dịch sau không đổi đặc trưng của giao dịch trước"): số giao dịch trước, số tiền chia trung bình số tiền trước, số giây từ giao dịch trước. Cùng dữ liệu, cách chia, lưới và mô hình với `gbm.yaml`.

| Config | Khoá thực thể | PR-AUC train | PR-AUC validation [95% CI] | Recall @ FPR 5% | Lần chạy |
| --- | --- | --- | --- | --- | --- |
| `gbm.yaml` (gốc) | — | 0,584 | 0,497 [0,483; 0,514] | 0,59 | `run-f8807cb6f780` |
| `gbm-history-card1.yaml` | `card1` (13.553 giá trị) | 0,689 | 0,497 [0,484; 0,513] | 0,59 | `run-0865527c0943` |
| `gbm-history-uid.yaml` | `card1+addr1+P_emaildomain` (90.375 nhóm) | 0,596 | 0,499 [0,484; 0,517] | 0,60 | `run-d15b7985126a` |

**Đọc kết quả.**

- **Không cải thiện đo được** trên validation: chênh không quá 0,002, nằm trong khoảng tin cậy.
- Với `card1`, PR-AUC train tăng mạnh (0,584 → 0,689) mà validation đứng yên: mô hình học thuộc train hơn, không tổng quát hơn. `card1` có khoảng 44 giao dịch mỗi giá trị, nên nó không phải "một khách hàng".
- Giả thuyết "đặc trưng mới trùng thông tin với `C1–C14`" đã được kiểm tra và **bác bỏ**: tương quan Spearman chỉ 0,01–0,15. Nguyên nhân chưa giải thích.
- Hai config này `draft`, **không** đăng ký cho tập test; không chạy `gbm-final` với chúng.

## 4. Việc chủ dự án cần làm (trên máy có dataset)

Đã xong cả ba bước (2026-11-06): `make leakage`, `make gbm`, đặt `status: frozen` rồi `make gbm-final` một lần. **Không chạy lại `make gbm-final` với config này.** Thứ tự thực tế: commit bản đóng băng (`89a8ed5`) trước, chạy test, rồi mới push.

## 5. Kiểm tra trong môi trường của agent

- `make lint`: pass.
- `make test` với PostgreSQL 16 tạm: **364 test pass**, không test nào bị bỏ qua. Độ phủ toàn repo 94%.
