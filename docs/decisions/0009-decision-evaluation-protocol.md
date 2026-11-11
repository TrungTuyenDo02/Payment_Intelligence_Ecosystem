# ADR 0009 — Protocol đánh giá quyết định trên dữ liệu phát triển

- **Trạng thái:** Accepted (chủ dự án duyệt D1–D8 của đặc tả Stage G và đồng ý chuyển ADR sang Accepted trong chat ngày 2026-11-11)
- **Phạm vi:** Stage G (G03 hiệu chỉnh, G04 chính sách, G05 độ ổn định), [đặc tả Stage G](../architecture/stage-g-spec.md)

## Bối cảnh

Stage E báo chất lượng xếp hạng (PR-AUC test 0,408, recall tại FPR 5% là 0,51). Recall tại FPR 5% chọn ngưỡng bằng nhãn của chính tập được đánh giá, nên không phải hiệu quả của một ngưỡng đã chốt trước (ngưỡng 0,853 chốt trên validation cho recall test 0,371). Muốn nói về **quyết định** (hiệu chỉnh, ngưỡng theo chi phí, ngân sách duyệt) thì cần dữ liệu để fit, dữ liệu để chọn và dữ liệu để đánh giá, tách nhau theo thời gian.

Tập test đã dùng một lần (`run-f8807cb6f780`, `run-d6faa4699008`) và bị khoá bởi quy tắc test-một-lần. Validation (118.108 dòng, 4.611 gian lận, 41 ngày) đã dùng cho lưới GBM, thí nghiệm rò rỉ và ADR 0008.

| Phương án | Ưu điểm | Nhược điểm |
| --- | --- | --- |
| **A. Chia validation theo thời gian thành V1 (hiệu chỉnh) / V2 (chọn) / V3 (đánh giá), thêm cửa sổ cuốn chiếu theo tuần làm độ nhạy** | Không chạm test; vai trò mỗi khối rõ, kiểm thử được; đủ gian lận mỗi khối (1,3–1,7 nghìn) | Validation đã dùng nhiều lần, kết quả có thể lạc quan; khối nhỏ, khoảng tin cậy rộng |
| B. Dùng lại tập test để đánh giá chính sách | Dữ liệu chưa dùng để chọn mô hình | Vi phạm quy tắc test-một-lần; con số test 0,408 mất tính không thiên lệch |
| C. Cross-validation theo thời gian trên train + validation, fit lại mô hình mỗi fold | Nhiều điểm đánh giá hơn | Đổi cách huấn luyện mô hình chính (ngoài phạm vi); tốn thời gian; vẫn dùng validation |
| D. Hai khối (hiệu chỉnh và chọn cùng một khối) | Khối lớn hơn | Hiệu chỉnh và chọn ngưỡng trên cùng nhãn: ước lượng chọn ngưỡng lạc quan |

## Quyết định

Chọn **A** (chi tiết ở đặc tả Stage G mục 2–7):

- Mô hình GBM cố định theo `run-f8807cb6f780`, fit trên train, không quét lại lưới.
- V1 = ngày 101–113, V2 = 114–126, V3 = 127–141 (`TransactionDT // 86400`). Nhãn V3 không được dùng để fit hay chọn.
- Bốn cửa sổ cuốn chiếu theo tuần (hiệu chỉnh tuần k, chọn tuần k+1, đánh giá tuần k+2) là phân tích độ nhạy, không phải kết quả chính.
- Config đăng ký trước, `status: draft`, commit trước lần chạy đầu tiên có số V3; bảng V3 báo toàn bộ lưới.
- Code lọc bỏ mọi dòng sau mốc validation trước khi đọc nhãn; có test chứng minh đổi các dòng đó không đổi output.
- Mọi kết quả ghi là "thăm dò".

## Hệ quả

- Không thêm thư viện; không đổi `gbm.yaml`, `baseline.yaml` hay sổ test-một-lần.
- Stage G **không** cho ước lượng không thiên lệch của hiệu quả chính sách; báo cáo phải nói rõ điều này.
- Muốn có ước lượng không thiên lệch cần dữ liệu mới, chưa dùng (không có trong IEEE-CIS ngoài tập test đã dùng); đó là quyết định ngoài Stage G.
