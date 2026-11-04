# Payment Intelligence Ecosystem

[![CI](https://github.com/TrungTuyenDo02/Payment_Intelligence_Ecosystem/actions/workflows/ci.yml/badge.svg)](https://github.com/TrungTuyenDo02/Payment_Intelligence_Ecosystem/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.11%2B-blue)
![License](https://img.shields.io/badge/license-MIT-lightgrey)

Đề tài thực tập 6 tuần: một nền tảng dữ liệu nhỏ cho mảng thanh toán, trả lời hai câu hỏi của vận hành:

1. **Hệ thống thanh toán có đang chạy ổn không?** Theo dõi KPI và phát hiện bất thường (Product 01, dữ liệu giả lập).
2. **Giao dịch này có đáng nghi không?** Chấm điểm rủi ro gian lận (Product 02, dataset công khai IEEE-CIS).

Không dùng dữ liệu thật của công ty. Toàn bộ chạy trên máy cá nhân bằng Python và Docker.

## Hệ thống

<p align="center"><img src="docs/assets/diagrams/system-overview.svg" alt="Sơ đồ tổng thể: nền tảng dùng chung, hai sản phẩm và trạng thái từng bước" width="100%"></p>

Hai sản phẩm dùng chung nền tảng (contract dữ liệu, quản lý dataset, quy tắc đánh giá, PostgreSQL) nhưng không dùng chung dữ liệu ([ADR 0002](docs/decisions/0002-product-boundaries.md)).

## Tiến độ

<p align="center"><img src="docs/assets/diagrams/roadmap.svg" alt="Lộ trình 6 tuần: A, B, C đã xong; D đang làm ở tuần 4" width="100%"></p>

- **Đã xong (tuần 1–3):** khung repo, contract `payment-event` 1.0.0, hai baseline gian lận đã đánh giá trên tập test, bộ sinh dữ liệu thanh toán giả lập và nạp vào PostgreSQL.
- **Tuần 4:** KPI độ tin cậy và hai detector đã xong và đã chỉnh trên bộ dữ liệu tuning. Còn bước đánh giá một lần trên bộ report.

## Kết quả đến nay

**Product 02: phát hiện gian lận trên IEEE-CIS.** Dữ liệu được chia theo thời gian: mô hình học trên phần cũ, được đánh giá trên phần mới hơn, giống như khi chạy thật.

<p align="center"><img src="docs/assets/results/split.png" alt="Train 60%, validation 20%, test 20% theo thời gian, kèm số giao dịch và tỷ lệ gian lận" width="85%"></p>
<p align="center"><img src="docs/assets/results/results.png" alt="PR-AUC và tỷ lệ gian lận bắt được tại FPR 5% của hai mô hình trên validation và test" width="100%"></p>

- **Logistic Regression tốt hơn baseline luật.** PR-AUC trên test là 0,165, gấp khoảng 4,8 lần mô hình đoán ngẫu nhiên. Baseline luật đạt 0,078.
- **Kết quả giảm từ validation sang test.** Dữ liệu thay đổi theo thời gian, nên con số trên validation lạc quan hơn thực tế. Đây là lý do tập test chỉ được mở **một lần**, với cấu hình đã chốt trước.
- Bảng số đầy đủ: [`summary.md`](docs/assets/results/summary.md) (lần chạy `run-d6faa4699008`).

**Product 01: dữ liệu thanh toán giả lập.** Mỗi lần mô phỏng 7 ngày tạo khoảng 25 nghìn payment (khoảng 30 nghìn sự kiện, có retry), với 4 sự cố được cài sẵn, trong đó có một sự cố yếu để thử giới hạn của detector. Mọi sự kiện qua kiểm tra contract và được nạp vào PostgreSQL không lỗi. Trên bộ dùng để chỉnh ngưỡng (tuning), detector chính bắt được 3/4 sự cố trong 15 phút, không báo nhầm, và không bắt được sự cố yếu x1,5 ([báo cáo Stage D](docs/architecture/stage-d-report.md)). Đây chưa phải kết quả cuối: số dùng cho báo cáo sẽ lấy từ một bộ dữ liệu riêng, chạy đúng một lần.

## Nguyên tắc

- **Đánh giá trung thực hơn điểm cao:** chia theo thời gian, không xáo trộn; mọi phép biến đổi chỉ học trên train; tập test dùng một lần.
- **Tái lập được:** cùng config, seed và dữ liệu cho cùng kết quả; mỗi lần chạy lưu config, checksum dữ liệu và metric.
- **Không dữ liệu thật, không dữ liệu thẻ:** chỉ dataset công khai và dữ liệu tự sinh.

## Chạy thử

Cần Python 3.11+, [uv](https://docs.astral.sh/uv/), Docker và `make`.

```bash
git clone https://github.com/TrungTuyenDo02/Payment_Intelligence_Ecosystem.git
```

```bash
cd Payment_Intelligence_Ecosystem && cp .env.example .env
```

```bash
make setup
```

```bash
make lint test
```

`make test` chỉ dùng dữ liệu tổng hợp nhỏ có sẵn trong repo, không cần tải dataset.

<details>
<summary>Các lệnh khác và cách chạy với dữ liệu thật</summary>

| Lệnh | Việc |
| --- | --- |
| `make up` / `make down` | Bật / tắt PostgreSQL 16 |
| `make simulate` | Sinh dữ liệu thanh toán giả lập vào `artifacts/simulations/<simulation_id>/` (`CONFIG=...` để chọn kịch bản) |
| `make db-init` / `make ingest SIM=<simulation_id>` | Tạo bảng và view KPI / nạp một lần mô phỏng vào PostgreSQL |
| `make kpi SIM=<simulation_id>` | Xuất KPI 15 phút ra Parquet |
| `make tune` / `make detect` / `make detect-plot` | Chỉnh ngưỡng, chạy detector, vẽ biểu đồ (chỉ trên bộ tuning) |
| `make detect-report` | Đánh giá một lần trên bộ report, chỉ với config detector đã `frozen` (chỉ chủ dự án chạy) |
| `make eda` | EDA trên phần train của IEEE-CIS |
| `make baseline` | Hai baseline, đánh giá trên validation |
| `make baseline-final` | Đánh giá test một lần, chỉ với config đã `frozen` (chỉ chủ dự án chạy) |
| `make report` | Vẽ biểu đồ và bảng số cho lần chạy gần nhất (`RUN_DIR=...` để chọn lần khác) |

**Dữ liệu IEEE-CIS:** tải [IEEE-CIS Fraud Detection](https://www.kaggle.com/c/ieee-fraud-detection) từ Kaggle (cần đăng nhập và chấp nhận điều khoản cuộc thi), đặt `train_transaction.csv` và `train_identity.csv` vào `datasets/raw/ieee-cis/` (không commit). Tạo manifest checksum:

```bash
PYTHONPATH=shared/dataset-management uv run python -m dataset_management.cli --name ieee-cis --source "Kaggle competition: IEEE-CIS Fraud Detection (https://www.kaggle.com/c/ieee-fraud-detection)" --base-dir datasets/raw/ieee-cis --file train_transaction.csv --file train_identity.csv --download-date YYYY-MM-DD --license-note "Kaggle competition terms, research use only, verify before any other use" --out datasets/manifests/ieee-cis.yaml
```

Sau đó chạy `make eda`, `make baseline`, `make report`.

</details>

<details>
<summary>Quy trình làm việc</summary>

<p align="center"><img src="docs/assets/diagrams/workflow.svg" alt="Quy trình: nhánh, pull request, CI, review, merge" width="100%"></p>

Mỗi pull request được [CI](.github/workflows/ci.yml) chạy `make lint` và `make test` trên Python 3.11 và 3.13, và chặn việc lỡ commit dataset, file mô hình hoặc `.env`.

</details>

## Tài liệu

| Tài liệu | Nội dung |
| --- | --- |
| [Tổng quan đề tài](docs/product/project-overview.md) | Bài toán, phạm vi, kế hoạch, rủi ro, tài liệu tham khảo |
| [Bàn giao công việc](HANDOFF.md) | Trạng thái hiện tại và việc tiếp theo |
| [Quyết định tiền xử lý (EDA)](docs/data-analysis/eda-summary.md) | 9 quyết định đã duyệt và bằng chứng |
| [Đặc tả](docs/architecture/stage-c-spec.md) · [Báo cáo](docs/architecture/stage-c-report.md) Stage C | Bộ sinh dữ liệu giả lập và ingestion |
| [Đặc tả](docs/architecture/stage-d-spec.md) · [Báo cáo](docs/architecture/stage-d-report.md) Stage D | KPI độ tin cậy và phát hiện bất thường |
| [Contract `payment-event`](contracts/payment-event/) | JSON Schema 1.0.0 và changelog |
| [ADR](docs/decisions/) | Các quyết định kiến trúc (0001–0005) |

## Giấy phép

Mã nguồn theo giấy phép [MIT](LICENSE). Dữ liệu IEEE-CIS theo điều khoản cuộc thi Kaggle và không đi kèm repo.

**Đỗ Trung Tuyến** · [@TrungTuyenDo02](https://github.com/TrungTuyenDo02)
