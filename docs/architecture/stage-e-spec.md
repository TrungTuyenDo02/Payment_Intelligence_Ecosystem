# Đặc tả Stage E — Thí nghiệm rò rỉ dữ liệu và Gradient Boosting (Product 02)

- **Trạng thái:** **Đã duyệt theo uỷ quyền**: chủ dự án yêu cầu trong chat (2026-11-04) "tự động theo đề xuất của agent". Mọi quyết định ở mục 9 là đề xuất của agent, ghi kèm lý do; chủ dự án có thể đổi bất kỳ dòng nào. Đổi sau khi đã chạy test là một config mới và phải ghi trong báo cáo.
- **Liên quan:**
  - [ADR 0003](../decisions/0003-label-delay-and-entity-overlap.md) (phương án B): khoảng trống `gap_days` và đo thực thể lặp lại, làm ở Stage E.
  - [ADR 0006](../decisions/0006-gradient-boosting-sklearn.md): Gradient Boosting của scikit-learn.
  - Baseline đã chốt: `projects/fraud-risk/configs/baseline.yaml`, lần chạy test `run-d6faa4699008`.

## 1. Mục tiêu

1. **Đo giá của từng kiểu rò rỉ dữ liệu.** Lấy đúng mô hình Logistic Regression của Stage B, mỗi lần phá **một** quy tắc, và xem điểm trên validation thay đổi bao nhiêu. Đây là bằng chứng cho các quy tắc đã đặt từ đầu dự án.
2. **Đo độ nhạy với độ trễ nhãn và thực thể lặp lại** (ADR 0003).
3. **Một mô hình mạnh hơn baseline:** Gradient Boosting, cùng dữ liệu, cùng cách chia và cùng đặc trưng, nên khác biệt chỉ đến từ mô hình.

## 2. Phạm vi

**Trong phạm vi**
- `gap_days` cho `time_split`, kèm test.
- `fraud_risk/evaluation/entity_overlap.py`, `fraud_risk/features/target_encoding.py`.
- `fraud_risk/experiments/leakage.py` và `configs/leakage.yaml`, lệnh `make leakage`.
- `fraud_risk/models/gbm.py`, `fraud_risk/scripts/run_gbm.py` và `configs/gbm.yaml`, lệnh `make gbm` và `make gbm-final`.

**Ngoài phạm vi**
- **API chấm điểm**: cắt (chủ dự án quyết định 2026-11-04, khi tuần 5 thiếu thời gian thì cắt API trước).
- Thư viện mới (LightGBM, XGBoost, SHAP, MLflow).
- Đặc trưng mới ngoài danh sách đã duyệt trong `eda-summary.md`. Mã hoá `card1` chỉ xuất hiện **trong thí nghiệm rò rỉ**, không đưa vào mô hình chính.
- Bảng identity (quyết định EDA #1 giữ tắt).

## 3. Khoảng trống thời gian (`gap_days`)

- Bỏ các dòng train trong N ngày cuối trước validation. Mô phỏng việc khi chấm điểm, nhãn của các giao dịch gần đây chưa có (chargeback đến muộn).
- **Validation và test giữ nguyên**, nên kết quả có và không có khoảng trống được so trên cùng các dòng.
- `gap_days = 0` không thêm khoá nào vào mốc split, nên mã lần chạy của baseline đã chốt không đổi (D6).
- Giá trị 7 và 14 ngày là **phân tích độ nhạy**, không phải "giá trị đúng" (ADR 0003).

## 4. Thí nghiệm rò rỉ (`make leakage`)

Mô hình luôn là Logistic Regression của baseline. Mọi biến thể chấm điểm trên **validation**. Không dòng test nào được chấm điểm, không nhãn test nào được đọc (có test kiểm tra: đổi nhãn test không đổi kết quả).

| Biến thể | Phá quy tắc nào | Kỳ vọng |
| --- | --- | --- |
| `proper` | Không (baseline Stage B) | Mốc so sánh |
| `random_split` | Quy tắc 7: chia theo thời gian | Điểm cao hơn nếu dữ liệu đổi theo thời gian, vì validation trộn lẫn với train |
| `preprocess_on_all` | Quy tắc 8: chỉ fit trên train | Gần như không đổi với mô hình này; cho thấy không phải rò rỉ nào cũng lớn |
| `target_enc_train` | Không: mã hoá `card1` bằng nhãn train, ngoài fold trên chính train | Đo giá trị thật của định danh thẻ |
| `target_enc_leaky` | Quy tắc 6: nhãn tách khỏi input. Mã hoá bằng nhãn train **và validation** | Điểm tăng rất mạnh: nhãn được chép thẳng vào đặc trưng |
| `gap_7d`, `gap_14d` | Không: độ trễ nhãn (ADR 0003) | Điểm giảm nhẹ nếu hành vi gian lận thay đổi nhanh |

Kèm bảng **thực thể lặp lại** (chỉ mô tả): tỷ lệ dòng validation và test có `card1`, và có `card1` + `addr1` + `P_emaildomain`, đã xuất hiện trong train. Tỷ lệ gian lận của nhóm "đã gặp" và "mới" chỉ tính trên validation. Tổ hợp 3 cột là heuristic phổ biến trong các notebook công khai của cuộc thi; báo cáo ghi rõ nguồn ý tưởng, không sao chép code (quy tắc 13).

Phân loại các kiểu rò rỉ theo Kapoor và Narayanan (2023); định nghĩa theo Kaufman và cộng sự (2012) (tổng quan, tài liệu 4 và 5).

## 5. Gradient Boosting (`make gbm`)

- `HistGradientBoostingClassifier` của scikit-learn (ADR 0006), `class_weight='balanced'` (quyết định EDA #4).
- Biến phân loại mã hoá thứ tự, fit trên train; giá trị chưa gặp thành giá trị thiếu. Không cần scaling hay điền thiếu.
- **Tắt `early_stopping`**: phần validation nội bộ của nó chia ngẫu nhiên, trái quy tắc 7.
- Lưới 8 tổ hợp (`learning_rate` 0,05 / 0,1; `max_iter` 200 / 400; `max_leaf_nodes` 15 / 31). Mỗi tổ hợp fit trên train; chọn tổ hợp có PR-AUC validation cao nhất; chọn ngưỡng trên validation (tối đa F1, như baseline).
- Run log giống Stage B: `config.yaml`, `metrics.json`, `split.json`, `threshold.json`, `models.json` (có cả kết quả lưới), `environment.txt`, `git_sha.txt`, checksum manifest.

## 6. Đăng ký trước các lần chạy test

Chỉ **một** config Stage E được chạy trên tập test, **một lần**:

| Config | Lý do |
| --- | --- |
| `configs/gbm.yaml` (`gap_days: 0`), sau khi chủ dự án đặt `status: frozen` | So sánh trực tiếp với Logistic Regression đã chạy test (`run-d6faa4699008`) |

Mọi biến thể khác (rò rỉ, khoảng trống, các điểm của lưới) **chỉ dùng validation**. Nếu sau khi xem kết quả test mà muốn chạy test thêm một config, đó phải là config mới và được ghi rõ trong báo cáo.

## 7. Lệnh Makefile mới

| Lệnh | Việc |
| --- | --- |
| `make leakage` | Thí nghiệm rò rỉ, ghi `artifacts/experiments/leak-<hash>/` (`results.json`, `summary.md`) |
| `make gbm` | Gradient Boosting, train và validation |
| `make gbm-final` | Đánh giá test một lần cho `gbm.yaml` đã `frozen` (chỉ chủ dự án chạy) |

## 8. Task và tiêu chí nghiệm thu

| ID | Task | Tiêu chí nghiệm thu |
| --- | --- | --- |
| E01 | `gap_days` | Dòng train trong khoảng trống bị bỏ, validation và test không đổi; `gap_days = 0` giữ nguyên mốc split của Stage B; giá trị âm bị từ chối |
| E02 | Thực thể lặp lại, mã hoá theo nhãn | Khớp ví dụ tính tay; không đọc nhãn test; mã hoá ngoài fold không dùng nhãn của chính dòng đó |
| E03 | Thí nghiệm rò rỉ | Mọi biến thể chấm điểm trên cùng số dòng validation; đổi nhãn test không đổi kết quả; biến thể rò rỉ thật sự làm điểm tăng trên fixture; test T10 chỉ cho phép `random_split` trong `split.py` và file thí nghiệm này |
| E04 | Gradient Boosting | Fit trên train; chọn trên validation; hai lần chạy cho `metrics.json` giống hệt; `gbm-final` từ chối config `draft` và từ chối chạy lại cùng hash |
| E05 | Báo cáo | `docs/architecture/stage-e-report.md` có số thật từ run id, sau khi chủ dự án chạy trên dữ liệu thật |

## 9. Quyết định (đề xuất của agent, áp dụng theo uỷ quyền ngày 2026-11-04)

| # | Câu hỏi | Quyết định | Lý do |
| --- | --- | --- | --- |
| E-Q1 | Thư viện Gradient Boosting | `HistGradientBoostingClassifier` của scikit-learn | Không thêm thư viện; tự xử lý giá trị thiếu và biến phân loại; đủ nhanh với 354 nghìn dòng. LightGBM hay XGBoost thường nhỉnh hơn một chút nhưng thêm phụ thuộc (ADR 0006) |
| E-Q2 | Đặc trưng của Gradient Boosting | Giống hệt baseline | Để khác biệt với Logistic Regression chỉ đến từ mô hình. Thêm đặc trưng là một bước riêng, cần quyết định EDA mới |
| E-Q3 | Dùng tập test cho config nào | Chỉ `gbm.yaml`, một lần | Mỗi lần mở test lại làm số trên test kém tin cậy; thí nghiệm rò rỉ và độ nhạy không cần test để rút ra kết luận |
| E-Q4 | Khoảng trống thực hiện thế nào | Bỏ cuối train, giữ nguyên validation và test | Tập đánh giá không đổi, nên so sánh được |
| E-Q5 | Mô hình dùng trong thí nghiệm rò rỉ | Logistic Regression của baseline | Nhanh, đã có số test, nên chỉ có một yếu tố thay đổi |
| E-Q6 | Mã hoá `card1` trên chính train | Ngoài fold, 5 khối liên tiếp theo thời gian | Mã hoá một dòng bằng nhãn của chính nó là rò rỉ nhỏ trong train: trên fixture, nó làm điểm *giảm* từ 0,168 xuống 0,078 vì mô hình tin quá mức vào đặc trưng; ngoài fold cho 0,166 |
| E-Q7 | API chấm điểm | Cắt | Quyết định của chủ dự án |
