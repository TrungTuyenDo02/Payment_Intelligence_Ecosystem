# EDA summary: quyết định tiền xử lý (IEEE-CIS)

> Agent chỉ được đề xuất (`proposed`). Chỉ chủ dự án đổi trạng thái thành `approved` hoặc `rejected` (AGENTS.md, quy tắc 12 và 14).
> Mọi số liệu dùng để quyết định phải lấy từ **partition train** (chạy `make eda`, bảng nằm trong `artifacts/eda/`, không commit).
> Bảng `01_fraud_rate_by_week_descriptive_only_all_data.csv` chỉ để mô tả, **không** được dùng làm bằng chứng cho quyết định.
> Chỉ chép vào đây các số tổng hợp tối thiểu làm bằng chứng (điều khoản giấy phép Kaggle chưa được kiểm tra).

**Trạng thái hiện tại:** đã chạy `make eda` trên dữ liệu thật ngày 2026-11-03 (manifest checksum `f7320fa9…`, partition train 354.324 dòng / 392 cột, split 60/20/20 theo thời gian). Quyết định #1 dùng thêm lần chạy `--with-identity` (bảng trong `artifacts/eda-identity/`). Chủ dự án duyệt cả 9 dòng trong chat ngày 2026-11-03; agent chỉ ghi lại quyết định đó.

| # | Quyết định | Bằng chứng (bảng / hình) | Phương án khác đã cân nhắc | Trạng thái |
| --- | --- | --- | --- | --- |
| 1 | Không join bảng identity ở baseline (giữ mặc định tắt) | `02_identity_effect.csv` (`--with-identity`): 27,5% dòng train có identity; fraud rate 6,73% khi có, 2,12% khi không | Join và thêm cờ `has_identity` (bằng chứng cho thấy đây là tín hiệu mạnh; để dành cho giai đoạn sau) | approved (chủ dự án, 2026-11-03) |
| 2 | Cột số: điền thiếu bằng median (fit trên train) | `02_missing_by_column.csv`: feature baseline chỉ có `card4`, `card6` thiếu 0,23%, chênh lệch fraud/non-fraud < 0,04 điểm %; các cột khác không thiếu | Thêm cờ `is_missing` cho cột có chênh lệch missing lớn giữa hai lớp (các cột D chênh 20–25 điểm % nhưng không nằm trong baseline) | approved (chủ dự án, 2026-11-03) |
| 3 | Không dùng các nhóm cột V có tỷ lệ thiếu cao ở baseline | `02_missing_groups.csv`: 17 nhóm thiếu cùng nhau, nhiều nhóm V thiếu 73–83%; 190 cột thiếu > 50% | Lấy một cột đại diện cho mỗi nhóm | approved (chủ dự án, 2026-11-03) |
| 4 | Dùng `class_weight='balanced'` cho Logistic Regression | `03_class_balance_summary.csv`: fraud rate 3,38% (1 : 28,6), trọng số 14,78 / 0,52; `03_class_balance_by_week.csv`, `03_fraud_rate_by_week_train.png`: theo tuần 1,85%–4,55% | Không cân bằng, chỉ chọn ngưỡng trên validation; undersampling | approved (chủ dự án, 2026-11-03) |
| 5 | Thêm `log1p(TransactionAmt)` bên cạnh giá trị gốc | `04_distributions.csv`: skew 19,44 → 0,50 sau `log1p`; trung vị 70, q99 1.092, max 31.937; `04_transaction_amt_raw_vs_log.png` | Cắt (clip) tại q99 của train | approved (chủ dự án, 2026-11-03) |
| 6 | Biến phân loại: one-hot cho `ProductCD`, `card4`, `card6`; giá trị chưa gặp thì bỏ qua (`handle_unknown='ignore'`) | `05_categorical_summary.csv`: 5 / 4 / 4 giá trị, thiếu ≤ 0,23%; `05_categorical_values.csv`: fraud rate `ProductCD` từ 2,0% (W) đến 10,7% (C), `card6` credit 6,3% so với debit 2,3% | Gộp các giá trị hiếm (<1% số dòng train) thành `other` | approved (chủ dự án, 2026-11-03) |
| 7 | Không dùng `P_emaildomain`, `R_emaildomain` ở baseline (nhiều giá trị) | `05_categorical_summary.csv`: 59 / 60 giá trị, thiếu 16% / 74%; `05_categorical_values.csv`: có tín hiệu (hotmail 5,2%, gmail 4,2%, yahoo 2,3%) | Gộp giá trị hiếm rồi one-hot | approved (chủ dự án, 2026-11-03) |
| 8 | Loại `TransactionID` và `TransactionDT` gốc khỏi features; chỉ dùng giờ trong ngày suy ra từ `TransactionDT` | `06_leakage_candidates.csv`: chỉ hai cột này bị gắn cờ (`encodes_time_or_order`, Spearman với thời gian = 1) | Giữ `TransactionDT` dạng số (mã hoá thứ tự thời gian, không tồn tại đúng nghĩa lúc scoring) | approved (chủ dự án, 2026-11-03) |
| 9 | Rà soát tay mọi cột khác trong `06_leakage_candidates.csv` trước khi đưa vào features | `06_column_checks.csv`: AUC một cột cao nhất 0,68 (`C4`, in-sample, lạc quan); không cột nào gần như trùng nhãn | Loại tự động theo ngưỡng (không làm: agent không được tự loại cột) | approved (chủ dự án, 2026-11-03) |

## Ghi chú cho chủ dự án

- `single_column_auc_in_sample` của cột phân loại được target-encode trên chính các dòng train, nên số này lạc quan. Chỉ dùng nó để tìm cột đáng nghi, không dùng để chọn feature.
- Nếu có dòng nào được duyệt làm thay đổi danh sách feature, chỉ sửa config `projects/fraud-risk/configs/baseline.yaml`. Đó là một config mới, nên sẽ ra `run_id` mới.
