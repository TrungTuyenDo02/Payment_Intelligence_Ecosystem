# Đặc tả Stage D — KPI độ tin cậy và phát hiện bất thường (bản nháp)

- **Trạng thái:** **Bản nháp**, chờ chủ dự án duyệt. Chưa viết code cho tới khi duyệt.
- **Điều kiện bắt đầu code:**
  1. Chủ dự án duyệt giả định của generator và đặt `status: frozen` cho `shared/synthetic-generator/configs/demo.yaml` và `report.yaml`.
  2. Chủ dự án trả lời các câu hỏi ở mục 10.
  3. Đặc tả này được duyệt và đổi tên thành `stage-d-spec.md`.
- **Liên quan:**
  - [Đặc tả Stage C](stage-c-spec.md), gồm sửa đổi A1 và A2 ở mục 10.
  - [ADR 0002](../decisions/0002-product-boundaries.md): Product 01 chỉ dùng dữ liệu giả lập.
  - [ADR 0005](../decisions/0005-kpi-layer-sql-views.md): tầng KPI dùng SQL views.

## 1. Mục tiêu

Từ bảng `payment_events` (Stage C), tính **KPI độ tin cậy theo khung 15 phút**, chạy **detector** trên các chuỗi KPI đó, gộp các điểm bất thường thành **danh sách sự cố**, rồi **đánh giá** detector với các bất thường đã cài sẵn.

Kết quả là "kiểm chứng trên bất thường đã biết", không phải hiệu năng thực tế (rủi ro 2 trong tổng quan).

## 2. Phạm vi

**Trong phạm vi**
- SQL views tính KPI trong `infrastructure/database/002_kpi_views.sql` (ADR 0005).
- Package `projects/payment-reliability/payment_reliability/`: đọc KPI, detector, gộp sự cố, đánh giá, CLI. Cách đặt tên giống quyết định D1 (thư mục có gạch nối, package dạng snake_case). Thêm `projects/payment-reliability` vào `pythonpath` của pytest và `PYTHONPATH` của Makefile.
- Config detector YAML có `status: draft | frozen` như D5.
- Run log và quy tắc đánh giá một lần trên mô phỏng `report`, giống Stage B.
- Báo cáo Stage D và biểu đồ chuỗi KPI có đánh dấu cửa sổ bất thường và cảnh báo.

**Ngoài phạm vi**
- Dashboard, API, cảnh báo thời gian thực, lịch chạy tự động (Stage F trở đi).
- Detector học máy (Isolation Forest, mạng nơ-ron). Chỉ dùng phương pháp thống kê giải thích được.
- Thư viện mới. Dùng `pandas`, `numpy`, `psycopg`, `matplotlib` đã có.

## 3. Định nghĩa KPI

**Hạt (grain):** một dòng cho mỗi (`simulation_id`, khung 15 phút, `provider_id`). Có thêm một dòng tổng cho mọi provider, với `provider_id = 'ALL'`.

**Gán khung:** theo `event_time`, tức thời điểm attempt kết thúc, làm tròn xuống bội số 15 phút theo UTC. Đây là đề xuất, xem câu hỏi Q1.

**Khung trống:** khung không có attempt nào vẫn có dòng, với số đếm bằng 0 và tỷ lệ để `NULL`. Thiếu dòng sẽ che mất sự cố mất lưu lượng.

| KPI | Định nghĩa | Ghi chú |
| --- | --- | --- |
| `attempts` | Số attempt | |
| `success_rate` | `SUCCESS` / `attempts` | |
| `first_attempt_success_rate` | `SUCCESS` có `attempt_number = 1` / số attempt có `attempt_number = 1` | Lần thử đầu, không tính retry |
| `technical_failure_rate` | (`TIMEOUT` + `PROVIDER_ERROR` + `NETWORK_ERROR`) / `attempts` | Lỗi kỹ thuật, tín hiệu chính về độ tin cậy của provider |
| `business_failure_rate` | (`DECLINED` + `INVALID_REQUEST`) / `attempts` | Lỗi nghiệp vụ, tách riêng theo quyết định 2 của Stage C |
| `retry_share` | Số attempt có `attempt_number > 1` / `attempts` | |
| `timeout_rate` | `TIMEOUT` / `attempts` | |
| `latency_p50_ms`, `latency_p95_ms` | `percentile_cont` trên `latency_ms`, **không tính** `TIMEOUT` | `TIMEOUT` luôn bằng ngưỡng 10.000 ms nên sẽ làm méo phân vị |
| `errors_by_code` | Số lỗi theo từng `error_code` | Một view riêng, dạng dài (một dòng cho mỗi mã lỗi) |
| `first_attempts_by_method` | Số attempt đầu tiên theo `payment_method` | Một view riêng, dùng để phát hiện mất lưu lượng |

Mỗi view có chú thích về hạt và định nghĩa cột. Số đếm luôn được giữ cùng tỷ lệ, vì detector cần biết tỷ lệ được tính trên bao nhiêu attempt.

## 4. Detector

**Đầu vào:** chỉ các chuỗi KPI. Detector **không đọc** `anomaly_labels.json`. Chỉ module đánh giá được đọc file này, và có test chặn việc detector import nó (giống test chống rò rỉ ở T10).

**Hai detector**, đều có tham số trong config:

| Detector | Cách làm | Mạnh ở | Yếu ở |
| --- | --- | --- | --- |
| **D-A. z-score bền vững** (baseline) | So giá trị của khung hiện tại với trung vị và MAD của N khung trước đó, ví dụ 24 giờ trước | Đơn giản, chuẩn, giải thích trong một câu | Không biết khung có ít attempt: ban đêm, 1 lỗi trên 2 attempt cũng thành điểm cao |
| **D-B. Điểm theo phân phối nhị thức, gộp cửa sổ** | Với tỷ lệ (lỗi kỹ thuật, timeout): tính tỷ lệ nền p₀ từ 24 giờ trước, rồi đo số lỗi quan sát lệch bao nhiêu so với kỳ vọng `n·p₀`, tính theo độ lệch chuẩn `√(n·p₀·(1−p₀))`. Cộng dồn trên cửa sổ trượt k khung, ví dụ 1 giờ. Với độ trễ: so trung vị log-latency với nền. Với lưu lượng: so **tỷ trọng** của một phương thức trong tổng attempt đầu với tỷ trọng nền, nên không bị ảnh hưởng bởi mùa vụ theo giờ | Tự tính đến số attempt trong khung; cửa sổ gộp có cơ hội bắt sự cố yếu x1,5 | Phức tạp hơn một bước, cần giải thích giả định nhị thức |

Đề xuất làm cả hai và so sánh: D-A là đường cơ sở, D-B là phương án chính. Xem câu hỏi Q2.

**Đầu ra:** mỗi (khung, chuỗi) có một điểm (score) và một cờ cảnh báo khi điểm vượt ngưỡng. "Chuỗi" là một cặp KPI và đối tượng, ví dụ `technical_failure_rate` của `prov_002`.

## 5. Gộp sự cố

- Các khung cảnh báo liên tiếp của cùng một đối tượng (provider hoặc phương thức) được gộp thành một sự cố. Cho phép một khoảng trống tối đa 1 khung.
- Mỗi sự cố có: `incident_id`, đối tượng, các KPI đã cảnh báo, thời gian bắt đầu và kết thúc, điểm cao nhất, KPI trung bình trong sự cố so với nền.
- Ghi vào `artifacts/detections/<run_id>/incidents.json`. Đây là đầu vào cho dashboard ở Stage F.

## 6. Đánh giá

**Phát hiện:** một bất thường được tính là đã phát hiện nếu có sự cố **đúng đối tượng** giao với cửa sổ `[start, end + 15 phút)`. Đối tượng là provider bị ảnh hưởng, hoặc phương thức với `traffic_drop`, hoặc mọi provider với `error_burst` không chỉ định provider. Đề xuất báo cáo thêm số liệu theo quy tắc lỏng hơn "bất kỳ đối tượng nào", xem câu hỏi Q3.

**Chỉ số báo cáo:**
- số bất thường phát hiện được trên tổng số, liệt kê từng cái, kể cả sự cố yếu x1,5;
- độ trễ phát hiện: khung cảnh báo đầu tiên trừ thời điểm bắt đầu;
- số sự cố báo nhầm (không giao với bất thường nào), quy ra mỗi ngày.

**Mục tiêu khi chỉnh ngưỡng:** phát hiện nhiều bất thường nhất trên mô phỏng `tuning` mà số báo nhầm không vượt quá X sự cố mỗi ngày. Đề xuất X = 1, xem câu hỏi Q4.

## 7. Tuning, report và đánh giá một lần

- Chỉ chỉnh tham số và ngưỡng trên `sim-485cacc9c858` (`tuning`).
- Khi chốt, chủ dự án đặt config detector thành `frozen`. `make detect-report` chạy đúng một lần trên `sim-f6e6749ff0bf` (`report`). Lệnh này từ chối config chưa `frozen`, và từ chối chạy lại cùng một hash (ghi trong `artifacts/detect_report_runs.json`). Muốn ép chạy lại phải dùng `--force` và một cảnh báo được ghi vào kết quả. Hash tính từ config detector (bỏ `status`) và `simulation_id`, giống D6.
- Đổi detector hay ngưỡng sau khi xem kết quả `report` là một config mới và phải ghi rõ trong báo cáo.

## 8. Lệnh Makefile mới

| Lệnh | Việc |
| --- | --- |
| `make db-init` | Như cũ, chạy thêm `002_kpi_views.sql` |
| `make kpi SIM=<simulation_id>` | Đọc các view KPI và ghi `artifacts/kpi/<simulation_id>/*.parquet`. Detector đọc Parquet, nên test detector không cần PostgreSQL |
| `make detect SIM=<tuning id>` | Chạy detector, gộp sự cố, đánh giá, ghi `artifacts/detections/<run_id>/`. Chỉ nhận mô phỏng có `purpose: tuning` |
| `make detect-report` | Đánh giá một lần trên mô phỏng `report`, chỉ chạy khi config detector đã `frozen` (mục 7). Chỉ chủ dự án chạy |

## 9. Task và tiêu chí nghiệm thu

| ID | Task | Tiêu chí nghiệm thu |
| --- | --- | --- |
| D01 | SQL views KPI | Có khung trống với số đếm 0; với các tỷ lệ và phân vị, kết quả khớp một cách tính độc lập bằng Python trên một mô phỏng nhỏ (test tích hợp, tự bỏ qua khi không có PostgreSQL); lỗi nghiệp vụ và lỗi kỹ thuật được tách riêng |
| D02 | `make kpi` | Ghi Parquet cho mỗi view; chạy hai lần cho file giống nhau; báo lỗi rõ nếu chưa nạp mô phỏng |
| D03 | Detector D-A và D-B | Test trên chuỗi tổng hợp tự tạo: bắt được bước nhảy đã biết, không cảnh báo trên chuỗi phẳng có nhiễu; điểm của D-B giảm khi số attempt giảm; detector không import module đọc nhãn |
| D04 | Gộp sự cố | Test với các khung cảnh báo tự tạo: gộp đúng khi khoảng trống ≤ 1 khung, tách đúng khi > 1 khung, tách đúng theo đối tượng |
| D05 | Đánh giá, run log, đánh giá một lần | Kết quả khớp một ví dụ tính tay; `make detect` từ chối mô phỏng `report`; `make detect-report` từ chối config `draft` và từ chối hash đã chạy |
| D06 | Báo cáo và biểu đồ | `docs/architecture/stage-d-report.md` có số thật từ một run id; biểu đồ chuỗi KPI tô màu cửa sổ bất thường và đánh dấu sự cố; ghi rõ giới hạn của dữ liệu giả lập |

Mỗi task một nhánh `task/D0x-...`; chỉ xong khi `make lint` và `make test` đều pass.

## 10. Câu hỏi cho chủ dự án

| # | Câu hỏi | Đề xuất |
| --- | --- | --- |
| Q1 | Gán attempt vào khung theo `event_time` (lúc kết thúc) hay theo lúc bắt đầu (`event_time − latency_ms`)? | `event_time`: đó là thứ hệ thống giám sát thật nhìn thấy. Lệch so với lúc bắt đầu tối đa 10 giây, gần như không đổi kết quả với khung 15 phút |
| Q2 | Làm cả hai detector (D-A làm đường cơ sở, D-B làm phương án chính), hay chỉ một? | Cả hai: so sánh với đường cơ sở cho thấy D-B có giá trị gì, giống cách Stage B so Logistic Regression với luật |
| Q3 | Khi đánh giá, có bắt buộc sự cố phải đúng đối tượng không? | Bắt buộc đúng đối tượng cho số chính; báo cáo thêm số theo quy tắc "bất kỳ đối tượng nào" để thấy khác biệt |
| Q4 | Mức báo nhầm chấp nhận được khi chỉnh ngưỡng là bao nhiêu sự cố mỗi ngày? | 1 sự cố mỗi ngày |
| Q5 | Lưu danh sách sự cố ở đâu? | File JSON trong `artifacts/`, giống run log của Stage B. Stage F quyết định có cần bảng PostgreSQL không |
