# Báo cáo Stage C — Bộ sinh dữ liệu giả lập và ingestion

- **Ngày:** 2026-11-04 (tuần 3 của lịch 6 tuần)
- **Đặc tả:** [`stage-c-spec.md`](stage-c-spec.md) (đã duyệt 2026-11-04). **Giả định chi tiết:** [`shared/synthetic-generator/README.md`](../../shared/synthetic-generator/README.md).
- **Trạng thái:** C01–C05 xong. Test tích hợp PostgreSQL đã chạy ngày 2026-11-04 trên một container `postgres:16` tạm (xem mục 2.1).

## 1. Đã làm gì

| Task | Nội dung | Kiểm chứng |
| --- | --- | --- |
| C01 | Config có kiểu (pydantic, từ chối trường lạ), `simulation_id` tất định | 34 test: ID không đổi khi đổi `status`, thứ tự key hay ghi rõ giá trị mặc định; đổi bất kỳ tham số, seed hay phiên bản generator thì ID đổi; 21 kiểu config sai bị từ chối |
| C02 | Sinh sự kiện theo luật, `make simulate` | 100% sự kiện qua `validate_event`; ID không trùng; đủ 5 quy tắc giữa attempt; tỷ lệ phương thức, lỗi, provider và đổi provider khớp config trên mẫu khoảng 60 nghìn payment; hai lần chạy giống hệt từng byte |
| C03 | Chèn 4 loại bất thường, ground truth tách riêng, config `tuning` và `report` | Payment ngoài mọi cửa sổ giống hệt lần chạy không bất thường; trong cửa sổ, chỉ số đổi đúng hướng và đúng độ lớn; sự kiện chỉ có trường của contract; ID payment không có khoảng trống |
| C04 | Schema PostgreSQL, `make db-init`, `make ingest` | 15 test không cần database (quy tắc giữa attempt, từ chối cả payment, dòng hỏng, sai `simulation_id`, ID trùng, checksum sai) và 3 test database (nạp, nạp lại, lưu lý do từ chối, từ chối file đã đổi) đều pass. Test database tự bỏ qua kèm lý do khi không có PostgreSQL |
| C05 | README mô tả mọi giả định, báo cáo này | — |

Toàn bộ `make test` khi có PostgreSQL: 318 test pass (sau sửa đổi A1, A2). Độ phủ test: `config.py` và `generator.py` 100%, `cli.py` 98%, `ingest.py` 91% (phần còn lại là hàm `main` của CLI).

## 2. Kết quả trên hai config

Cập nhật 2026-11-04 sau sửa đổi A1 (150 payment/giờ) và A2 (thêm sự cố yếu x1,5) của đặc tả, mục 10. Chạy với generator 0.2.0, numpy 2.5.4. Hai lần chạy trước sửa đổi (`sim-30fb2cffe123`, `sim-37237f17e79a`, khoảng 5 nghìn payment mỗi lần) không còn dùng.

| Chỉ số | `demo.yaml` (tuning) | `report.yaml` (report) |
| --- | --- | --- |
| `simulation_id` | `sim-485cacc9c858` | `sim-f6e6749ff0bf` |
| Payment / sự kiện | 25.573 / 30.050 | 25.151 / 29.340 |
| Payment có retry | 15,0% | 14,3% |
| Thành công ngay lần đầu | 77,1% | 77,6% |
| Thành công sau cùng (kể cả retry) | 89,9% | 90,1% |
| Tỷ lệ lỗi theo attempt (prov_001 / 002 / 003) | 15,5% / 23,9% / 30,9% | 15,1% / 22,0% / 30,6% |
| Độ trễ (không tính TIMEOUT), trung vị / p95 | 579 / 1.509 ms | 582 / 1.522 ms |
| Tỷ trọng QR / E_WALLET / CARD / BANK_TRANSFER | 45,1 / 24,9 / 20,1 / 10,0% | 44,4 / 25,1 / 20,5 / 10,0% |
| Bất thường | 4 (outage, latency, error burst, **outage yếu x1,5**) | 4 (outage, latency, **traffic drop**, **outage yếu x1,5**) |

Tỷ lệ lỗi theo provider bao gồm cả ảnh hưởng của bất thường, nên lệch nhẹ so với config (15 / 22 / 30%). Cách tính các chỉ số trên cho ra đúng các số của lần chạy cũ khi áp dụng lên config cũ, nên hai bảng so sánh được với nhau.

### 2.1 Nạp vào PostgreSQL

Chạy `make db-init`, nạp hai simulation, rồi nạp lại `sim-485cacc9c858` một lần nữa:

| Lần nạp | `simulation_id` | Đọc | Nhận mới | Trùng (đã có) | Từ chối |
| --- | --- | --- | --- | --- | --- |
| 1 | `sim-485cacc9c858` | 30.050 | 30.050 | 0 | 0 |
| 2 | `sim-f6e6749ff0bf` | 29.340 | 29.340 | 0 | 0 |
| 3 (nạp lại) | `sim-485cacc9c858` | 30.050 | 0 | 30.050 | 0 |

Bảng `payment_events` có đúng 30.050 + 29.340 dòng, với 25.573 và 25.151 payment khác nhau; `ingestion_rejects` rỗng. Lần nạp lại không thêm dòng nào.

**Cách chạy lần này:** một cụm PostgreSQL 16 tạm trong môi trường phát triển của agent, cổng 55432 trên `127.0.0.1`, kết nối bằng `POSTGRES_HOST` và `POSTGRES_PORT`. Toàn bộ `make test` với database này: 318 test pass, không test nào bị bỏ qua. Lần chạy trước sửa đổi dùng một container `postgres:16` tạm khởi động từ Windows. Đường chạy chuẩn `make up` (cổng 5432 trên `127.0.0.1`) vẫn chưa được thử từ WSL.

## 3. Lệch so với đặc tả

| Điểm | Đặc tả | Thực tế | Lý do |
| --- | --- | --- | --- |
| Quy mô demo | 30 payment/giờ, khoảng 6 nghìn sự kiện | 150 payment/giờ, 30.050 sự kiện | Sửa đổi A1 của đặc tả (chủ dự án, 2026-11-04): đủ attempt cho KPI 15 phút theo provider. Test cho phép 27.500–32.500 sự kiện |
| Vị trí code ingestion | Không nêu | `shared/synthetic-generator/synthetic_generator/ingest.py` | Tránh thêm package mới (quyết định 10); có thể tách ra khi Stage D cần |
| Provider của attempt đầu | Không nêu | Phân phối đều | Đơn giản nhất; config chưa có trọng số provider |
| Mẫu báo cáo | Mục 12 của `AGENTS.md` | Theo cấu trúc của file này | `AGENTS.md` không có trên máy phát triển |

## 4. Hạn chế đã biết

- **Dữ liệu hoàn toàn giả định.** Mọi tham số do agent và chủ dự án đặt, không học từ dữ liệu thật. Tỷ lệ lỗi được cố ý để cao. Báo cáo Stage D phải gọi kết quả là "kiểm chứng trên bất thường đã biết", không phải hiệu năng thực tế (rủi ro 2 trong tổng quan).
- **Phần lớn bất thường dễ thấy.** Ba trong bốn sự cố mỗi config có độ lớn x2,5–x5. Đã thêm một sự cố yếu x1,5 mỗi config (sửa đổi A2). Mỗi config chỉ có một sự cố yếu, nên kết quả trên nó là một ví dụ, không phải một tỷ lệ phát hiện.
- **Byte-identical phụ thuộc phiên bản numpy.** Manifest ghi `numpy_version`; đổi numpy có thể đổi dữ liệu dù cùng `simulation_id`.
- **Quy tắc giữa attempt chỉ kiểm tra trong một file.** Nạp hai simulation khác nhau không thể trùng payment vì ID mang tag của simulation, nhưng ingestion không kiểm tra chéo giữa các file.
- **`make up` từ WSL chưa được thử**, vì WSL integration của Docker Desktop chưa bật (mục 2.1).

## 5. Việc còn lại

| Việc | Ai | Ghi chú |
| --- | --- | --- |
| Bật WSL integration cho Ubuntu trong Docker Desktop, rồi thử `make up` và `make db-init` | Chủ dự án, agent | Không chặn Stage D; code đã kiểm chứng trên PostgreSQL 16 |
| Duyệt các giả định trong README generator và kịch bản bất thường | Chủ dự án | Trước khi `frozen` |
| Đặt `status: frozen` cho `demo.yaml` và `report.yaml` | Chủ dự án | Bắt buộc trước khi chỉnh detector ở Stage D (đặc tả mục 4) |
