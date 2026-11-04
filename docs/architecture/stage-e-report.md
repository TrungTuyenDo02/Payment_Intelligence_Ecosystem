# Báo cáo Stage E — Thí nghiệm rò rỉ dữ liệu và Gradient Boosting

- **Ngày:** 2026-11-04 (tuần 5 của lịch 6 tuần)
- **Đặc tả:** [`stage-e-spec.md`](stage-e-spec.md), [ADR 0006](../decisions/0006-gradient-boosting-sklearn.md).
- **Trạng thái:** E01–E04 xong code và test trên dữ liệu tổng hợp. **Chưa có số trên IEEE-CIS**: dataset chỉ có trên máy chủ dự án. Mục 2 và 3 sẽ được điền sau khi chủ dự án chạy `make leakage` và `make gbm` (mục 4).

## 1. Đã làm gì

| Task | Nội dung | Kiểm chứng (trên fixture tổng hợp) |
| --- | --- | --- |
| E01 | `gap_days` trong `time_split` và config | Bỏ đúng các dòng cuối train, validation và test không đổi; `gap_days = 0` giữ nguyên mốc split nên mã lần chạy của baseline đã chốt không đổi |
| E02 | Thực thể lặp lại; mã hoá theo nhãn, có bản ngoài fold | Khớp ví dụ tính tay; không đọc nhãn test; mã hoá ngoài fold không dùng nhãn của chính dòng |
| E03 | `make leakage`: 7 biến thể, chỉ trên validation | Mọi biến thể chấm cùng số dòng validation; đảo nhãn test không đổi kết quả; test T10 chỉ cho phép `random_split` ở `split.py` và file thí nghiệm |
| E04 | `make gbm`, `make gbm-final` | Fit trên train, chọn trên validation; hai lần chạy cho `metrics.json` giống hệt; `gbm-final` từ chối config `draft` và từ chối chạy lại |

Thời gian chạy đo trên dữ liệu tổng hợp cùng kích thước IEEE-CIS (590.540 dòng): thí nghiệm rò rỉ khoảng 70 giây, mỗi điểm lưới Gradient Boosting tối đa khoảng 6 giây, chưa tính thời gian đọc CSV.

**Kiểm tra cơ chế trên fixture** (3.000 dòng tổng hợp, không có ý nghĩa về gian lận thật): mã hoá `card1` bằng nhãn validation đẩy PR-AUC validation từ 0,168 lên 0,967; mã hoá đúng cách cho 0,166. Đây chỉ chứng minh code phát hiện được rò rỉ, không phải kết quả của đề tài.

## 2. Thí nghiệm rò rỉ trên IEEE-CIS

*Chưa chạy.* Sau `make leakage`, chép bảng trong `artifacts/experiments/leak-<hash>/summary.md` vào đây, kèm run id.

## 3. Gradient Boosting trên IEEE-CIS

*Chưa chạy.* Bảng dự kiến:

| Mô hình | PR-AUC validation | PR-AUC test | Recall @ FPR 5% (test) | Lần chạy |
| --- | --- | --- | --- | --- |
| Luật (Stage B) | 0,089 | 0,078 | 0,22 | `run-d6faa4699008` |
| Logistic Regression (Stage B) | 0,245 | 0,165 | 0,28 | `run-d6faa4699008` |
| Gradient Boosting | *chờ `make gbm`* | *chờ `make gbm-final`* | | |

## 4. Việc chủ dự án cần làm (trên máy có dataset)

1. `make leakage`, rồi gửi `summary.md` và `results.json`.
2. `make gbm`, rồi gửi `metrics.json` và `models.json` của thư mục run.
3. Nếu đồng ý với kết quả validation: đặt `status: frozen` trong `projects/fraud-risk/configs/gbm.yaml`, commit và push, **rồi mới** chạy `make gbm-final` một lần.

## 5. Kiểm tra trong môi trường của agent

- `make lint`: pass.
- `make test` với PostgreSQL 16 tạm: **364 test pass**, không test nào bị bỏ qua. Độ phủ toàn repo 94%.
