# Bàn giao công việc — 2026-11-04

> Dành cho người tiếp tục dự án từ ngày 2026-11-05. Đọc file này trước, sau đó đọc [`README.md`](README.md) và [tổng quan đề tài](docs/product/project-overview.md).
> Chủ dự án: Đỗ Trung Tuyến (@TrungTuyenDo02).

## 1. Đang ở đâu

Lịch 6 tuần: **tuần 1–3 (Stage A, B, C) đã xong**. Tuần 4 sẽ làm Stage D. Mọi thứ đã nằm trên `main` (commit `96f4da7`, PR #6).

| Tuần | Stage | Trạng thái |
| --- | --- | --- |
| 1–2 | A: khung repo, contract, manifest dataset | ✅ Xong. Contract `payment-event` **1.0.0 đã duyệt** (2026-11-03) |
| 1–2 | B: baseline gian lận trên IEEE-CIS | ✅ Xong. Đã chạy test một lần với config `frozen` |
| 3 | C: dữ liệu giả lập và ingestion PostgreSQL | ✅ Xong code và test. Hai config mô phỏng **còn `draft`** |
| 4 | D: mô hình dữ liệu, KPI, phát hiện bất thường | ⏳ Chưa bắt đầu, chưa có đặc tả |
| 5 | E: thí nghiệm rò rỉ, Gradient Boosting, API chấm điểm | Chưa bắt đầu |
| 6 | F: dashboard, báo cáo thực tập | Chưa bắt đầu |

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

- `make test`: 318 test pass khi có PostgreSQL (3 test database tự bỏ qua nếu không có).
- Sửa đổi 2026-11-04 (đặc tả Stage C, mục 10): 150 payment/giờ thay cho 30, và thêm một sự cố yếu x1,5 mỗi config.

## 3. Việc cần làm tiếp

### 3.1 Chờ chủ dự án (chặn Stage D)

| # | Việc | Ghi chú |
| --- | --- | --- |
| 1 | Duyệt giả định trong [README generator](shared/synthetic-generator/README.md) và kịch bản bất thường | Tỷ lệ lỗi 15/22/30% **cố ý để cao** |
| 2 | Đặt `status: frozen` cho `shared/synthetic-generator/configs/demo.yaml` và `report.yaml` | Bắt buộc trước khi chỉnh detector (đặc tả mục 4). Chỉ chủ dự án được đặt `frozen` |
| 3 | ~~Quyết định có thêm kịch bản bất thường yếu hơn (khoảng x1,5) không~~ | **Đã quyết (2026-11-04):** thêm vào cả hai config, cùng với 150 payment/giờ. KPI dùng SQL views (ADR 0005); nếu tuần 5 thiếu thời gian thì cắt API chấm điểm trước |

### 3.2 Stage D (tuần 4) — đề xuất thứ tự

1. **Viết đặc tả Stage D** (`docs/architecture/stage-d-spec.md`, bản nháp) theo cách đã làm với Stage C: mục tiêu, phạm vi, task D01–D0x với tiêu chí nghiệm thu, danh sách câu hỏi cho chủ dự án. Chủ dự án duyệt rồi mới viết code.
2. **ADR 0005: dbt hay SQL views** cho tầng mô hình dữ liệu. Phương án dự phòng đã ghi trong kế hoạch là SQL views. Nếu chọn dbt thì cần `dbt-postgres` (thư viện mới, ADR 0004 đã nhắc).
3. **KPI độ tin cậy, tính theo attempt** (quyết định của chủ dự án): tỷ lệ thành công, thành công ngay lần đầu, tỷ lệ retry, độ trễ p50/p95, lỗi theo provider và mã lỗi. Tách lỗi nghiệp vụ (`DECLINED`, `INVALID_REQUEST`) khỏi lỗi kỹ thuật (quyết định 2 của đặc tả Stage C).
4. **Bộ phát hiện bất thường** trên chuỗi KPI theo thời gian. Chỉ chỉnh trên `sim-485cacc9c858` (tuning), chỉ báo cáo trên `sim-f6e6749ff0bf` (report). Báo cáo là "kiểm chứng trên bất thường đã biết", không phải hiệu năng thực tế (rủi ro 2 trong tổng quan). Detector **không được đọc** `anomaly_labels.json`; chỉ phần đánh giá được đọc.
5. Danh sách sự cố (gộp các điểm bất thường liền nhau) làm đầu vào cho dashboard ở Stage F.

### 3.3 Việc nhỏ, không chặn

- Bật WSL integration cho Ubuntu trong Docker Desktop (Settings → Resources → WSL integration → Ubuntu → **Apply & restart**), rồi thử `make up` và `make db-init` từ WSL. Lần kiểm chứng C04 dùng một container `postgres:16` tạm vì integration chưa có hiệu lực.
- Xoá các nhánh cũ đã merge trên GitHub: `contract/approve-payment-event`, `stage-c`, `docs/*`, `integration/stage-ab`, `task/*`.

## 4. Cách chạy

Chạy mọi lệnh `make` trong **WSL Ubuntu** (thư mục `/mnt/f/VSF/prj`). `.venv` được tạo trong WSL; chạy `uv` từ Windows sẽ làm hỏng nó.

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

Dataset IEEE-CIS chỉ có trên máy chủ dự án (`datasets/raw/ieee-cis/`, không commit). Không cần nó cho Stage C và D.

## 5. Quy tắc làm việc

- Không dữ liệu thật, dữ liệu thẻ hay secret trong repo. Không commit dataset, Parquet, mô hình, `artifacts/` hay `.env`.
- **Chỉ chủ dự án** được duyệt contract, đặc tả, quyết định EDA, đặt `frozen` và chạy `make baseline-final`.
- Thay đổi kiến trúc hay thêm thư viện phải có ADR trong `docs/decisions/`.
- Mỗi việc một nhánh; chỉ xong khi `make lint` và `make test` đều pass. Mở PR vào `main`; CI chạy lint và test trên Python 3.11 và 3.13.
- Chủ dự án muốn commit từng bước trên máy và push một lần khi xong một phần việc.
- Đổi kết quả sinh dữ liệu với cùng config thì phải tăng `GENERATOR_VERSION` trong `synthetic_generator/__init__.py`.
- File `AGENTS.md` (quy tắc gốc, bị git-ignore) không có trên máy này. Nếu chủ dự án có bản, hãy xin bản đó.

## 6. Tài liệu chính

| Tài liệu | Nội dung |
| --- | --- |
| [Tổng quan đề tài](docs/product/project-overview.md) | Bài toán, phạm vi, kế hoạch 6 tuần, rủi ro, tài liệu tham khảo, trạng thái task |
| [Contract `payment-event`](contracts/payment-event/) | Schema 1.0.0 và changelog (quy tắc giữa các attempt) |
| [Đặc tả](docs/architecture/stage-c-spec.md) và [báo cáo](docs/architecture/stage-c-report.md) Stage C | Thiết kế, quyết định, kết quả, hạn chế |
| [README generator](shared/synthetic-generator/README.md) | Mọi giả định của dữ liệu giả lập |
| [ADR 0001–0004](docs/decisions/) | Cấu trúc package, ranh giới hai sản phẩm, độ trễ nhãn, driver PostgreSQL |
