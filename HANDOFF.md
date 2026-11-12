# Bàn giao công việc — 2026-11-12

> Dành cho người tiếp tục dự án từ ngày 2026-11-05. Đọc file này trước, sau đó đọc [`README.md`](README.md) và [tổng quan đề tài](docs/product/project-overview.md).
> Chủ dự án: Đỗ Trung Tuyến (@TrungTuyenDo02).

## 000. Cập nhật 2026-11-12: G08, `make demo`, G09 (đọc trước)

| Việc | Nhánh, commit | Kiểm chứng |
| --- | --- | --- |
| G08 bộ chấm điểm theo lô | `stage-g/g08-batch-scoring` (`7ab81f6`) | `make score-model` → `score-19e94be9616d` (chạy hai lần, file trùng từng byte); `make score` trên 2.000 dòng V3: lệch huấn luyện–chấm điểm 0; tham số Platt trùng G03; 10 test mới; phá hoại có chủ đích (lệch `hour_of_day` 7 giờ) bị 2 test bắt |
| `make demo` (Product 01 đầu-cuối) | `stage-g/g08b-demo` (`4beab1c`) | Chỉ dùng bộ tuning; `scripts/check_demo.py` so với số đã công bố (D-B 3/4, 0 báo nhầm/ngày; D-A 2/4, 1,0). **Chưa chạy đầu-cuối trên máy này** (không có Docker/PostgreSQL); job `demo` trong CI chạy nó trên PostgreSQL 16 |
| `make demo` dễ hiểu hơn (sau khi chủ dự án chạy thử không thấy kết quả) | `stage-g/g08c-demo-ux` | `scripts/demo.py`: kiểm tra PostgreSQL trước và in hướng dẫn nếu thiếu (trước đây là traceback sau 12 giây); in 7 bước kèm nơi ghi kết quả; [hướng dẫn demo](docs/demo-guide.md); bỏ cảnh báo `VIRTUAL_ENV` trên Windows; `make up` báo rõ khi thiếu Docker. **Đã chạy thật 2026-11-12** sau khi chủ dự án cài Docker Desktop: `make up` → `make demo` qua đủ 7 bước, D-B 3/4 và 0 báo nhầm/ngày, D-A 2/4 và 1,0, khớp số công bố; chạy lần hai: 0 dòng mới, 30.050 dòng đã có. `make test` với PostgreSQL: **454 pass, 1 skip** (7 test DB chạy thật) |
| G09 đồng bộ tài liệu | `stage-g/g09-docs` | README (demo 5 phút, Stage G, ADR 0001–0010), overview, dàn ý, báo cáo thực tập có mục 4.6 Stage G (PDF **25 trang**, đã xem các trang mới), báo cáo tuần [`docs/weekly/`](docs/weekly/) |

`make test` sau G08: **439 pass, 8 skip**; sau `make demo`: thêm 4 test (`tests/test_check_demo.py`).

Việc tiếp theo:

1. Push ba nhánh mới, mở PR xếp chồng: G08 → G07, `g08b-demo` → G08, G09 → `g08b-demo`. Xác nhận CI xanh: `lint and test` (PostgreSQL, `REQUIRE_DB=1`), `registries`, `demo`.
2. ADR 0002 đã Accepted (chủ dự án chấp nhận trong chat 2026-11-12).
3. Dashboard trên máy mới thiếu số test của Product 02: chép `artifacts/runs/run-f8807cb6f780/test/` từ máy chủ dự án, hoặc chủ dự án chạy `make bundle RUN_DIR=artifacts/runs/run-f8807cb6f780 OWNER_TEST=1` rồi commit. Agent không đọc thư mục test.
4. G10 ⏸: chủ dự án đồng ý lên kế hoạch (2026-11-12). Đặc tả nháp [`stage-g10-spec.md`](docs/architecture/stage-g10-spec.md) trên nhánh `stage-g/g10-spec`, **chờ duyệt D1–D9** trước khi viết code (đặc biệt D1: không tăng `GENERATOR_VERSION`, và D2: nơi chạy phần cần PostgreSQL).

## 00. Cập nhật 2026-11-11: Stage G

Stage G: từ xếp hạng đến quyết định, **chỉ trên train + validation (thăm dò)**. Hướng dẫn thường trực cho agent nằm trong `CLAUDE.md` (bị git-ignore, chỉ có trên máy này). Tập test không được mở; không config `frozen` nào bị sửa.

### Đã làm (mỗi task một nhánh, xếp chồng: g01 → g02 → … → g07; đã push đến G07 ngày 2026-11-12)

| Task | Nhánh, commit | Kiểm chứng |
| --- | --- | --- |
| G00 mốc | — | `make lint` pass; `make test` 381 pass, 8 skip (7 test DB vì máy không có Docker, 1 hook); checksum manifest khớp |
| G01 đặc tả + ADR 0009 | `stage-g/g01-protocol` (`e2f962b`) | Chủ dự án duyệt D1–D8, ADR 0009 Accepted (chat 2026-11-11) |
| G02 tách hai bảng metric | `stage-g/g02-metric-presentation` (`dba37f6`) | README (thêm bảng "không phải production"), báo cáo Stage E, LaTeX + 2 PDF (23 và 10 trang, đã xem trang có bảng mới), dàn ý, dashboard (+2 test). Không chạy `make dashboard` vì lệnh đó đọc `artifacts/runs/*/test/` |
| G03 hiệu chỉnh | `stage-g/g03-calibration` (`50d01de`) | `make calibration` → `cal-04b3ad5944ce`; 13 test |
| G04 chính sách | `stage-g/g04-policy` (`fb53035`) | `make policy` → `pol-af5df43efe54`; 10 test |
| G05 độ ổn định | `stage-g/g05-stability` (`ed54347`) | `make stability` → `stab-36887d48b356`; 8 test |
| G06 báo cáo | `stage-g/g06-report` (`82705cb`) | [`stage-g-report.md`](docs/architecture/stage-g-report.md): mọi số kèm mã lần chạy và commit |
| G07 đóng gói | `stage-g/g07-packaging` | [ADR 0010](docs/decisions/0010-experiment-and-execution-ids.md) Accepted (chat 2026-11-11). `execution_id` cho mọi runner (cả `detect-report`); test hồi quy: `gbm.yaml`/`baseline.yaml` vẫn ra `f8807cb6f780…`/`d6faa4699008…`; CI có PostgreSQL + `REQUIRE_DB=1` và job kiểm tra sổ; `make bundle`, `make verify-demo`; gói `results/` cho cal/pol/stab. **CI chưa chạy** (chưa push) |

`make test` sau G05: 414 pass, 8 skip; sau G07: **429 pass, 8 skip** (vẫn 7 test DB bỏ qua trên máy này; với `REQUIRE_DB=1` chúng báo lỗi, như CI sẽ làm). Mỗi lệnh Stage G chạy ít nhất ba lần, `results.json` trùng từng byte. Tự kiểm tra (đảo nhãn, đổi dòng test, phá hoại có chủ đích, tính lại bằng vòng lặp thuần) ghi trong báo cáo Stage G.

### Kết quả chính (thăm dò, dữ liệu phát triển)

- Điểm gốc của GBM gấp khoảng 7 lần tỷ lệ gian lận thật; dịch tiên nghiệm hoặc Platt sửa được phần lớn.
- Luật chi phí theo số tiền, dùng xác suất đã hiệu chỉnh, có chi phí thấp nhất ở 27/27 tổ hợp chi phí giả định (phân tích độ nhạy, không phải ROI).
- PR-AUC theo tuần validation dao động 0,35–0,56; PSI của 4 đầu vào không giải thích được.

### Việc tiếp theo

1. **Push và mở PR**: chủ dự án chọn một PR cho mỗi task, xếp chồng (G01 → `main`, G02 → G01, …, G07 → G06), merge từ dưới lên, sau mỗi lần merge đổi đích của PR kế tiếp sang `main`. Cần `gh auth login` để mở PR bằng CLI.
2. G07 chỉ xong khi CI xanh với test DB chạy thật (job `lint and test` có PostgreSQL) và job `registries` pass.
3. Máy này thiếu lần chạy detector của Product 01 (`make verify-demo` báo thiếu `detections/det-*`).
4. Kế tiếp: G08 (chấm điểm theo lô, dùng `execution_id`); G09; G10 ⏸.
5. ~~Lệch tài liệu: HANDOFF ghi PDF báo cáo 19–20 trang, thực tế 23 trang.~~ Đã sửa ở G09 (nay 25 trang).

## 0. Cập nhật 2026-11-09 (đọc trước)

### Đã làm

| Việc | Ở đâu | Kiểm chứng |
| --- | --- | --- |
| Điền số Stage E (rò rỉ, Gradient Boosting test 0,408) vào báo cáo thực tập, bài báo, README, dàn ý; build lại 2 PDF | `docs/report/`, `README.md` | PDF 19 và 10 trang, đã xem các trang có bảng mới |
| Sơ đồ: E và F chuyển sang "Đã xong" | `docs/assets/diagrams/`, `docs/report/latex/figures/` | Xuất lại SVG và PNG |
| Tái lập trên máy Windows/WSL này: `make baseline`, `make leakage`, `make gbm`, `make simulate` (2 config), `ingest`, `kpi`, `detect` | — | Ra đúng mọi run id cũ. Số khớp, trừ thí nghiệm rò rỉ lệch ±0,001 ở 3 dòng (phiên bản thư viện khác) |
| Thí nghiệm mới, **chỉ validation**: 3 đặc trưng lịch sử thực thể (chỉ dùng giao dịch trước, không dùng nhãn) | `baseline_features.py` (`_history`), `configs/gbm-history-*.yaml`, [báo cáo Stage E mục 3b](docs/architecture/stage-e-report.md) | Không cải thiện: 0,497 / 0,499 so với 0,497. Hai config là `draft`, **không** chạy test |
| Dashboard: gộp cảnh báo `ALL` trùng thời gian với cảnh báo provider (cột "Gộp ALL") | `shared/dashboard/dashboard/build.py` (`fold_echoes`) | Bộ tuning: 8 sự cố thô còn 5. Chỉ đổi phần hiển thị; `incidents.json` và đánh giá không đổi |
| **Sửa lỗi** dashboard crash `KeyError: 'recall_at_fpr'` khi có lần chạy cũ (`run-515a1190a0a4`) | `build.py`, test `test_fraud_table_…` | Code cũ crash trên dữ liệu thật; code mới chạy |
| **Sửa lỗi** bảng Product 02 của dashboard: số validation hiện 2 lần, 3 biến thể Gradient Boosting không phân biệt được, Test đứng trước Validation, bảng rò rỉ hiện markdown thô | `build.py` | Bảng từ 15 dòng còn 7; có cột "Số đặc trưng" |
| **Sửa lỗi** hook `commit-msg` không chạy trong WSL (`Syntax error: "\|" unexpected`) do CRLF khi checkout trên Windows | `.gitattributes` | Test hook pass trong WSL |
| **Sửa lỗ hổng** quy tắc test-một-lần: sổ đăng ký chỉ nằm trên từng máy, nên máy này đã có thể chạy lại `gbm-final` và `detect-report` | `.gitignore` cho phép 2 file sổ; sổ đã ghi `run-f8807cb6f780` và `det-08335c6af086` | `make detect-report` giờ bị chặn ("already evaluated") |
| **Sửa lỗi** môi trường: `uv` trên Windows xoá `.venv` của WSL (hai môi trường dùng chung thư mục) | `Makefile`: trên Windows dùng `.venv-win` | `make` trên Windows tạo `.venv-win`, `.venv` WSL nguyên vẹn |
| Cổng 5432 bị Windows chặn trên máy này | `.env` (không commit) đặt `POSTGRES_PORT=55432` | `make up`, `make test` từ Windows: 374 pass, 1 bỏ qua (test quyền thực thi của hook, cố ý bỏ qua trên Windows) |
| Ghi hạn chế: run id không chứa phiên bản thư viện | Báo cáo thực tập và bài báo, mục hạn chế | — |

### Việc cần làm (theo thứ tự)

1. **Gộp sổ test-một-lần trên máy chủ dự án** (máy đã chạy `gbm-final`). Máy đó có `artifacts/test_runs.json` chưa được git theo dõi, nên `git pull` sẽ báo *untracked working tree file would be overwritten*. Cách làm: đổi tên file local (ví dụ `test_runs.local.json`), `git pull`, chép mục nào có trong file local mà file mới chưa có (so theo `hash`), rồi commit. Làm tương tự với `artifacts/detect_report_runs.json`. **Từ nay, sau mỗi `*-final` hay `detect-report`, commit sổ ngay.**
2. **Chép kết quả test của Gradient Boosting sang máy demo.** `artifacts/runs/run-f8807cb6f780/test/` chỉ có trên máy chủ dự án. Thiếu thư mục này thì dashboard không có dòng Test 0,408. Chép cùng đường dẫn rồi `make dashboard`. **Không** chạy `make gbm-final` để tạo lại.
3. **Muốn dashboard Product 01 hiện bộ report** thay vì bộ tuning: chép `artifacts/detections/det-08335c6af086/` từ máy chủ dự án. Không chạy lại `make detect-report`.
4. Trên máy nào bị chặn cổng 5432 (Windows báo *access permissions* khi `make up`): tạo `.env` từ `.env.example` với `POSTGRES_PORT=55432`.
5. Việc cũ, không chặn: bật WSL integration trong Docker Desktop; xoá các nhánh cũ đã merge trên GitHub (xem mục 3.3).
6. Hai câu hỏi mở đã được phân tích (2026-11-09, chỉ validation, xem [báo cáo Stage E mục 2b và 3b](docs/architecture/stage-e-report.md)): chia ngẫu nhiên cho PR-AUC thấp hơn chủ yếu vì hai validation là hai tập dòng khác nhau (khoảng 0,03 còn chưa giải thích); đặc trưng lịch sử không giúp vì `C1–C14` đã chứa phần lớn thông tin theo thực thể (bỏ chúng thì 0,497 xuống 0,158). Khoá có `D1n` cho gợi ý nhỏ, chưa đủ ý nghĩa khi lấy mẫu theo cụm `card1`. Hai PDF đã build lại bằng MiKTeX + XeLaTeX (báo cáo thực tập 20 trang, bài báo 10 trang, 0 lỗi biên dịch); chưa xem từng trang bằng mắt. Mọi thử nghiệm tiếp theo chỉ chạy trên validation; mở tập test lần nữa cần chủ dự án quyết và phải ghi rõ trong báo cáo.

## 1. Đang ở đâu

Lịch 6 tuần: **tuần 1–3 (Stage A, B, C) đã xong**. **Tuần 4 (Stage D) đã xong**: chỉnh trên bộ tuning, đánh giá một lần trên bộ report (`det-08335c6af086`). **Stage E đã chạy xong** (2026-11-06), gồm cả `gbm-final` một lần. Cập nhật 2026-11-06.

| Tuần | Stage | Trạng thái |
| --- | --- | --- |
| 1–2 | A: khung repo, contract, manifest dataset | ✅ Xong. Contract `payment-event` **1.0.0 đã duyệt** (2026-11-03) |
| 1–2 | B: baseline gian lận trên IEEE-CIS | ✅ Xong. Đã chạy test một lần với config `frozen` |
| 3 | C: dữ liệu giả lập và ingestion PostgreSQL | ✅ Xong. Hai config mô phỏng đã `frozen` (2026-11-04) |
| 4 | D: mô hình dữ liệu, KPI, phát hiện bất thường | ✅ Xong. Config detector `frozen`, đã đánh giá report một lần |
| 5 | E: thí nghiệm rò rỉ, Gradient Boosting | ✅ Xong: `leak-827d929eaa73`, `run-f8807cb6f780` (Gradient Boosting test PR-AUC 0,408). API chấm điểm đã cắt |
| 6 | F: dashboard, báo cáo thực tập | ✅ Xong. Báo cáo thực tập và bài báo đã có số Stage E (2026-11-08) |

## 2. Đã làm gì

### Stage A/B — Product 02 (Fraud & Risk, IEEE-CIS)

- Adapter, chia dữ liệu theo thời gian 60/20/20, EDA 6 bước (9 quyết định đã duyệt, xem [`eda-summary.md`](docs/data-analysis/eda-summary.md)), metrics, baseline luật và Logistic Regression, run log và quy tắc test-một-lần.
- Kết quả cuối (`run-d6faa4699008`, config `frozen`), chi tiết trong [README](README.md#kết-quả):

| Mô hình | PR-AUC validation | PR-AUC test | Recall @ FPR 5% (test) |
| --- | --- | --- | --- |
| Logistic Regression | 0,245 | **0,165** | 0,28 |
| Luật (rule-based) | 0,089 | 0,078 | 0,22 |

- **Không chạy lại `make baseline-final` với config này.** Tập test đã được dùng (hai lần: `run-515a1190a0a4` với config cũ, `run-d6faa4699008` sau khi thêm `fpr_target`; mọi metric chung trùng khớp).

### Stage C — nền tảng dữ liệu cho Product 01 (Payment Reliability)

- [Đặc tả](docs/architecture/stage-c-spec.md) (đã duyệt, 11 quyết định ở mục 9) và [báo cáo](docs/architecture/stage-c-report.md).
- Code trong `shared/synthetic-generator/`, giả định chi tiết trong [README của generator](shared/synthetic-generator/README.md):
  - **C01** config có kiểu (pydantic) và `simulation_id` tất định;
  - **C02** bộ sinh theo luật: Poisson theo giờ, mùa vụ theo giờ Việt Nam, retry chỉ cho lỗi kỹ thuật, có thể đổi provider;
  - **C03** 4 loại bất thường (`provider_outage`, `latency_degradation`, `error_burst`, `traffic_drop`), nhãn chỉ nằm trong `anomaly_labels.json`;
  - **C04** schema PostgreSQL (`infrastructure/database/001_payment_events.sql`), ingestion kiểm tra contract và 5 quy tắc giữa các attempt, nạp lại không trùng;
  - **C05** README giả định và báo cáo.
- Hai lần mô phỏng:

| Config | Mục đích | `simulation_id` | Payment / sự kiện | Bất thường |
| --- | --- | --- | --- | --- |
| `configs/demo.yaml` | tuning (chỉnh detector) | `sim-485cacc9c858` | 25.573 / 30.050 | outage, latency, error burst, outage yếu x1,5 |
| `configs/report.yaml` | report (chỉ để báo cáo) | `sim-f6e6749ff0bf` | 25.151 / 29.340 | outage, latency, **traffic drop**, outage yếu x1,5 |

- `make test`: 345 test pass khi có PostgreSQL, kể cả Stage D (7 test database tự bỏ qua nếu không có).
- Sửa đổi 2026-11-04 (đặc tả Stage C, mục 10): 150 payment/giờ thay cho 30, và thêm một sự cố yếu x1,5 mỗi config.

## 3. Việc cần làm tiếp

### 3.1 Kết quả Stage D

| Detector | Tuning (`det-3ddc26cff253`) | Report (`det-08335c6af086`, một lần) |
| --- | --- | --- |
| D-B gộp cửa sổ | 3/4, 0 báo nhầm/ngày | 2/4, 0 báo nhầm/ngày |
| D-A z-score bền vững | 2/4, 1,0 báo nhầm/ngày | 0/4, 2,0 báo nhầm/ngày |

- Config detector đã `frozen` (agent đặt theo yêu cầu của chủ dự án, commit `e331ec1`, trước khi chạy report). **Không chạy lại `make detect-report` với config này**; từ 2026-11-09 sổ `artifacts/detect_report_runs.json` nằm trong git và chặn lần chạy thứ hai.
- Cả hai detector trượt `traffic_drop` (loại không có trong tuning) và sự cố x1,5. Muốn thử ngưỡng riêng cho từng loại KPI là config mới và cần bộ report mới.

### 3.2 Sau Stage D

- **Stage E (tuần 5): xong.** [Đặc tả](docs/architecture/stage-e-spec.md), [báo cáo](docs/architecture/stage-e-report.md), [ADR 0006](docs/decisions/0006-gradient-boosting-sklearn.md). API chấm điểm đã cắt.
  1. Xong (2026-11-06): `make leakage` → `leak-827d929eaa73`; `make gbm` → `run-f8807cb6f780` (PR-AUC validation 0,497).
  2. `gbm.yaml` đã `status: frozen`; `make gbm-final` đã chạy một lần: test PR-AUC 0,408, recall tại FPR 5% là 0,51. **Không chạy lại.** Số đã điền vào báo cáo thực tập, bài báo và README (2026-11-08).
- **Stage F (tuần 6): xong.** `make dashboard` sinh `artifacts/dashboard/index.html` cho cả hai sản phẩm ([đặc tả](docs/architecture/stage-f-spec.md), [ADR 0007](docs/decisions/0007-static-html-dashboard.md)). [Dàn ý báo cáo thực tập](docs/report/report-outline.md) gắn từng số với run id; mục 4.3 và 4.4 đã có số. Dashboard gộp cảnh báo `ALL` trùng thời gian với cảnh báo provider (cột "Gộp ALL", 2026-11-08); chỉ đổi phần hiển thị, `incidents.json` và kết quả đánh giá giữ nguyên.

### 3.3 Việc nhỏ, không chặn

- Bật WSL integration cho Ubuntu trong Docker Desktop (Settings → Resources → WSL integration → Ubuntu → **Apply & restart**), rồi thử `make up` và `make db-init` từ WSL. Lần kiểm chứng C04 dùng một container `postgres:16` tạm vì integration chưa có hiệu lực.
- Xoá các nhánh cũ đã merge trên GitHub: `contract/approve-payment-event`, `stage-c`, `docs/*`, `integration/stage-ab`, `task/*`.

## 4. Cách chạy

Có hai môi trường, **mỗi môi trường một `.venv` riêng, đừng dùng chung**: (1) **WSL Ubuntu** (thư mục `/mnt/f/VSF/prj`), nơi chạy PostgreSQL; (2) **Windows** với `uv` và Git Bash, đã kiểm tra `make lint`, `make test` (cả test database, qua Docker Desktop) và `make gbm`.

- **Windows:** `make` tự dùng `.venv-win` (biến `UV_PROJECT_ENVIRONMENT` trong Makefile), nên không đụng `.venv` của WSL. Chạy `uv` trực tiếp ngoài `make` trên Windows thì phải tự đặt `UV_PROJECT_ENVIRONMENT=.venv-win`, nếu không `.venv` của WSL sẽ bị xoá.
- **Cổng PostgreSQL:** máy này bị Windows chặn cổng 5432; `.env` (không commit) đặt `POSTGRES_PORT=55432`. Từ Windows: `make up`, `make db-init`, `make ingest`, `make kpi` đã chạy được (2026-11-09).

```bash
make setup
```

```bash
make lint test
```

```bash
make simulate
```

```bash
make simulate CONFIG=shared/synthetic-generator/configs/report.yaml
```

```bash
make up
```

```bash
make db-init
```

```bash
make ingest SIM=sim-485cacc9c858
```

```bash
make kpi SIM=sim-485cacc9c858
```

```bash
make detect
```

Dataset IEEE-CIS chỉ có trên máy chủ dự án (`datasets/raw/ieee-cis/`, không commit). Không cần nó cho Stage C và D.

## 5. Quy tắc làm việc

- Không dữ liệu thật, dữ liệu thẻ hay secret trong repo. Không commit dataset, Parquet, mô hình, `artifacts/` hay `.env`.
- **Chỉ chủ dự án** được duyệt contract, đặc tả, quyết định EDA, đặt `frozen` và chạy `make baseline-final`.
- **Sổ test-một-lần nằm trong git** (`artifacts/test_runs.json`, `artifacts/detect_report_runs.json`, từ 2026-11-09). Sau mỗi `*-final` hay `detect-report`, commit sổ ngay, để máy khác không mở lại tập test. Trước đó sổ chỉ nằm trên từng máy, nên máy này đã có thể chạy lại `gbm-final` và `detect-report` mà không bị chặn.
- Thay đổi kiến trúc hay thêm thư viện phải có ADR trong `docs/decisions/`.
- Mỗi việc một nhánh; chỉ xong khi `make lint` và `make test` đều pass. Mở PR vào `main`; CI chạy lint và test trên Python 3.11 và 3.13.
- Chủ dự án muốn commit từng bước trên máy và push một lần khi xong một phần việc.
- Đổi kết quả sinh dữ liệu với cùng config thì phải tăng `GENERATOR_VERSION` trong `synthetic_generator/__init__.py`.
- File `AGENTS.md` (quy tắc gốc, bị git-ignore) không có trên máy này. Nếu chủ dự án có bản, hãy xin bản đó.

## 6. Tài liệu chính

| Tài liệu | Nội dung |
| --- | --- |
| [Báo cáo thực tập (PDF)](docs/report/bao-cao-thuc-tap.pdf), [mã LaTeX](docs/report/latex/) | Báo cáo đầy đủ (25 trang, có mục Stage G); bài báo 10 trang |
| [Hướng dẫn GitHub](docs/github-guide.md) | Nhánh, PR, merge, dọn nhánh, git hook, tag bản nộp |
| [Tổng quan đề tài](docs/product/project-overview.md) | Bài toán, phạm vi, kế hoạch 6 tuần, rủi ro, tài liệu tham khảo, trạng thái task |
| [Contract `payment-event`](contracts/payment-event/) | Schema 1.0.0 và changelog (quy tắc giữa các attempt) |
| [Đặc tả](docs/architecture/stage-c-spec.md) và [báo cáo](docs/architecture/stage-c-report.md) Stage C | Thiết kế, quyết định, kết quả, hạn chế |
| [README generator](shared/synthetic-generator/README.md) | Mọi giả định của dữ liệu giả lập |
| [Đặc tả](docs/architecture/stage-d-spec.md) và [báo cáo](docs/architecture/stage-d-report.md) Stage D | KPI, detector, đánh giá, kết quả tuning |
| [Đặc tả](docs/architecture/stage-e-spec.md) và [báo cáo](docs/architecture/stage-e-report.md) Stage E | Thí nghiệm rò rỉ, Gradient Boosting |
| [Đặc tả Stage F](docs/architecture/stage-f-spec.md), [dàn ý báo cáo](docs/report/report-outline.md) | Dashboard, báo cáo |
| [ADR 0001–0010](docs/decisions/) | Cấu trúc package, ranh giới hai sản phẩm, độ trễ nhãn, driver PostgreSQL, tầng KPI bằng SQL views, Gradient Boosting của scikit-learn, dashboard HTML tĩnh, đặc trưng lịch sử thực thể chỉ nhìn quá khứ, protocol đánh giá Stage G, `experiment_id` và `execution_id` |
| [Báo cáo Stage G](docs/architecture/stage-g-report.md), [báo cáo tuần](docs/weekly/) | Hiệu chỉnh, chính sách, độ ổn định, chấm điểm theo lô; báo cáo theo tuần cho mentor |
