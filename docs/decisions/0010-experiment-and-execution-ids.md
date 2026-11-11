# ADR 0010 — Tách mã cấu hình và mã lần chạy; CI bảo vệ sổ test-một-lần

- **Trạng thái:** Accepted (chủ dự án duyệt trong chat ngày 2026-11-11; xem mục "Quyết định của chủ dự án")
- **Phạm vi:** `fraud_risk/evaluation/run_log.py`, các runner (`run_baseline`, `run_gbm`, `leakage`, `split_diagnostics`, Stage G), `detect-report` của Product 01, `.github/workflows/ci.yml`, `Makefile`

## Bối cảnh

1. **Một mã đang làm hai việc.** `compute_run_hash` (config trừ `status`, seed, checksum dataset, mốc chia) vừa là tên thư mục kết quả (`run-…`, `cal-…`) vừa là khoá của sổ test-một-lần. Vì vậy nó cố ý không chứa phiên bản thư viện hay commit: nếu chứa, nâng thư viện sẽ sinh mã mới và mở lại tập test. Hệ quả là hai lần chạy cùng config trên hai môi trường khác nhau ghi đè cùng một thư mục, và không phân biệt được. Đã quan sát chênh ±0,001 ở thí nghiệm rò rỉ giữa hai máy.
2. **CI bỏ qua test database.** CI không có PostgreSQL, nên 7 test database tự bỏ qua (máy hiện tại cũng vậy: 8 skip).
3. **Sổ test-một-lần chỉ được bảo vệ bằng quy ước.** Một PR có thể xoá dòng trong `artifacts/test_runs.json` hay `artifacts/detect_report_runs.json`, hoặc thêm dòng `"forced": true`, mà CI không báo gì.
4. **Kết quả không có trong git.** `artifacts/` bị git-ignore. Máy không có lần chạy thì `make dashboard` sinh trang rỗng mà không báo lỗi.

## Phương án

| Phương án | Ưu điểm | Nhược điểm |
| --- | --- | --- |
| **A. Giữ nguyên công thức hiện tại làm `experiment_id`; thêm `execution_id` riêng cho mỗi lần chạy** | Mọi mã cũ (`run-f8807cb6f780`, …) và mọi dòng trong sổ vẫn đúng; không mở lại test | Thêm một file mỗi lần chạy |
| B. Đổi công thức hash (thêm phiên bản thư viện) | Một mã duy nhất | Mọi mã cũ đổi, sổ mất tác dụng; vi phạm quy tắc 3 |
| C. Không làm | Không tốn công | Giữ nguyên bốn vấn đề ở trên |

## Quyết định (phương án A)

**1. Hai mã**

- `experiment_id` = mã hiện tại, **công thức giữ nguyên từng byte** (có test hồi quy: config `gbm.yaml` với mốc chia đã biết phải ra đúng `f8807cb6f780…`). Đây là tên thư mục kết quả và là khoá test-một-lần, như cũ.
- `execution_id` = `exec-` + 12 ký tự đầu của SHA-256(`experiment_id`, thời điểm bắt đầu UTC, commit, nội dung `environment.txt`). Mỗi lần chạy có một mã mới; mã này **không bao giờ** được dùng làm khoá.
- Mỗi lần chạy ghi thêm `executions/<execution_id>.json` trong thư mục kết quả: thời điểm bắt đầu/kết thúc, commit (kèm `-dirty`), phiên bản Python và thư viện, nền tảng, và băm SHA-256 của các file kết quả. File `metrics.json` / `results.json` ở gốc thư mục vẫn là của lần chạy gần nhất (như hiện nay). So hai lần chạy thì so hai file `executions/…`.
- Dòng mới trong sổ test-một-lần có thêm trường `execution_id`. Dòng cũ giữ nguyên.

**2. CI có PostgreSQL thật**

- Thêm service `postgres:16` vào `ci.yml`, đặt `POSTGRES_*` khớp `compose.yaml`.
- Thêm biến `REQUIRE_DB=1` trong CI: khi có biến này, test database **thất bại** thay vì bỏ qua nếu không kết nối được. Trên máy cá nhân không đặt biến này, nên hành vi cũ (bỏ qua) giữ nguyên.

**3. CI bảo vệ hai sổ**

- Script `scripts/check_registries.py` (chỉ dùng thư viện chuẩn) so mỗi sổ ở PR với bản ở nhánh đích của PR (`git show origin/<nhánh đích>:<sổ>`; push vào `main` thì so với commit trước). Script báo lỗi nếu: (a) một dòng cũ bị xoá hoặc bị sửa (so theo `hash`); (b) có dòng mới mang `"forced": true`; (c) file không phải JSON hợp lệ. Checkout cần `fetch-depth: 0`.
- Ngoại lệ (nếu chủ dự án cố ý `--force`): chủ dự án ghi lý do trong PR và tạm bỏ qua bước này. Đề xuất **không** tự động hoá ngoại lệ.

**4. Gói kết quả nhỏ có thể commit**

- `make bundle RUN_DIR=<thư mục>` chép vào `results/<experiment_id>/` các file nhỏ: `config.yaml`, `metrics.json` hoặc `results.json`, `split.json`, `summary.md`, `environment.txt`, `git_sha.txt`, `executions/*.json`. Không chép dataset, Parquet, mô hình hay dự đoán theo dòng. Giới hạn 1 MB mỗi gói, vượt thì báo lỗi.
- Agent chỉ đóng gói lần chạy train/validation (`cal-…`, `pol-…`, `stab-…`, `leak-…`, phần validation của `run-…`). **Gói của phần test** (`artifacts/runs/*/test/`) do chủ dự án tự chạy, vì agent không được đọc thư mục đó.

**5. `make verify-demo`**

- Kiểm tra trước khi sinh dashboard: có `artifacts/runs/`, có ít nhất một lần chạy Product 02, có một thư mục detector của Product 01. Thiếu thứ gì thì in rõ thiếu gì, cách lấy (lệnh `make …` hoặc chép từ máy chủ dự án, xem HANDOFF), và thoát mã khác 0. `make dashboard` giữ hành vi hiện tại (vẫn sinh trang có ô "Chưa có lần chạy").

## Hệ quả

- Không thêm thư viện. Không đổi config `frozen`, không chạy `*-final`, không đổi dòng cũ nào trong sổ.
- Mọi mã lần chạy đã công bố giữ nguyên.
- CI chậm hơn một chút (khởi động PostgreSQL).

## Quyết định của chủ dự án (2026-11-11)

1. **Chọn A.** Giữ nguyên công thức hiện tại làm `experiment_id`; thêm `execution_id` cho từng lần chạy. `execution_id` chỉ dùng để truy vết, không bao giờ là khoá test-một-lần.
2. **Gói kết quả đặt ở `results/` tại gốc repo**, tách khỏi `docs/` (tài liệu). Chỉ chứa config, metric, split, summary, môi trường, commit và thông tin lần chạy; không chứa dataset, Parquet, mô hình hay dự đoán từng dòng.
3. **Kiểm tra sổ chạy trên mọi PR**, không chỉ PR vào `main`: các nhánh Stage G xếp chồng, nên một nhánh trung gian có thể xoá dòng hoặc thêm `"forced": true` rồi đi tiếp qua các PR sau. Bản đối chiếu là nhánh đích của PR.
4. **Agent không gói kết quả test.** Nếu cần, chủ dự án tự chạy `make bundle` trên máy có `artifacts/runs/*/test/` sau khi xem nội dung.
