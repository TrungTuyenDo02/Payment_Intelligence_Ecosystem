# Báo cáo Stage G — Từ xếp hạng đến quyết định (Product 02)

- **Đặc tả:** [stage-g-spec.md](stage-g-spec.md) (đã duyệt 2026-11-11), [ADR 0009](../decisions/0009-decision-evaluation-protocol.md).
- **Mọi kết quả ở đây là "thăm dò"**: chỉ dùng train + validation, mà validation đã bị dùng cho lưới GBM, thí nghiệm rò rỉ và đặc trưng lịch sử. Tập test **không** được nạp ở bước nào.
- Môi trường các lần chạy: Python 3.12.10, scikit-learn 1.9.1, pandas 3.1.0, numpy 2.5.4, Windows 11.

## Khối validation (chung cho G03–G05)

| Khối | Vai trò | Ngày | Dòng | Gian lận | Tỷ lệ |
| --- | --- | --- | --- | --- | --- |
| V1 | Hiệu chỉnh | 101–113 | 38.426 | 1.523 | 3,96% |
| V2 | Chọn | 114–126 | 41.426 | 1.741 | 4,20% |
| V3 | Đánh giá | 127–141 | 38.256 | 1.347 | 3,52% |

Mô hình cố định (không quét lại lưới) tái tạo đúng Stage E: PR-AUC validation GBM 0,4970, Logistic Regression 0,2454 (Stage E: 0,497 và 0,245).

## G03 — Hiệu chỉnh xác suất (`cal-04b3ad5944ce`)

Lệnh: `make calibration`. Config: [`calibration.yaml`](../../projects/fraud-risk/configs/calibration.yaml) (`draft`). Kết quả đầy đủ trong `artifacts/experiments/cal-04b3ad5944ce/summary.md`.

**Câu hỏi.** Hai mô hình học với `class_weight="balanced"`, tức là coi gian lận nặng gấp khoảng 28 lần giao dịch thường. Điểm số vì vậy không đọc được như xác suất. Điều này không ảnh hưởng chuyện xếp hạng, nhưng quan trọng khi đặt ngưỡng theo chi phí (G04): ở đó cần "xác suất giao dịch này là gian lận".

**Ba cách** (bộ hiệu chỉnh chỉ fit trên V1, chọn trên V2 theo log loss, báo trên V3):

- **Gốc:** dùng điểm như cũ.
- **Dịch tiên nghiệm:** cộng `log(π / (1 − π))` vào logit, với π = 3,38% là tỷ lệ gian lận của train. Cách này hoàn tác đúng trọng số cân bằng nếu mô hình đúng dạng, và không cần nhãn mới.
- **Sigmoid (Platt):** hồi quy logistic trên logit của điểm, fit bằng nhãn V1.

| Mô hình | Phương pháp | Brier V2 | Log loss V2 | Brier V3 | Log loss V3 | Xác suất TB V3 | Tỷ lệ thật V3 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| GBM | Gốc | 0,1095 | 0,3632 | 0,1037 | 0,3511 | 0,2610 | 0,0352 |
| GBM | Dịch tiên nghiệm | 0,0259 | 0,1082 | 0,0259 | 0,1095 | 0,0270 | 0,0352 |
| GBM | **Sigmoid (Platt)** ← chọn | 0,0253 | 0,1063 | 0,0256 | 0,1085 | 0,0346 | 0,0352 |
| LR | Gốc | 0,1910 | 0,5702 | 0,1816 | 0,5511 | 0,3989 | 0,0352 |
| LR | Dịch tiên nghiệm | 0,0344 | 0,1408 | 0,0307 | 0,1301 | 0,0326 | 0,0352 |
| LR | **Sigmoid (Platt)** ← chọn | 0,0341 | 0,1396 | 0,0309 | 0,1302 | 0,0381 | 0,0352 |

![Reliability trên V3 và xác suất trung bình theo tuần](../assets/results/stage-g-calibration.png)

**Kết luận** (trong dữ liệu phát triển, thăm dò):

1. **Điểm gốc không phải xác suất.** Trung bình điểm GBM là 0,26 trong khi tỷ lệ gian lận thật là 0,035, tức là gấp khoảng 7 lần. Log loss gốc (0,35) tệ hơn cả cách đoán hằng số bằng tỷ lệ gian lận (khoảng 0,15 khi tỷ lệ 3,5%).
2. **Hiệu chỉnh nào cũng sửa được phần lớn sai lệch.** Log loss giảm từ khoảng 0,35 xuống 0,11 (GBM). Riêng dịch tiên nghiệm không dùng nhãn validation nào mà đã đạt gần mức của Platt.
3. **Platt và dịch tiên nghiệm gần như ngang nhau.** Trên V3, log loss của GBM chênh 0,001 và của LR chênh 0,0001. Platt được chọn trên V2 cho cả hai mô hình, nhưng trong 4 cửa sổ cuốn chiếu, dịch tiên nghiệm được chọn 1/4 lần với GBM và 2/4 lần với LR. Không nên đọc đây là "Platt tốt hơn".
4. **Hiệu chỉnh không theo kịp trôi theo tuần.** Tỷ lệ gian lận thật dao động 3,1%–4,75% giữa các tuần validation, còn xác suất trung bình sau hiệu chỉnh thì gần như phẳng (Platt: 3,1%–4,5%) và đi trễ so với tỷ lệ thật. Bộ hiệu chỉnh fit một lần trên V1 không thể biết tỷ lệ của tuần sau.
5. **PR-AUC không đổi**, đúng như kỳ vọng: ở mọi khối, ba phương pháp cho cùng PR-AUC, vì chúng chỉ đổi giá trị chứ không đổi thứ tự điểm. Các chính sách top-N ở G04 cũng không đổi theo hiệu chỉnh.

Ngoài lề: PR-AUC của GBM thay đổi đáng kể giữa các khối (V1 0,514; V2 0,555; V3 0,404) với cùng một mô hình. Điều này nhắc rằng một con số PR-AUC trên một giai đoạn có độ biến thiên lớn; G05 đo kỹ hơn.

**Tự kiểm tra**

| Kiểm tra | Kết quả |
| --- | --- |
| Không chạm test | Test tự động: đảo nhãn và đổi đặc trưng của mọi dòng test không đổi một giá trị nào của kết quả |
| Đảo nhãn | Hoán vị nhãn V3: PR-AUC GBM 0,0355, bằng tỷ lệ gian lận V3 0,0352 (mức ngẫu nhiên) |
| Nhìn tương lai | Test: đảo nhãn V3 không đổi tham số bộ hiệu chỉnh và phương pháp được chọn |
| Phá hoại có chủ đích | Tạm bỏ kiểm tra vai trò khối: test "fit trên V3" thất bại. Tạm cho dòng test vào dữ liệu phát triển: 2 test thất bại. Đã khôi phục code |
| Tính độc lập | Brier và log loss của GBM + Platt trên 1.000 dòng đầu V3, tính bằng vòng lặp Python thuần: 0,0208137948 và 0,0855486315, trùng code chính đến 10 chữ số |
| Tái lập | Chạy `make calibration` hai lần: cùng `cal-04b3ad5944ce`, `results.json` trùng từng byte |

**Hạn chế (kết quả này không chứng minh):**

- Không chứng minh hiệu chỉnh sẽ đúng trên dữ liệu sau validation. Tỷ lệ gian lận trôi theo tuần, và bộ hiệu chỉnh tĩnh đi trễ.
- Bộ hiệu chỉnh fit trên V1 rồi áp ngay lên V2/V3, tức là giả định nhãn V1 có ngay. Thực tế chargeback đến muộn (D3, hạn chế lạc quan).
- Chênh lệch giữa Platt và dịch tiên nghiệm nhỏ hơn mức dao động giữa các cửa sổ, và chưa có khoảng tin cậy cho phần chênh này (không nằm trong danh sách đăng ký trước).
- Isotonic không được thử (D5).
