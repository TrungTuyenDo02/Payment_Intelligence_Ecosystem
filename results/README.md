# Gói kết quả nhỏ (ADR 0010)

Thư mục này chứa bản chép **các file tóm tắt** của từng lần chạy, để kết quả có trong git dù `artifacts/` bị git-ignore.

- Tạo bằng `make bundle RUN_DIR=artifacts/experiments/<mã>` (hoặc `artifacts/runs/<mã>`). Mỗi gói nằm ở `results/<experiment_id>/`, tối đa 1 MB.
- Chỉ chép: `config.yaml`, `metrics.json` / `results.json` / `evaluation.json`, `split.json`, `threshold.json`, `models.json`, `summary.md`, `environment.txt`, `git_sha.txt`, `manifest_checksum.txt`, `executions/*.json`.
- **Không** chép dataset, Parquet, mô hình, hình hay dự đoán theo dòng. Không đọc thư mục con (`test/`).
- Thư mục `test/` (Product 02) và `report/` (Product 01) chứa kết quả đánh giá một lần: **chỉ chủ dự án** đóng gói, bằng `OWNER_TEST=1`. Agent không đóng gói và không đọc chúng.

Hai mã (ADR 0010):

- `experiment_id` (tên thư mục, ví dụ `cal-04b3ad5944ce`): băm config, seed, checksum dataset và mốc chia. Không đổi khi nâng thư viện. Đây là khoá của sổ test-một-lần.
- `execution_id` (`executions/exec-….json`): mỗi lần chạy một mã, ghi thời điểm, commit, môi trường và băm SHA-256 của các file kết quả. Hai lần chạy cùng `experiment_id` cho `results.json` cùng băm nghĩa là kết quả trùng từng byte.
