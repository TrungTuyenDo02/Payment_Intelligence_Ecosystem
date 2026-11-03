# Đặc tả Stage C — Bộ sinh dữ liệu giả lập và ingestion

- **Trạng thái:** **Đã duyệt** bởi chủ dự án (2026-11-04). File này là nguồn chính cho Stage C; không chép sang `AGENTS.md`.
- **Điều kiện bắt đầu code:** (1) contract `payment-event` được duyệt (đã duyệt 1.0.0 ngày 2026-11-03); (2) các câu hỏi ở mục 9 (đã trả lời ngày 2026-11-03); (3) Stage A/B đã merge vào `main`. Cả ba điều kiện đã đạt.
- **Liên quan:** [ADR 0002](../decisions/0002-product-boundaries.md) (Product 01 chỉ dùng dữ liệu giả lập), contract `contracts/payment-event/`.

## 1. Mục tiêu

Sinh ra một luồng sự kiện thanh toán giả lập **đúng contract**, **tái lập chính xác** từ `simulation_id`, có **bất thường được chèn có chủ đích** kèm nhãn ground truth riêng, rồi nạp vào PostgreSQL với kiểm tra hợp lệ và chống trùng lặp. Đây là đầu vào cho KPI và detector ở Stage D.

## 2. Phạm vi

**Trong phạm vi**
- `shared/synthetic-generator/`: package `synthetic_generator` (mô hình sinh, CLI).
- Kiểm tra từng sự kiện dùng lại `payment_event_rules.validate_event` của contract, không viết lại. Kiểm tra giữa các attempt nằm trong code ingestion. Không tạo package `shared/data-validation/` riêng.
- Ingestion một lần (batch) từ file JSONL vào PostgreSQL.
- Config YAML cho mỗi kịch bản mô phỏng, có `status: draft | frozen` như D5.

**Ngoài phạm vi**
- Streaming (Kafka), lịch chạy tự động, dbt, KPI, detector (Stage D).
- Dữ liệu khách hàng, dữ liệu thẻ, nhãn gian lận (ADR 0002).
- Học phân phối từ dữ liệu thật (CTGAN hoặc tương tự). Mọi tham số là giả định được ghi rõ trong config.

## 3. Mô hình sinh dữ liệu (dựa trên luật)

| Thành phần | Mô hình đề xuất | Tham số trong config |
| --- | --- | --- |
| Thực thể | Danh sách provider và merchant cố định, ID dạng `prov_001`, `mer_0001` | Số provider, số merchant, tỷ trọng merchant (phân phối lệch) |
| Thời gian | Khoảng mô phỏng theo UTC; mùa vụ theo giờ địa phương `Asia/Ho_Chi_Minh` | Ngày bắt đầu, số ngày, hệ số theo giờ trong ngày và ngày trong tuần |
| Số lượng giao dịch | Quá trình Poisson với cường độ thay đổi theo giờ | Số payment trung bình mỗi giờ |
| Phương thức và số tiền | Phân phối rời rạc cho `payment_method`; số tiền log-normal theo phương thức, làm tròn đến 1.000 VND | Tỷ trọng phương thức, tham số log-normal |
| Kết quả attempt | Xác suất thất bại theo provider × phương thức; mã lỗi theo phân phối rời rạc | Xác suất lỗi nền, phân phối mã lỗi |
| Retry | Chỉ lỗi kỹ thuật (`TIMEOUT`, `PROVIDER_ERROR`, `NETWORK_ERROR`) được thử lại, tối đa k lần; `DECLINED` và `INVALID_REQUEST` không retry. Mỗi attempt có `attempt_id` riêng; retry có thể chuyển sang provider khác. `merchant_id`, `amount`, `payment_method`, `currency` giữ nguyên | Xác suất retry, k, khoảng chờ, `retry_switch_provider_prob` |
| Độ trễ | Log-normal theo provider; attempt `TIMEOUT` có độ trễ bằng ngưỡng timeout | Tham số log-normal, ngưỡng timeout |

Tất cả sự kiện có `source_system = synthetic_generator`, `currency = VND`, `event_time` là thời điểm attempt **kết thúc** (UTC, hậu tố `Z`).

## 4. Chèn bất thường và ground truth

- Mỗi kịch bản bất thường được khai báo trong config: loại, provider hoặc phương thức bị ảnh hưởng, thời điểm bắt đầu, thời lượng, độ lớn.
- Các loại đề xuất:
  1. `provider_outage`: tỷ lệ `TIMEOUT` hoặc `PROVIDER_ERROR` của một provider tăng mạnh.
  2. `latency_degradation`: độ trễ của một provider tăng theo hệ số.
  3. `error_burst`: một mã lỗi tăng đột biến trong thời gian ngắn.
  4. `traffic_drop`: lưu lượng một phương thức giảm mạnh.
- **Ground truth tách khỏi sự kiện:** file `anomaly_labels.json` riêng, không có trường nào trong sự kiện tiết lộ bất thường. Đây là cùng tinh thần với quy tắc 6 (nhãn tách khỏi input).
- **Giảm đánh giá vòng tròn (rủi ro 2):** config phân biệt `tuning` và `report`. Hai nhóm dùng seed khác nhau, và nhóm `report` có ít nhất một loại bất thường không xuất hiện ở `tuning`. Kịch bản phải được `frozen` trước khi chỉnh detector ở Stage D.

## 5. Tái lập (`simulation_id`)

- `simulation_id` = SHA-256 (rút gọn) của config dạng canonical (bỏ trường `status`) + seed + phiên bản generator. Cách tính tương tự D6.
- Mỗi lần sinh ghi `artifacts/simulations/<simulation_id>/`:
  - `events.jsonl`: các sự kiện, sắp theo `event_time` rồi `event_id`.
  - `anomaly_labels.json`: ground truth.
  - `simulation_manifest.yaml`: `simulation_id`, config, seed, phiên bản generator, số dòng, SHA-256 của `events.jsonl`.
- Chạy lại cùng config và seed phải cho `events.jsonl` **giống hệt từng byte**.
- Thư mục `artifacts/` vẫn git-ignore. Chỉ config được commit.

## 6. Ingestion vào PostgreSQL

| Bảng | Nội dung |
| --- | --- |
| `ingestion_runs` | Mỗi lần nạp: `simulation_id`, thời điểm, số dòng đọc, nhận, từ chối, checksum file |
| `payment_events` | Sự kiện hợp lệ, các trường payload được tách cột; khoá chính `event_id` |
| `ingestion_rejects` | Sự kiện không hợp lệ kèm lý do (từ `validate_event`) và nội dung gốc |

Quy tắc:
- Mọi sự kiện đi qua `validate_event`. Sự kiện lỗi vào `ingestion_rejects`, không làm dừng cả lô.
- Tính duy nhất của `event_id` được đảm bảo bằng khoá chính. Changelog của contract đã hẹn kiểm tra này ở ingestion.
- Kiểm tra các quy tắc giữa các attempt của cùng payment (trong code ingestion), theo changelog contract 1.0.0: cùng `merchant_id`, `amount`, `payment_method`, `currency`; tối đa một `SUCCESS` và không có attempt sau `SUCCESS`; cặp (`payment_id`, `attempt_number`) duy nhất; `attempt_number` liên tiếp từ 1. Retry được đổi `provider_id`. Nếu một payment vi phạm, **mọi attempt của payment đó** vào `ingestion_rejects` kèm lý do, để chuỗi retry không bị đứt.
- Nạp lại cùng một `simulation_id` không tạo bản ghi trùng (idempotent). Nếu checksum `events.jsonl` khác lần nạp trước của cùng `simulation_id`, từ chối nạp và báo lỗi.
- Schema SQL nằm trong `infrastructure/database/`, chạy bằng một lệnh `make db-init`.

## 7. Lệnh Makefile mới

| Lệnh | Mục đích |
| --- | --- |
| `make simulate CONFIG=...` | Sinh dữ liệu vào `artifacts/simulations/<simulation_id>/` |
| `make db-init` | Tạo bảng trong PostgreSQL |
| `make ingest SIM=<simulation_id>` | Nạp sự kiện vào PostgreSQL |

## 8. Task và tiêu chí nghiệm thu

| ID | Task | Tiêu chí nghiệm thu |
| --- | --- | --- |
| C01 | Config và `simulation_id` | Config có kiểu (pydantic), từ chối trường lạ; `simulation_id` tất định; đổi `status` không đổi `simulation_id` |
| C02 | Mô hình sinh cơ bản (không bất thường) | 100% sự kiện qua `validate_event`; `payment_id != attempt_id`; `event_id` duy nhất; tỷ lệ phương thức và lỗi trên mẫu lớn nằm trong dung sai so với config; chạy hai lần giống hệt từng byte |
| C03 | Chèn bất thường và ground truth | Chỉ số bị ảnh hưởng thay đổi trong cửa sổ khai báo và không thay đổi ngoài cửa sổ; `anomaly_labels.json` khớp config; sự kiện không chứa trường nào tiết lộ bất thường |
| C04 | Schema PostgreSQL và ingestion | Sự kiện lỗi vào `ingestion_rejects` kèm lý do; nạp lại không tạo trùng; test tích hợp tự bỏ qua kèm lý do rõ khi PostgreSQL không chạy |
| C05 | Tài liệu và báo cáo | README của generator mô tả mọi giả định; báo cáo theo mẫu mục 12 của `AGENTS.md` |

Mỗi task một nhánh `task/C0x-...`; chỉ xong khi `make lint` và `make test` đều pass.

## 9. Quyết định của chủ dự án (2026-11-03)

| # | Câu hỏi | Quyết định |
| --- | --- | --- |
| 1 | Thứ tự attempt | Thêm `attempt_number` (số nguyên ≥ 1) vào contract, trước khi duyệt (changelog, revision 2) |
| 2 | Phân loại lỗi | Giữ một trạng thái `FAILED` trong contract; tầng KPI (Stage D) tách lỗi nghiệp vụ (`DECLINED`, `INVALID_REQUEST`) khỏi lỗi kỹ thuật |
| 3 | Thư viện PostgreSQL | `psycopg[binary]`, xem [ADR 0004](../decisions/0004-postgres-driver.md) |
| 4 | Quy mô dữ liệu | **Demo nhỏ**: mặc định 7 ngày, 3 provider, 20 merchant, trung bình 30 payment mỗi giờ (khoảng 5 nghìn payment, khoảng 6 nghìn sự kiện kể cả retry). Config cho phép tăng khi cần |
| 5 | Phiên bản trong sự kiện | Sự kiện ghi `schema_version = "1.0.0"`; trạng thái duyệt chỉ ghi trong changelog và `x-status` |

Quyết định khi duyệt đặc tả (2026-11-04):

| # | Câu hỏi | Quyết định |
| --- | --- | --- |
| 6 | Payment vi phạm quy tắc giữa các attempt | Từ chối cả payment: mọi attempt vào `ingestion_rejects` |
| 7 | Lỗi nào được retry | Chỉ `TIMEOUT`, `PROVIDER_ERROR`, `NETWORK_ERROR` |
| 8 | Chọn provider khi retry | Tham số config `retry_switch_provider_prob` |
| 9 | Nạp lại cùng `simulation_id`, khác checksum | Từ chối nạp, báo lỗi |
| 10 | Package `shared/data-validation/` | Không tạo; kiểm tra giữa các attempt nằm trong ingestion |
| 11 | Chép đặc tả vào `AGENTS.md` | Không chép; file này là nguồn chính, đổi tên thành `stage-c-spec.md` |

Không còn việc nào chặn việc viết code Stage C.
