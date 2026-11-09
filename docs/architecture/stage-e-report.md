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
- **Kết quả ngược kỳ vọng:** chia ngẫu nhiên cho PR-AUC *thấp hơn* 0,068, trong khi rò rỉ thời gian thường làm điểm cao lên. Mục 2b phân tích nguyên nhân: phần lớn mức chênh đến từ việc hai validation **không phải cùng một tập dòng**, chứ không phải từ chất lượng mô hình.

### 2b. Vì sao chia ngẫu nhiên cho PR-AUC thấp hơn (chẩn đoán, 2026-11-09)

Lần chạy `diag-827d929eaa73` (`fraud_risk.experiments.split_diagnostics`), **chỉ dùng train và validation** của cách chia đã chốt (472.432 dòng); không dòng test nào được chấm hay đọc nhãn (test tự động đảo nhãn test và kiểm tra kết quả không đổi). Chia ngẫu nhiên ở đây xáo trộn *trong* 80% đầu, nên số liệu hơi khác `leak-827d929eaa73` (0,179 so với 0,177). Mô hình là Logistic Regression của Stage B.

**Ma trận 2×2**, PR-AUC (recall tại FPR 5%):

| Huấn luyện trên | Validation theo thời gian | Validation ngẫu nhiên |
| --- | --- | --- |
| Train theo thời gian | 0,245 (0,325) | 0,179 (0,311) |
| Train ngẫu nhiên | 0,257 (0,345) | 0,180 (0,329) |

- **Tập đánh giá quyết định, mô hình gần như không.** Đổi cách huấn luyện đổi PR-AUC 0,001–0,012; đổi tập đánh giá đổi khoảng 0,07.
- **Tỷ lệ gian lận** (3,54% so với 3,90%): quy về cùng tỷ lệ bằng trọng số chỉ nâng 0,179 lên 0,191, tức khoảng **0,012**, ít hơn ước lượng 0,022 trước đây.
- **Giai đoạn đầu:** validation ngẫu nhiên trải trên cả 6 tháng, gồm tuần 0–3 (khoảng 31.000 dòng) có tỷ lệ gian lận chỉ 1,9–2,8% và PR-AUC theo tuần thấp (tuần 1–2 khoảng 0,10). Bỏ tuần 0–3 thì PR-AUC của validation ngẫu nhiên tăng từ 0,179 lên 0,212 (mô hình train theo thời gian), tức giải thích khoảng một nửa mức chênh 0,066. Hai phần này (tỷ lệ gian lận và giai đoạn đầu) chồng nhau nên không cộng được. Việc chọn "tuần 0–3" được quyết định **sau khi đã xem bảng theo tuần**, nên đây là phân tích sau, không phải giả thuyết đặt trước.
- **Trên cùng 29.223 dòng** (validation ngẫu nhiên nằm trong giai đoạn của validation theo thời gian) mô hình train ngẫu nhiên đạt 0,245 và mô hình train theo thời gian đạt 0,234. Chênh +0,0117, khoảng tin cậy 95% [0,0087; 0,0145] (bootstrap cặp theo dòng, nên khoảng này hẹp hơn thực tế): lợi thế nhỏ của việc train có các giao dịch lân cận về thời gian.
- **Thực thể lặp lại không phải nguyên nhân:** tỷ lệ `card1` đã gặp trong train là 99,1% (ngẫu nhiên) và 98,7% (theo thời gian).
- **Chưa giải thích:** sau khi bỏ tuần 0–3, vẫn còn khoảng 0,03 giữa 0,245 và 0,212. Vài tuần trong khoảng 6–13 cũng có PR-AUC thấp, nhưng chưa kiểm tra riêng. Khoảng tin cậy cho điểm "bỏ tuần 0–3" chưa được tính.

**Kết luận.** Nhận định cũ "chia ngẫu nhiên làm điểm thấp hơn" dễ gây hiểu nhầm: hai cách chia dùng hai tập đánh giá khác nhau, và PR-AUC gộp nhiều tuần có tỷ lệ gian lận khác nhau thấp hơn trung bình từng tuần. Recall tại FPR 5%, chỉ số không phụ thuộc tỷ lệ gian lận, gần như không đổi (0,31–0,34), nên không có bằng chứng chia ngẫu nhiên làm *mô hình* kém đi. Điều này không có nghĩa chia ngẫu nhiên là chấp nhận được: nó vẫn trộn tương lai vào train, như lợi thế +0,0117 trên cùng dòng cho thấy.

## 3. Gradient Boosting trên IEEE-CIS

Lần chạy `run-f8807cb6f780` (validation). Lưới 8 tổ hợp, chọn theo PR-AUC validation: `learning_rate = 0,1`, `max_iter = 400`, `max_leaf_nodes = 15` (PR-AUC validation 0,497). Ngưỡng 0,853 chọn trên validation (tối đa F1). Cùng đặc trưng với baseline Logistic Regression.

| Mô hình | PR-AUC validation | PR-AUC test | Recall @ FPR 5% (test) | Lần chạy |
| --- | --- | --- | --- | --- |
| Luật (Stage B) | 0,089 | 0,078 | 0,22 | `run-d6faa4699008` |
| Logistic Regression (Stage B) | 0,245 | 0,165 | 0,28 | `run-d6faa4699008` |
| Gradient Boosting | 0,497 [0,483; 0,514] | **0,408** [0,390; 0,424] | **0,51** | `run-f8807cb6f780` |

Trên validation, Gradient Boosting có recall 0,588 tại FPR 5% và 0,480 khi giữ precision 0,50. PR-AUC trên train là 0,584, cao hơn validation 0,497, nên mô hình khớp train tốt hơn. **Hạn chế (đã kiểm tra ở mục 3b):** tổ hợp tốt nhất nằm ở cạnh lưới (`max_iter = 400`); lưới rộng đến 1.200 vòng không cho kết quả tốt hơn. Kết quả validation còn có thể hơi lạc quan vì đã chọn tổ hợp trên chính tập này; chỉ số test mới là con số để báo cáo.

**Kết quả trên test** (118.108 dòng, tỷ lệ gian lận 3,44%; ngưỡng 0,853 chọn trên validation, config `frozen`, commit `89a8ed5`, chạy một lần không `--force`):

- PR-AUC 0,408 [0,390; 0,424], giảm 0,089 so với validation (0,497). Logistic Regression giảm 0,080 (0,245 xuống 0,165). Gradient Boosting vẫn cao gấp khoảng 2,5 lần Logistic Regression trên test (0,408 so với 0,165), khoảng tin cậy hai mô hình không giao nhau.
- Tại ngưỡng đã chọn: precision 0,516, recall 0,371, F1 0,432, FPR 1,24%.
- Recall tại FPR 5%: 0,514 (Logistic Regression 0,28). Giữ precision 0,50 thì recall là 0,379.
- **Hạn chế:** sự sụt giảm từ validation sang test cho thấy chọn tổ hợp và ngưỡng trên validation hơi lạc quan, và dữ liệu thay đổi theo thời gian (mục 2). Chưa có giải thích nguyên nhân cụ thể, và mô hình chỉ dùng 20 đặc trưng, chưa dùng bảng identity.

## 3b. Thí nghiệm bổ sung: đặc trưng lịch sử thực thể (2026-11-08 và 2026-11-09, chỉ validation)

Câu hỏi: thêm hành vi quá khứ của cùng thực thể có giúp Gradient Boosting không? Các đặc trưng chỉ dùng giao dịch **trước đó**, không dùng nhãn (`_history`, `_window_count` trong `baseline_features.py`, có test "đổi giao dịch sau không đổi đặc trưng của giao dịch trước"): số giao dịch trước, số tiền chia trung bình số tiền trước, số giây từ giao dịch trước, và số giao dịch trong 24 giờ và 7 ngày trước. Cùng dữ liệu, cách chia, lưới và mô hình với `gbm.yaml`. Tất cả config ở trạng thái `draft`; **không** chạy trên test.

| Config | Khoá thực thể | PR-AUC train | PR-AUC validation [95% CI] | Recall @ FPR 5% | Lần chạy |
| --- | --- | --- | --- | --- | --- |
| `gbm.yaml` (gốc) | — | 0,584 | 0,497 [0,483; 0,514] | 0,588 | `run-f8807cb6f780` |
| `gbm-history-card1` (đếm tích luỹ) | `card1` | 0,689 | 0,497 [0,484; 0,513] | 0,59 | `run-0865527c0943` |
| `gbm-history-uid` (đếm tích luỹ) | `card1+addr1+P_emaildomain` | 0,596 | 0,499 [0,484; 0,517] | 0,60 | `run-d15b7985126a` |
| `gbm-history-window-card1` (24h, 7d) | `card1` | 0,690 | 0,5005 [0,487; 0,516] | 0,593 | `run-8f6422d09ac8` |
| `gbm-history-window-uid` (24h, 7d) | `card1+addr1+P_emaildomain` | 0,594 | 0,4895 [0,476; 0,507] | 0,588 | `run-b7f7e893f155` |
| `gbm-window-uidd` (24h, 7d) | uid + `D1n` | 0,600 | 0,5085 [0,493; 0,523] | 0,613 | `run-f42906337c71` |
| `gbm-wide-grid` (`max_iter` đến 1.200) | — | 0,584 | 0,497 [0,483; 0,514] | 0,588 | `run-14499cc27f0a` |
| `gbm-agg-uid` (24h, 7d + tổng hợp) | `card1+addr1+P_emaildomain` | 0,609 | 0,4968 [0,483; 0,513] | 0,593 | `run-18a73d0c29f4` |
| `gbm-agg-uidd` (24h, 7d + tổng hợp) | uid + `D1n` | 0,607 | 0,4984 [0,483; 0,514] | 0,596 | `run-77d836c1ea94` |

**Kiểm tra các giả thuyết.**

1. *Đặc trưng đếm tích luỹ không dừng theo thời gian.* **Đúng.** Số giữa của `card1_prev_count` là 186 ở train và 629 ở validation; 4,2% dòng validation vượt mọi giá trị trong train. Tỷ lệ gian lận của giao dịch đầu tiên của một `card1` là 2,2% (train) và 5,3% (validation). Nhưng thay bằng đếm theo cửa sổ 24 giờ và 7 ngày (ổn định hơn) vẫn **không cải thiện** (+0,004 cho `card1`, −0,008 cho `uid`), nên đây không phải nguyên nhân chính.
2. *Các cột `C1–C14` đã chứa thông tin theo thực thể.* **Được ủng hộ mạnh.** Bỏ `C1–C14` thì PR-AUC validation rơi từ 0,497 xuống **0,158** [0,149; 0,169] (`run-2d45949ed489`). Khi không có chúng, đặc trưng lịch sử của đề tài giúp một chút: 0,177 [0,167; 0,187] với `card1` (`run-c5e7a212d3b8`) và 0,174 [0,165; 0,185] với `uid` (`run-8ecd86529b93`), tăng khoảng 0,016–0,019, nhưng còn rất thấp so với 0,497. Kết luận: `C1–C14` mang gần như toàn bộ tín hiệu theo thực thể, mạnh hơn nhiều so với lịch sử mà đề tài tự dựng từ dữ liệu có sẵn. Phép đo Spearman 0,01–0,15 trước đây không phát hiện được điều này vì nó chỉ đo quan hệ đơn điệu từng cặp. Việc `C1–C14` đếm gì lấy từ thảo luận công khai của cuộc thi, **chưa xác minh với tài liệu gốc**.
3. *Tổ hợp tốt nhất nằm ở cạnh lưới.* **Bác bỏ.** Với `max_iter` 400, 800, 1.200, tổ hợp tốt nhất vẫn là `learning_rate 0,1`, `max_iter 400`, `max_leaf_nodes 15` (0,497); `learning_rate 0,05` với 1.200 vòng cho 0,4969.
4. *Khoá `card1+addr1+P_emaildomain` vẫn trộn nhiều khách hàng.* **Một phần.** Thêm `D1n` (ngày giao dịch trừ `D1`, ngày thẻ bắt đầu dùng; hằng số với một thẻ) cho kết quả tốt nhất: 0,5085.

5. *Thống kê tổng hợp theo thực thể như giải pháp công khai của cuộc thi.* **Không giúp.** Áp ý tưởng (độ lệch chuẩn và z-score của số tiền, số giá trị `ProductCD` và `C13` khác nhau trong một thực thể) nhưng chỉ dùng các giao dịch **trước đó** của thực thể (`_aggregate`; có test tính tay và test "đổi giao dịch sau không đổi đặc trưng của giao dịch trước"). Theo các bài viết thứ cấp tôi đọc được (chưa xác minh với bản gốc), các giải pháp công khai gộp trên toàn bộ dữ liệu; nếu đúng vậy, cách đó gồm cả giao dịch tương lai và validation, vi phạm quy tắc fit trên train và không có trong hệ thống thật, nên **không** được dùng ở đây. Kết quả: 0,4968 (`uid`) và 0,4984 (`uidd`); kiểm định cặp theo cụm `card1` so với gốc cho chênh −0,0002 [−0,0094; +0,0093] và +0,0022 [−0,0117; +0,0173]. Thêm các thống kê này vào `uidd` còn làm điểm thấp hơn bản `uidd` không có chúng (0,5085). Nguyên nhân chưa kiểm tra; có thể thông tin quá khứ ngắn không đủ để thống kê ổn định, và nếu cách gộp trên toàn bộ dữ liệu có lợi thế thì một phần có thể đến từ việc nhìn thấy tương lai; cả hai đều là giả thuyết.

**Kiểm định cặp** (`paired_comparison`: fit lại mô hình đã chọn của từng lần chạy trên train, số validation fit lại khớp số đã ghi; bootstrap 500 lần, seed 42, trên cùng 118.108 dòng validation; chênh = biến thể trừ gốc):

| Biến thể | Chênh PR-AUC, lấy mẫu theo dòng | Chênh PR-AUC, lấy mẫu theo cụm `card1` | Chênh recall @ FPR 5%, theo cụm |
| --- | --- | --- | --- |
| `gbm-window-uidd` | +0,0114 [+0,0054; +0,0168] | +0,0120 [−0,0026; +0,0249] | +0,0218 [+0,0033; +0,0424] |
| `gbm-history-window-card1` | +0,0035 [−0,0016; +0,0085] | +0,0036 [−0,0086; +0,0162] | +0,0025 [−0,0125; +0,0175] |
| `gbm-history-window-uid` | −0,0074 [−0,0118; −0,0030] | −0,0074 [−0,0191; +0,0035] | −0,0006 [−0,0169; +0,0150] |
| `gbm-agg-uid` | — | −0,0002 [−0,0094; +0,0093] | +0,0041 [−0,0118; +0,0223] |
| `gbm-agg-uidd` | — | +0,0022 [−0,0117; +0,0173] | +0,0069 [−0,0074; +0,0235] |

- Lấy mẫu theo dòng cho khoảng tin cậy quá hẹp vì các giao dịch của cùng một thẻ tương quan với nhau. Lấy mẫu theo cụm `card1` rộng gấp khoảng hai lần và là con số nên dùng.
- Theo cụm, **chỉ chênh recall của `uidd` loại trừ 0** (cận dưới +0,0033, sát 0); chênh PR-AUC của `uidd` **không** đủ ý nghĩa ([−0,0026; +0,0249]). Hai biến thể còn lại không khác gốc.
- So sánh 3 ứng viên với một mốc gốc, chưa hiệu chỉnh nhiều lần so sánh; `uidd` là tốt nhất trong các biến thể đã thử nên có nguy cơ chọn lọc có lợi. Cả hai mô hình đều chọn siêu tham số trên chính validation này.

**Kết luận.** Đặc trưng lịch sử thực thể tự dựng **không cải thiện đo được** Gradient Boosting, vì `C1–C14` đã chứa phần lớn thông tin này. Khoá có `D1n` cho gợi ý cải thiện nhỏ (recall +0,02 tại FPR 5%) ở ranh giới ý nghĩa thống kê, chưa đủ để đổi cấu hình đã đóng băng. Muốn xác nhận cần bộ dữ liệu hoặc giai đoạn mới; mở tập test cho các config này cần quyết định của chủ dự án.

**Tài liệu liên quan** (đã có trong danh mục tham khảo của bài báo): Saito và Rehmsmeier về tính phụ thuộc tỷ lệ lớp dương của PR-AUC; Gama về trôi khái niệm; Kapoor và Narayanan về rò rỉ; Jesus và cộng sự về recall tại FPR cố định. **Chưa xác minh, chưa đưa vào danh mục:** bài "Enhancing Credit Card Fraud Detection under Severe Class Imbalance using Cost-Sensitive Learning and Threshold Optimization" (EAI ISMLA) nói kiểm định theo thời gian cho PR-AUC thấp hơn kiểm định ngẫu nhiên trên bộ dữ liệu 2013; mới đọc được tóm tắt, chưa biết tác giả, năm, DOI. Các bài viết giải pháp hạng đầu của cuộc thi (UID từ `card1`, `addr1`, `D1n`) là nguồn thứ cấp, một trang trả về lỗi 403 khi tôi truy cập.

## 4. Việc chủ dự án cần làm (trên máy có dataset)

Đã xong cả ba bước (2026-11-06): `make leakage`, `make gbm`, đặt `status: frozen` rồi `make gbm-final` một lần. **Không chạy lại `make gbm-final` với config này.** Thứ tự thực tế: commit bản đóng băng (`89a8ed5`) trước, chạy test, rồi mới push.

## 5. Kiểm tra trong môi trường của agent

- `make lint`: pass.
- `make test` với PostgreSQL 16 tạm: **364 test pass**, không test nào bị bỏ qua. Độ phủ toàn repo 94%.
