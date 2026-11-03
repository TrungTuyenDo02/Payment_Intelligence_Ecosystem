# Báo cáo Stage C — Bộ sinh dữ liệu giả lập và ingestion

- **Ngày:** 2026-11-04 (tuần 3 của lịch 6 tuần)
- **Đặc tả:** [`stage-c-spec.md`](stage-c-spec.md) (đã duyệt 2026-11-04). **Giả định chi tiết:** [`shared/synthetic-generator/README.md`](../../shared/synthetic-generator/README.md).
- **Trạng thái:** C01–C03 và C05 xong. C04 xong phần code và test không cần database; **3 test tích hợp PostgreSQL chưa chạy** (Docker Desktop chưa bật trên máy phát triển).

## 1. Đã làm gì

| Task | Nội dung | Kiểm chứng |
| --- | --- | --- |
| C01 | Config có kiểu (pydantic, từ chối trường lạ), `simulation_id` tất định | 34 test: ID không đổi khi đổi `status`, thứ tự key hay ghi rõ giá trị mặc định; đổi bất kỳ tham số, seed hay phiên bản generator thì ID đổi; 21 kiểu config sai bị từ chối |
| C02 | Sinh sự kiện theo luật, `make simulate` | 100% sự kiện qua `validate_event`; ID không trùng; đủ 5 quy tắc giữa attempt; tỷ lệ phương thức, lỗi, provider và đổi provider khớp config trên mẫu khoảng 60 nghìn payment; hai lần chạy giống hệt từng byte |
| C03 | Chèn 4 loại bất thường, ground truth tách riêng, config `tuning` và `report` | Payment ngoài mọi cửa sổ giống hệt lần chạy không bất thường; trong cửa sổ, chỉ số đổi đúng hướng và đúng độ lớn; sự kiện chỉ có trường của contract; ID payment không có khoảng trống |
| C04 | Schema PostgreSQL, `make db-init`, `make ingest` | 15 test không cần database (quy tắc giữa attempt, từ chối cả payment, dòng hỏng, sai `simulation_id`, ID trùng, checksum sai). 3 test database (nạp, nạp lại, lưu lý do từ chối, từ chối file đã đổi) **tự bỏ qua** khi không có PostgreSQL |
| C05 | README mô tả mọi giả định, báo cáo này | — |

Toàn bộ `make lint test`: 313 test pass, 3 bỏ qua (PostgreSQL). Độ phủ test: `config.py` và `generator.py` 100%, `cli.py` 98%, `ingest.py` 79% (phần ghi database chưa chạy).

## 2. Kết quả trên hai config

Chạy với generator 0.2.0, numpy 2.5.4.

| Chỉ số | `demo.yaml` (tuning) | `report.yaml` (report) |
| --- | --- | --- |
| `simulation_id` | `sim-30fb2cffe123` | `sim-37237f17e79a` |
| Payment / sự kiện | 4.945 / 5.766 | 5.020 / 5.827 |
| Payment có retry | 14,5% | 13,9% |
| Thành công ngay lần đầu | 77,6% | 77,5% |
| Thành công sau cùng (kể cả retry) | 89,9% | 89,7% |
| Tỷ lệ lỗi theo attempt (prov_001 / 002 / 003) | 15,4% / 23,3% / 29,8% | 14,6% / 22,2% / 30,9% |
| Độ trễ (không tính TIMEOUT), trung vị / p95 | 590 / 1.497 ms | 585 / 1.506 ms |
| Tỷ trọng QR / E_WALLET / CARD / BANK_TRANSFER | 44,9 / 25,2 / 20,2 / 9,6% | 44,5 / 24,7 / 20,7 / 10,1% |
| Bất thường | 3 (outage, latency, error burst) | 3 (outage, latency, **traffic drop**) |

Tỷ lệ lỗi theo provider bao gồm cả ảnh hưởng của bất thường, nên lệch nhẹ so với config (15 / 22 / 30%).

## 3. Lệch so với đặc tả

| Điểm | Đặc tả | Thực tế | Lý do |
| --- | --- | --- | --- |
| Số sự kiện demo | Khoảng 6 nghìn | 5.766 | Chủ dự án chọn tăng tỷ lệ lỗi và retry (2026-11-04); con số này nằm trong khoảng test cho phép 5.500–6.500 |
| Vị trí code ingestion | Không nêu | `shared/synthetic-generator/synthetic_generator/ingest.py` | Tránh thêm package mới (quyết định 10); có thể tách ra khi Stage D cần |
| Provider của attempt đầu | Không nêu | Phân phối đều | Đơn giản nhất; config chưa có trọng số provider |
| Mẫu báo cáo | Mục 12 của `AGENTS.md` | Theo cấu trúc của file này | `AGENTS.md` không có trên máy phát triển |

## 4. Hạn chế đã biết

- **Dữ liệu hoàn toàn giả định.** Mọi tham số do agent và chủ dự án đặt, không học từ dữ liệu thật. Tỷ lệ lỗi được cố ý để cao. Báo cáo Stage D phải gọi kết quả là "kiểm chứng trên bất thường đã biết", không phải hiệu năng thực tế (rủi ro 2 trong tổng quan).
- **Bất thường dễ thấy.** Độ lớn x3–x5 trong cửa sổ 45 phút đến 3 giờ. Detector có thể đạt điểm cao một cách dễ dàng (Wu và Keogh, tổng quan 7.2). Nên thêm kịch bản yếu hơn (x1,5) trước khi báo cáo Stage D.
- **Byte-identical phụ thuộc phiên bản numpy.** Manifest ghi `numpy_version`; đổi numpy có thể đổi dữ liệu dù cùng `simulation_id`.
- **Quy tắc giữa attempt chỉ kiểm tra trong một file.** Nạp hai simulation khác nhau không thể trùng payment vì ID mang tag của simulation, nhưng ingestion không kiểm tra chéo giữa các file.
- **Phần ghi PostgreSQL chưa được chạy thật.** Xem mục 5.

## 5. Việc còn lại

| Việc | Ai | Ghi chú |
| --- | --- | --- |
| Bật Docker Desktop và WSL integration cho Ubuntu | Chủ dự án | Cài đặt trên máy cá nhân |
| Chạy `make up`, `make db-init`, `make test` và nạp hai simulation | Agent | Hoàn tất nghiệm thu C04 |
| Duyệt các giả định trong README generator và kịch bản bất thường | Chủ dự án | Trước khi `frozen` |
| Đặt `status: frozen` cho `demo.yaml` và `report.yaml` | Chủ dự án | Bắt buộc trước khi chỉnh detector ở Stage D (đặc tả mục 4) |
