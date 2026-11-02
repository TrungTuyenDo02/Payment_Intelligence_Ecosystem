# EDA summary: quyết định tiền xử lý (IEEE-CIS)

> Agent chỉ được đề xuất (`proposed`). Chỉ chủ dự án đổi trạng thái thành `approved` hoặc `rejected` (AGENTS.md, quy tắc 12 và 14).
> Mọi số liệu dùng để quyết định phải lấy từ **partition train** (chạy `make eda`, bảng nằm trong `artifacts/eda/`, không commit).
> Bảng `01_fraud_rate_by_week_descriptive_only_all_data.csv` chỉ để mô tả, **không** được dùng làm bằng chứng cho quyết định.
> Chỉ chép vào đây các số tổng hợp tối thiểu làm bằng chứng (điều khoản giấy phép Kaggle chưa được kiểm tra).

**Trạng thái hiện tại:** các bảng mới chỉ được chạy trên fixture tổng hợp, chưa chạy trên dữ liệu thật. Cột "Bằng chứng" ghi tên bảng; chủ dự án điền số liệu thật sau khi chạy `make eda` trên máy mình.

| # | Quyết định | Bằng chứng (bảng / hình) | Phương án khác đã cân nhắc | Trạng thái |
| --- | --- | --- | --- | --- |
| 1 | Không join bảng identity ở baseline (giữ mặc định tắt) | `02_identity_effect.csv` (tỷ lệ dòng có identity, fraud rate có/không có identity; chạy `make eda` với `--with-identity`) | Join và thêm cờ `has_identity` | proposed |
| 2 | Cột số: điền thiếu bằng median (fit trên train) | `02_missing_by_column.csv` (missing_rate, chênh lệch fraud và non-fraud) | Thêm cờ `is_missing` cho cột có chênh lệch missing lớn giữa hai lớp | proposed |
| 3 | Không dùng các nhóm cột V có tỷ lệ thiếu cao ở baseline | `02_missing_groups.csv` (các nhóm cột thiếu cùng nhau) | Lấy một cột đại diện cho mỗi nhóm | proposed |
| 4 | Dùng `class_weight='balanced'` cho Logistic Regression | `03_class_balance_summary.csv` (fraud_rate, trọng số balanced), `03_class_balance_by_week.csv`, `03_fraud_rate_by_week_train.png` | Không cân bằng, chỉ chọn ngưỡng trên validation; undersampling | proposed |
| 5 | Thêm `log1p(TransactionAmt)` bên cạnh giá trị gốc | `04_distributions.csv` (skew_raw so với skew_log1p), `04_transaction_amt_raw_vs_log.png` | Cắt (clip) tại q99 của train | proposed |
| 6 | Biến phân loại: one-hot cho `ProductCD`, `card4`, `card6`; giá trị chưa gặp thì bỏ qua (`handle_unknown='ignore'`) | `05_categorical_summary.csv` (n_unique, rare_rows_share) | Gộp các giá trị hiếm (<1% số dòng train) thành `other` | proposed |
| 7 | Không dùng `P_emaildomain`, `R_emaildomain` ở baseline (nhiều giá trị) | `05_categorical_summary.csv`, `05_categorical_values.csv` | Gộp giá trị hiếm rồi one-hot | proposed |
| 8 | Loại `TransactionID` và `TransactionDT` gốc khỏi features; chỉ dùng giờ trong ngày suy ra từ `TransactionDT` | `06_leakage_candidates.csv` (unique_per_row, encodes_time_or_order) | Giữ `TransactionDT` dạng số (mã hoá thứ tự thời gian, không tồn tại đúng nghĩa lúc scoring) | proposed |
| 9 | Rà soát tay mọi cột khác trong `06_leakage_candidates.csv` trước khi đưa vào features | `06_leakage_candidates.csv`, `06_column_checks.csv` | Loại tự động theo ngưỡng (không làm: agent không được tự loại cột) | proposed |

## Ghi chú cho chủ dự án

- `single_column_auc_in_sample` của cột phân loại được target-encode trên chính các dòng train, nên số này lạc quan. Chỉ dùng nó để tìm cột đáng nghi, không dùng để chọn feature.
- Nếu có dòng nào được duyệt làm thay đổi danh sách feature, chỉ sửa config `projects/fraud-risk/configs/baseline.yaml`. Đó là một config mới, nên sẽ ra `run_id` mới.
