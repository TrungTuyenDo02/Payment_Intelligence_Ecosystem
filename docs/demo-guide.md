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

(`copy` trong PowerShell/cmd; trong Git Bash dùng `cp`. `make` chạy được từ cả ba: trên Windows nó tự dùng bash đi kèm Git for Windows.) Lệnh `make up` bật một container `postgres:16` ở cổng 5432. Nếu cổng 5432 bị Windows chặn, sửa `POSTGRES_PORT=55432` trong `.env`.

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

`make demo` chạy **cả hai sản phẩm** (Product 02 chỉ khi máy có dataset). Mỗi bước in một dòng tiến độ: thanh %, sản phẩm đang chạy, bước mấy trên mấy. Xong mỗi sản phẩm là bảng kết quả, cuối cùng là danh sách kiểm tra ✓/✗:

```text
=== Product 01 — Payment Reliability (dữ liệu thanh toán giả lập) ===
[░░░░░░░░░░░░░░░░░░░░░░░░]   0% | Product 01 | bước 1/6: Sinh dữ liệu giả lập: 7 ngày, 3 provider, 20 merchant, 4 sự cố cài sẵn
      ✓ xong trong 6 giây → artifacts/simulations/sim-485cacc9c858/
[███░░░░░░░░░░░░░░░░░░░░░]  12% | Product 01 | bước 2/6: Tạo bảng và view KPI trong PostgreSQL
[██████░░░░░░░░░░░░░░░░░░]  25% | Product 01 | bước 3/6: Nạp sự kiện vào PostgreSQL, kiểm tra từng dòng theo contract payment-event
[█████████░░░░░░░░░░░░░░░]  38% | Product 01 | bước 4/6: Tính KPI 15 phút bằng view SQL, xuất Parquet
[████████████░░░░░░░░░░░░]  50% | Product 01 | bước 5/6: Chạy hai detector (D-A z-score, D-B gộp cửa sổ), gộp cảnh báo thành sự cố
[███████████████░░░░░░░░░]  62% | Product 01 | bước 6/6: Dựng dashboard HTML cho cả hai sản phẩm

--- Kết quả Product 01 ---
Nạp: 30050 sự kiện; 30050 mới, 0 đã có từ lần trước, 0 bị từ chối
Sự cố cài sẵn                                D-B (chính)            D-A (đường cơ sở)
anom-01 provider_outage x4 (prov_002)        ✓ bắt, sau 15 phút     ✗ trượt
anom-02 latency_degradation x3 (prov_001)    ✓ bắt, sau 15 phút     ✓ bắt, sau 15 phút
anom-03 error_burst x3 (NETWORK_ERROR)       ✓ bắt, sau 15 phút     ✓ bắt, sau 30 phút
anom-04 provider_outage x1,5 (prov_001)      ✗ trượt                ✗ trượt
D-B: bắt 3/4 sự cố, 0,0 báo nhầm/ngày
D-A: bắt 2/4 sự cố, 1,0 báo nhầm/ngày

=== Product 02 — Fraud & Risk (IEEE-CIS, chỉ dữ liệu phát triển) ===
[██████████████████░░░░░░]  75% | Product 02 | bước 1/2: Huấn luyện bộ chấm điểm: Gradient Boosting trên train, hiệu chỉnh Platt trên V1
      ✓ xong trong 20 giây → artifacts/models/score-…/
[█████████████████████░░░]  88% | Product 02 | bước 2/2: Chấm điểm 2.000 giao dịch validation không nhãn (sample_v3.csv)

--- Kết quả Product 02 ---
Xác suất gian lận trung bình (đã hiệu chỉnh): 0,037; ≥ 0,5: 22 giao dịch
5 giao dịch rủi ro nhất (để minh hoạ, không phải quyết định chặn):
  TransactionID  TransactionAmt ProductCD  Điểm gốc  Xác suất
  3421982                100,00 R             0,999     0,987
  ...

[████████████████████████] 100% | Kiểm tra
  ✓ Mọi sự kiện qua kiểm tra contract (0 dòng bị từ chối)
  ✓ D-B gộp cửa sổ (chính) khớp số công bố (3/4, 0 báo nhầm/ngày)
  ✓ D-A z-score bền vững khớp số công bố (2/4, 1 báo nhầm/ngày)
  ✓ Dashboard đã dựng
  ✓ Mô hình tái tạo PR-AUC validation của Stage E (kiểm tra lúc huấn luyện)
  ✓ Đầu vào chấm điểm không có cột nhãn isFraud
  ✓ Điểm theo lô trùng điểm lúc huấn luyện (2000 dòng, chênh lớn nhất 0,0)

Tổng kết: 7/7 kiểm tra đạt
```

Đọc nhanh:

- **Bảng Product 01**: mỗi dòng là một sự cố cài sẵn trong dữ liệu giả lập; cột D-B, D-A cho biết detector có bắt được không và sau bao lâu. Sự cố x1,5 bị trượt là có chủ đích (nằm dưới giới hạn phát hiện).
- **Bảng Product 02**: "Điểm gốc" chỉ dùng để xếp hạng (bị thổi lên khoảng 7 lần); "Xác suất" là điểm đã hiệu chỉnh. Danh sách 5 giao dịch chỉ để minh hoạ.
- **Danh sách kiểm tra**: ✓ là đạt, ✗ là không đạt (lệnh trả mã lỗi 1), – là phần bị bỏ qua (thiếu PostgreSQL hoặc dataset; mã lỗi 2 nếu anh yêu cầu đúng phần đó).
- Chạy lại lần hai: dòng "Nạp" báo "0 mới, 30050 đã có": nạp lại không tạo dữ liệu trùng.
- Chỉ một sản phẩm: `make demo PRODUCT=01` hoặc `make demo PRODUCT=02`.

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
| `'{' is not recognized` hoặc `The system cannot find the path specified` | `make` không tìm thấy bash (bản Makefile cũ, hoặc máy chưa có Git for Windows) | Cập nhật repo; cài Git for Windows |
| ✗ ở dòng "khớp số công bố" | Kết quả khác số đã công bố | Báo lại, kèm `artifacts/detections/det-3ddc26cff253/evaluation.json` |
| Phần Product 02 trên dashboard trống | Máy chưa có `artifacts/runs/` | Chạy `make baseline`, `make gbm` (cần dataset); số test chỉ có trên máy chủ dự án |
