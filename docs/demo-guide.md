# Hướng dẫn chạy và đọc demo

Trang này giải thích **chương trình làm gì ở từng bước**, chạy thế nào, và mở file nào để xem kết quả. Hai sản phẩm là hai pipeline độc lập ([ADR 0002](decisions/0002-product-boundaries.md)).

## 1. Product 01 — `make demo`

### 1.1 Cần gì

| Thứ | Vì sao | Kiểm tra |
| --- | --- | --- |
| Python + `uv` + `make` | Chạy code | `make lint` chạy được |
| **PostgreSQL 16** | KPI được tính bằng SQL view trong database ([ADR 0005](decisions/0005-kpi-layer-sql-views.md)) | `make demo` tự kiểm tra trước khi làm bất cứ gì |

Cách dễ nhất để có PostgreSQL là Docker Desktop:

```bash
copy .env.example .env
```

```bash
make up
```

(`copy` trong PowerShell; trong Git Bash dùng `cp`.) Lệnh `make up` bật một container `postgres:16` ở cổng 5432. Nếu cổng 5432 bị Windows chặn, sửa `POSTGRES_PORT=55432` trong `.env`.

Không có PostgreSQL thì `make demo` dừng ngay và in hướng dẫn, không chạy nửa chừng.

### 1.2 Luồng dữ liệu

```text
 demo.yaml (config, frozen)
     │  [1] sinh dữ liệu giả lập, có 4 sự cố cài sẵn
     ▼
 artifacts/simulations/sim-485cacc9c858/
     ├─ events.jsonl          30.050 sự kiện "một lần thử thanh toán đã xong"
     └─ anomaly_labels.json   đáp án: 4 sự cố ở đâu (detector KHÔNG được đọc)
     │  [2] tạo bảng   [3] nạp + kiểm tra contract
     ▼
 PostgreSQL: bảng payment_events
     │  [4] view SQL gom theo khung 15 phút
     ▼
 artifacts/kpi/sim-485cacc9c858/*.parquet   tỷ lệ lỗi, độ trễ, lưu lượng theo provider/mã lỗi/phương thức
     │  [5] hai detector so mỗi khung với 24 giờ trước đó
     ▼
 artifacts/detections/det-3ddc26cff253/
     ├─ incidents.json        các sự cố detector tìm ra
     └─ evaluation.json       so sự cố tìm ra với đáp án: bắt được mấy, trễ bao lâu, báo nhầm bao nhiêu
     │  [6] so với số đã công bố   [7] dựng trang HTML
     ▼
 artifacts/dashboard/index.html
```

### 1.3 Màn hình khi chạy thành công

```text
== Demo Product 01: độ ổn định thanh toán (dữ liệu giả lập, bộ tuning) ==
Kiểm tra PostgreSQL ...
PostgreSQL sẵn sàng.

[1/7] Sinh dữ liệu giả lập: 7 ngày, 3 provider, 20 merchant, 4 sự cố cài sẵn (demo.yaml)
      sim-485cacc9c858 -> ...\artifacts\simulations\sim-485cacc9c858
      → kết quả: artifacts/simulations/sim-485cacc9c858/ (events.jsonl, anomaly_labels.json)
[2/7] Tạo bảng và view KPI trong PostgreSQL (chạy lại nhiều lần vẫn an toàn)
[3/7] Nạp sự kiện vào PostgreSQL, kiểm tra từng dòng theo contract payment-event
      đọc 30050 dòng: 30050 dòng mới, 0 dòng đã có từ lần trước (bỏ qua), 0 dòng bị từ chối
[4/7] Tính KPI 15 phút bằng view SQL và xuất ra Parquet
[5/7] Chạy hai detector (D-A z-score, D-B gộp cửa sổ), gộp cảnh báo thành sự cố, chấm với nhãn
[6/7] So với số đã công bố cho bộ tuning
      D-B gộp cửa sổ (chính): bắt 3/4 sự cố, 0 báo nhầm/ngày (công bố: 3/4, 0)
      D-A z-score bền vững: bắt 2/4 sự cố, 1 báo nhầm/ngày (công bố: 2/4, 1)
      Khớp số đã công bố cho bộ tuning.
[7/7] Dựng dashboard HTML tĩnh cho cả hai sản phẩm
== Xong ==
Mở dashboard bằng trình duyệt: ...\artifacts\dashboard\index.html
```

Chạy lại lần hai: bước 3 báo "0 dòng mới, 30050 dòng đã có": nạp lại không tạo dữ liệu trùng.

### 1.4 Đọc kết quả

- **Dashboard** (`artifacts/dashboard/index.html`, mở bằng trình duyệt): phần Product 01 có ô số tổng, bảng theo provider, biểu đồ tỷ lệ lỗi và độ trễ theo giờ (vùng tô là sự cố), danh sách sự cố detector tìm ra, và bảng đối chiếu với đáp án.
- **`evaluation.json`**: với mỗi detector (`pooled` = D-B, `robust_z` = D-A), mỗi sự cố cài sẵn có `detected` (bắt được chưa), `delay_minutes` (bắt sau bao nhiêu phút), cùng `false_per_day` (số sự cố báo nhầm mỗi ngày).
- **Sự cố bị trượt là bình thường**: sự cố yếu x1,5 nằm dưới giới hạn phát hiện, có chủ đích ([báo cáo Stage D](architecture/stage-d-report.md)).

### 1.5 Vì sao demo dùng bộ "tuning"

Có hai bộ mô phỏng. Bộ **tuning** dùng để chọn ngưỡng detector, chạy lại thoải mái. Bộ **report** chỉ được đánh giá **một lần** (`det-08335c6af086`: D-B 2/4) để con số đó trung thực, nên demo không bao giờ chạy lại nó.

## 2. Product 02 — `make score-model` và `make score`

Cần dataset IEEE-CIS trong `datasets/raw/ieee-cis/` (không cần PostgreSQL).

```text
 train_transaction.csv (IEEE-CIS)
     │  make score-model: chia theo thời gian, bỏ phần test, học Gradient Boosting trên train,
     │                    hiệu chỉnh xác suất trên khối V1 của validation
     ▼
 artifacts/models/score-19e94be9616d/
     ├─ scorer.pkl          mô hình + bộ hiệu chỉnh
     ├─ model_card.json     đặc trưng, tham số, mốc thời gian không được vượt
     └─ sample_v3.csv       2.000 giao dịch validation, ĐÃ BỎ cột nhãn (đầu vào mẫu)
     │  make score [INPUT=file.csv]
     ▼
 artifacts/scores/exec-….csv    TransactionID, score, score_calibrated, model_version, feature_version, execution_id
 artifacts/scores/exec-….json   tóm tắt + kiểm tra lệch: điểm theo lô so với điểm lúc huấn luyện
```

`score` là điểm gốc (chỉ dùng để xếp hạng; bị thổi lên khoảng 7 lần). `score_calibrated` đọc được gần như xác suất. Bộ chấm điểm từ chối file có cột `isFraud` hoặc có giao dịch thuộc giai đoạn test.

## 3. Lỗi thường gặp

| Thấy | Nghĩa | Làm gì |
| --- | --- | --- |
| `Không kết nối được PostgreSQL` | Chưa bật database | `make up` (cần Docker Desktop đang chạy) |
| `docker not found` | Chưa cài Docker | Cài Docker Desktop, hoặc dùng PostgreSQL có sẵn qua `.env` |
| `MISMATCH` ở bước 6 | Kết quả khác số đã công bố | Báo lại, kèm `artifacts/detections/det-3ddc26cff253/evaluation.json` |
| Phần Product 02 trên dashboard trống | Máy chưa có `artifacts/runs/` | Chạy `make baseline`, `make gbm` (cần dataset); số test chỉ có trên máy chủ dự án |
