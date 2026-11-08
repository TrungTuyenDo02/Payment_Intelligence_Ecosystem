# Báo cáo Stage D — KPI độ tin cậy và phát hiện bất thường

- **Ngày:** 2026-11-04 (tuần 4 của lịch 6 tuần)
- **Đặc tả:** [`stage-d-spec.md`](stage-d-spec.md) (đã duyệt 2026-11-04), [ADR 0005](../decisions/0005-kpi-layer-sql-views.md) (SQL views).
- **Trạng thái:** D01–D06 xong. Detector được chỉnh trên mô phỏng `tuning` (mục 2), rồi config được `frozen` và đánh giá **một lần** trên mô phỏng `report` (mục 3). Theo yêu cầu rõ ràng của chủ dự án trong chat (2026-11-04), agent đặt `frozen` và chạy `make detect-report`. Config đã `frozen` được commit và push (`e331ec1`) **trước** khi chạy report.

## 1. Đã làm gì

| Task | Nội dung | Kiểm chứng |
| --- | --- | --- |
| D01 | 5 SQL view trong `infrastructure/database/002_kpi_views.sql`: KPI theo khung 15 phút cho từng provider và `ALL`, lỗi theo mã, payment mới theo phương thức. Khung trống vẫn có dòng. `make db-init` chạy mọi file schema theo thứ tự số | Test tích hợp so view với một cách tính độc lập bằng pandas: mọi số đếm khớp, p50/p95 khớp, không thiếu khung nào |
| D02 | `make kpi SIM=...` ghi Parquet vào `artifacts/kpi/<simulation_id>/` | Hai lần xuất cho file giống hệt từng byte, kể cả sau khi nạp lại vào một database mới; báo lỗi rõ nếu chưa nạp mô phỏng |
| D03 | Hai detector: **D-A** z-score bền vững (trung vị, MAD của 24 giờ trước), **D-B** gộp cửa sổ (z-score nhị thức cho tỷ lệ, trung bình có trọng số của log độ trễ) | Test trên chuỗi tự tạo: bắt bước nhảy đã biết, yên lặng ở phần còn lại; với cùng mức thay đổi, ít attempt hơn thì điểm D-B thấp hơn; trường hợp mất lưu lượng khớp số tính tay (7,2) |
| D04 | Gộp các khung cảnh báo liền nhau (khoảng trống ≤ 1 khung) thành sự cố, theo từng detector và đối tượng | Test gộp và tách trên ví dụ tự tạo |
| D05 | Đánh giá với nhãn, `make detect`, `make tune`, `make detect-plot` (`RUN_DIR`, `OUT`), `make detect-report` | Khớp một ví dụ tính tay; detector không import module đọc nhãn (kiểm tra AST) và đổi nhãn không đổi cảnh báo; `detect` từ chối mô phỏng `report`; `detect-report` từ chối config `draft` và từ chối chạy lại cùng hash |

Toàn bộ `make test` với PostgreSQL 16: **345 test pass**, không test nào bị bỏ qua. Độ phủ của `payment_reliability`: `evaluation.py`, `incidents.py`, `kpi.py` 100%, `detectors.py` 98%, `plots.py` 96%, `cli.py` 65% (phần còn lại là hàm `main`).

## 2. Kết quả trên mô phỏng `tuning`

Lần chạy `det-3ddc26cff253` trên `sim-485cacc9c858` (7 ngày, 25.573 payment, 4 bất thường đã cài). Config `detector.yaml` ở trạng thái `draft`, ngưỡng chọn bằng `make tune`.

> Đây là số trên chính dữ liệu dùng để chỉnh ngưỡng, nên lạc quan hơn thực tế. Số dùng cho báo cáo thực tập là số trên mô phỏng `report` ở mục 3.

### 2.1 Chọn tham số

`make tune` thử 9 ngưỡng cho D-A và 9 ngưỡng × 3 kích thước cửa sổ gộp (2, 4, 8 khung) cho D-B. Quy tắc chọn được viết trong code **trước khi chạy**:
1. bắt được nhiều bất thường nhất, đúng đối tượng;
2. với điều kiện báo nhầm không quá 1 sự cố mỗi ngày;
3. nếu hoà: độ trễ trung bình ngắn hơn, rồi đến ngưỡng cao hơn (thận trọng hơn).

| Detector | Tham số chọn | Bắt được | Báo nhầm / ngày | Độ trễ TB |
| --- | --- | --- | --- | --- |
| D-A z-score bền vững | ngưỡng 7 | 2/4 | 1,00 | 22,5 phút |
| D-B gộp cửa sổ | ngưỡng 8, gộp 2 khung (30 phút) | 3/4 | 0,00 | 15 phút |

**Có nhiều cấu hình D-B hoà nhau** (cùng bắt 3/4, không báo nhầm, độ trễ 15 phút) với ngưỡng 5 đến 8. Bộ tuning chỉ có 4 bất thường nên không đủ để phân biệt các cấu hình này. Quy tắc hoà chọn ngưỡng cao nhất.

### 2.2 Từng bất thường

| Bất thường | Đối tượng | D-A | D-B |
| --- | --- | --- | --- |
| `provider_outage` x4, 90 phút | `prov_002` | **Trượt** (điểm cao nhất 5,9 < 7) | Bắt, sau 15 phút |
| `latency_degradation` x3, 3 giờ | `prov_001` | Bắt, sau 15 phút | Bắt, sau 15 phút |
| `error_burst` x3, 45 phút | mọi provider | Bắt, sau 30 phút | Bắt, sau 15 phút |
| `provider_outage` **x1,5**, 2 giờ | `prov_001` | Trượt (điểm cao nhất 2,1) | Trượt (điểm cao nhất 1,6) |

<p align="center"><img src="../assets/results/stage-d-tuning.png" alt="KPI và điểm của hai detector quanh bốn bất thường trên mô phỏng tuning" width="100%"></p>

### 2.3 Đọc kết quả

- **D-B tốt hơn D-A rõ rệt**, đúng lý do được thiết kế. Ngoài các cửa sổ bất thường, điểm D-A lên tới 10 vào ban đêm, khi một khung chỉ có vài attempt và một lỗi là thành tỷ lệ 50%. Muốn ít báo nhầm thì D-A phải đặt ngưỡng cao, và khi đó trượt cả sự cố x4. D-B tính đến số attempt nên điểm ban đêm nhỏ (cao nhất 4,6 ngoài các cửa sổ bất thường), cho phép ngưỡng 8 mà vẫn bắt nhanh.
- **Không detector nào bắt được sự cố yếu x1,5**, và kết quả này giải thích được bằng tính tay. Theo config, tỷ lệ lỗi kỹ thuật của `prov_001` sẽ tăng từ khoảng 10,5% lên khoảng 18%. Gộp cả 2 giờ (khoảng 130 attempt), mức tăng đó chỉ bằng khoảng 2,8 lần độ dao động ngẫu nhiên. Trong lần mô phỏng này, do ngẫu nhiên, tỷ lệ thực tế trong cửa sổ chỉ là 15,0% (21 lỗi trên 140 attempt) so với 10,5% ở 24 giờ trước, tức khoảng 1,7 lần độ dao động. Cả hai mức đều thấp hơn nhiều so với ngưỡng 8 cần để không báo nhầm. Với lượng dữ liệu này, sự cố x1,5 nằm dưới ngưỡng phát hiện được. Hạ ngưỡng cũng không giúp: ở ngưỡng 3 với cửa sổ 8 khung, cảnh báo duy nhất trùng thời điểm lại ở `prov_002` (sai đối tượng), trong khi báo nhầm lên 0,86 lần mỗi ngày.
- **2 sự cố "sai đối tượng" của D-B** là tiếng vọng ở `ALL`: khi `prov_002` hỏng, tỷ lệ lỗi tổng cũng tăng. Chúng không bị tính là báo nhầm vì xảy ra đúng lúc có sự cố. Dashboard ở Stage F nên gộp cảnh báo `ALL` với cảnh báo provider cùng lúc.
- **Độ trễ 15 phút là mức nhỏ nhất có thể**: cảnh báo chỉ được đưa ra khi khung 15 phút đầu tiên của sự cố kết thúc.

## 3. Kết quả trên mô phỏng `report` (đánh giá một lần)

Lần chạy `det-08335c6af086` trên `sim-f6e6749ff0bf` (7 ngày, 25.151 payment, 4 bất thường; seed khác và có loại `traffic_drop` mà bộ tuning không có). Config `detector.yaml` đã `frozen`, cùng ngưỡng như mục 2.1, không chỉnh gì sau khi chạy. `artifacts/detect_report_runs.json` ghi một lần chạy duy nhất, không `--force`.

### 3.1 Tổng hợp

| Detector | Bắt được (đúng đối tượng) | Báo nhầm / ngày | Độ trễ TB | So với tuning |
| --- | --- | --- | --- | --- |
| D-A z-score bền vững | **0/4** | 2,00 (14 sự cố) | — | Tuning: 2/4, 1,00/ngày |
| D-B gộp cửa sổ | **2/4** | **0,00** | 22,5 phút | Tuning: 3/4, 0,00/ngày |

### 3.2 Từng bất thường

| Bất thường | Đối tượng | Điểm cao nhất D-A / D-B | D-A | D-B |
| --- | --- | --- | --- | --- |
| `provider_outage` x3, 60 phút | `prov_003` | 5,3 / 13,9 | Trượt | Bắt, sau 15 phút |
| `latency_degradation` x2,5, 2 giờ | `prov_002` | 6,0 / 12,7 | Trượt | Bắt, sau 30 phút |
| `traffic_drop` QR x5, 2 giờ (loại mới) | `QR` | 3,6 / 6,6 | Trượt | **Trượt** |
| `provider_outage` x1,5, 2 giờ | `prov_002` | 2,2 / 2,6 | Trượt | Trượt |

Ngưỡng: D-A 7, D-B 8. Ngoài các cửa sổ bất thường, điểm cao nhất là 9,4 với D-A và 3,8 với D-B.

<p align="center"><img src="../assets/results/stage-d-report.png" alt="KPI và điểm của hai detector quanh bốn bất thường trên mô phỏng report" width="100%"></p>

### 3.3 Đọc kết quả

- **Kết quả giảm từ tuning sang report**, giống Stage B (validation sang test). Một phần vì bộ report khó hơn có chủ đích: sự cố yếu hơn (x3 thay x4, x2,5 thay x3) và có một loại chưa gặp khi chỉnh.
- **D-B vẫn tốt hơn D-A rõ rệt.** D-B bắt cả hai sự cố về lỗi và độ trễ, không báo nhầm lần nào trong 7 ngày. D-A không bắt được gì nhưng báo nhầm 14 lần, **tất cả** trong khoảng 01:45–05:45 giờ Việt Nam, khi mỗi khung chỉ có vài attempt. Đây đúng là điểm yếu đã dự đoán ở đặc tả, mục 4.
- **D-B trượt `traffic_drop` dù sự cố nhìn bằng mắt rất rõ.** Tỷ trọng QR trong các payment mới rơi từ 44,0% (24 giờ trước) xuống 16,6%. Nhưng mỗi cửa sổ 30 phút chỉ có khoảng 110 payment mới, nên điểm D-B chỉ đạt 6,6, dưới ngưỡng 8. Ngưỡng 8 được chọn trên bộ tuning, nơi chỉ có sự cố về lỗi và độ trễ. Ngoài sự cố, điểm của chuỗi tỷ trọng thấp hơn các chuỗi khác (cao nhất 3,3 trên tuning), nên một ngưỡng riêng cho chuỗi này, khoảng 5, có lẽ đã bắt được [ước đoán]. Theo quy tắc đánh giá một lần, **không** chỉnh lại sau khi xem kết quả. Đổi ngưỡng theo từng loại KPI là một config mới, cần một bộ report mới để đánh giá.
- **Sự cố x1,5 vẫn dưới ngưỡng phát hiện**, giống tuning: điểm cao nhất 2,6.
- **1 sự cố "sai đối tượng"** của D-B là tiếng vọng ở `ALL` khi `prov_003` hỏng, như ở tuning. Không tính là báo nhầm.

### 3.4 Điều rút ra cho báo cáo thực tập

1. Một detector biết số attempt (D-B) quan trọng hơn việc chọn ngưỡng khéo: với cùng quy trình chỉnh, D-A tệ hơn ở mọi mặt.
2. Ngưỡng chỉnh trên một loại sự cố không tự chuyển sang loại khác. Đây là lý do cần bộ report có loại sự cố chưa gặp, và là bài học đáng nêu.
3. Có giới hạn phát hiện: với khoảng 150 payment/giờ, sự cố làm tỷ lệ lỗi tăng 1,5 lần không thể bắt được mà không báo nhầm nhiều.
4. Mọi kết luận dựa trên 4 + 4 sự cố tự cài, nên chỉ là ví dụ minh hoạ, không phải tỷ lệ phát hiện.

## 4. Lệch so với đặc tả

| Điểm | Đặc tả | Thực tế | Lý do |
| --- | --- | --- | --- |
| Chỉ số độ trễ cho detector | p50 hoặc p95 | Chỉ dùng p50 (trung vị); p95 có trong view nhưng không đưa vào detector | Với khoảng 12 attempt mỗi khung, p95 gần như là giá trị lớn nhất, rất nhiễu |
| Lệnh vẽ biểu đồ | Không nêu | Thêm `make detect-plot` | Cần cho task D06 |
| Code đánh giá trong CLI | Không nêu | `tune` và `detect` đều đọc nhãn, nhưng chỉ của mô phỏng `tuning` | Theo mục 7 của đặc tả: chỉ chỉnh trên `tuning` |

## 5. Hạn chế đã biết

- **Dữ liệu và bất thường đều do mình đặt.** Đây là kiểm chứng trên bất thường đã biết, không phải hiệu năng thực tế.
- **Bộ tuning nhỏ:** 4 bất thường. Số "3/4" có độ bất định rất lớn; nên đọc là danh sách từng trường hợp, không phải một tỷ lệ.
- **Giả định nhị thức của D-B** coi các attempt là độc lập. Retry của cùng một payment không hoàn toàn độc lập, nên điểm D-B có thể hơi cao hơn mức đúng.
- **Ngày đầu không có điểm:** detector cần ít nhất 12 giờ lịch sử, nên sự cố trong khoảng 12–24 giờ đầu của mô phỏng không thể bị phát hiện.
- **Một khung 15 phút là độ phân giải nhỏ nhất:** sự cố ngắn hơn 15 phút sẽ bị làm loãng.

## 6. Việc còn lại

| Việc | Ai | Ghi chú |
| --- | --- | --- |
| Thử `make up` và `make db-init` từ WSL | Chủ dự án | Kiểm chứng đến nay dùng PostgreSQL 16 tạm |
| Nếu muốn thử ngưỡng riêng cho từng loại KPI | Chủ dự án quyết | Là config mới; cần một bộ report mới (seed và sự cố khác), không dùng lại `sim-f6e6749ff0bf` |
| Dashboard đọc `incidents.json`, gộp cảnh báo `ALL` với cảnh báo provider cùng lúc | Stage F | Xong (2026-11-08): `fold_echoes` trong `shared/dashboard`, chỉ ở lớp hiển thị; `incidents.json` và đánh giá không đổi |
