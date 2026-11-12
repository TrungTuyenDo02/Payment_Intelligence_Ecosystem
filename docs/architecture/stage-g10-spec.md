# Đặc tả G10 — Thử nghiệm độ bền (bản nháp, chờ duyệt)

- **Trạng thái:** **Nháp ⏸**, chờ chủ dự án duyệt D1–D9 (mục 9). Chưa có dòng code nào của G10.
- **Liên quan:** [đặc tả Stage C](stage-c-spec.md) (bộ sinh dữ liệu, ingestion), [đặc tả Stage D](stage-d-spec.md) (detector), [ADR 0005](../decisions/0005-kpi-layer-sql-views.md) (KPI là SQL views), [ADR 0009](../decisions/0009-decision-evaluation-protocol.md), [ADR 0010](../decisions/0010-experiment-and-execution-ids.md).
- **Nguyên tắc:** không đổi detector, không đổi mô hình, không chỉnh lại ngưỡng, không thêm thuật toán. G10 chỉ **đo** các thành phần đã chốt hoạt động thế nào khi điều kiện xấu đi. Không mở tập test, không chạm cặp mô phỏng `frozen` (`sim-485cacc9c858`, `sim-f6e6749ff0bf`) hay sổ `detect_report_runs.json`.

## 1. Ba câu hỏi

| Phần | Câu hỏi | Sản phẩm | Cần PostgreSQL |
| --- | --- | --- | --- |
| **G10a** sự cố tăng dần | Detector D-B so với đường nền 24 giờ trước đó. Nếu sự cố tăng **từ từ** thì đường nền có "nuốt" dần sự cố không ("luộc ếch")? | Product 01 | Có |
| **G10b** pipeline | Nạp trùng, sự kiện sai thứ tự hoặc đến muộn, dòng hỏng, tải 10× làm gì với dữ liệu và KPI? | Product 01 | Có |
| **G10c** nhãn nhiễu | Nếu một phần nhãn train sai (gian lận không bị phát hiện, hoặc báo nhầm thành gian lận), Logistic Regression hay Gradient Boosting chịu được tốt hơn? | Product 02 | Không |

## 2. G10a — Sự cố tăng dần

### 2.1 Thay đổi bộ sinh dữ liệu

Thêm trường tuỳ chọn `shape` cho mỗi bất thường, giá trị `step` (mặc định, như hiện nay) hoặc `ramp`. Với `ramp`, hệ số tăng tuyến tính từ 1 lên `magnitude` trong `ramp_minutes` phút đầu, rồi giữ ở `magnitude` đến hết `duration_minutes`. Ví dụ, tỷ lệ lỗi của `provider_outage` tại thời điểm t trong cửa sổ là `failure_prob × (1 + (magnitude − 1) × min(1, t / ramp_minutes))`.

**Không đổi kết quả của config cũ** (D1): khi `shape = step`, trường này không được đưa vào `simulation_id`, và code sinh dữ liệu đi đúng nhánh cũ. Test hồi quy: `demo.yaml` vẫn ra `sim-485cacc9c858`, `report.yaml` vẫn ra `sim-f6e6749ff0bf`, và SHA-256 của `events.jsonl` không đổi.

### 2.2 Lưới mô phỏng (đăng ký trước)

Mỗi mô phỏng 7 ngày, cùng tham số nền với `demo.yaml`, đúng **một** sự cố bắt đầu từ ngày thứ 3 (để có đủ 24 giờ đường nền sạch và tránh hai sự cố chồng nhau). Config mới ở `shared/synthetic-generator/configs/stress/`, trạng thái `draft`, `purpose: stress` (giá trị mới, xem D3).

| Trục | Giá trị |
| --- | --- |
| Loại sự cố | `provider_outage` trên `prov_002` (lỗi 22%); `latency_degradation` trên `prov_001` |
| `magnitude` cuối | 2; 3 |
| Hình dạng | `step`; `ramp` với `ramp_minutes` 60, 360, 1.440 (24 giờ), 2.880 (48 giờ) |
| Thời gian giữ sau khi ramp xong | 120 phút |
| Seed | 3 seed cho mỗi ô |

Tổng: 2 loại × 2 mức × 5 hình dạng × 3 seed = **60 mô phỏng**, mỗi mô phỏng khoảng 25 nghìn payment.

### 2.3 Đo gì

Detector chạy với **đúng tham số của `detector.yaml`** (D-B ngưỡng 8, gộp 2 khung; D-A ngưỡng 7; đường nền 96 khung = 24 giờ). Lệnh mới `python -m payment_reliability.cli stress --config …` ghi `artifacts/experiments/ramp-<mã>/`. Lệnh này không dùng `detect` (chỉ cho bộ tuning) hay `detect-report` (một lần).

Với mỗi mô phỏng và mỗi detector:

- bắt được hay không (trong cửa sổ, cộng 15 phút ân hạn như Stage D);
- độ trễ, tính từ lúc bắt đầu sự cố và từ lúc hệ số đạt 1,5×;
- điểm cao nhất trong cửa sổ, so với ngưỡng;
- số báo nhầm mỗi ngày ngoài cửa sổ.

**Giả thuyết viết trước:** ramp 60 phút cho kết quả gần như `step`; ramp từ 24 giờ trở lên làm D-B trượt hoặc bắt muộn, vì đường nền 24 giờ đã chứa phần đầu của sự cố. Kết quả ngược giả thuyết cũng được báo cáo nguyên văn.

**Tính độc lập:** với tỷ lệ lỗi, điểm D-B có công thức đóng (z của tỷ lệ nhị thức so với đường nền). Tự tính điểm kỳ vọng theo thời gian cho một ramp bằng công thức, rồi đối chiếu với điểm detector trên dữ liệu mô phỏng.

## 3. G10b — Kiểm thử pipeline

Nạp trùng và dòng hỏng **đã có test chức năng** từ Stage C (`test_ingest_and_reingest_is_idempotent`, `test_rejects_are_stored_with_reasons`, các test quy tắc giữa attempt). G10b bổ sung phần đo và các trường hợp chưa có:

| Thử | Cách làm | Kỳ vọng / đo |
| --- | --- | --- |
| Nạp trùng ở quy mô đầy đủ | Nạp `sim-485cacc9c858` hai lần | Lần hai: 0 dòng mới, toàn bộ là `rows_duplicate`; KPI Parquet trùng từng byte |
| Sai thứ tự | Xáo trộn thứ tự dòng của file sự kiện, nạp vào một simulation tạm | KPI trùng từng byte với bản gốc |
| Đến muộn | Tách file theo thời điểm "đến": nạp 90% trước, xuất KPI, nạp 10% còn lại, xuất lại | Đếm khung 15 phút có KPI thay đổi; chạy D-B trên cả hai bản và so cảnh báo. Đây là điều vận hành thật gặp phải: detector chỉ thấy ảnh chụp tại lúc chạy |
| Dòng hỏng | Chèn x% dòng hỏng có kiểm soát (JSON hỏng, thiếu trường, sai enum, vi phạm quy tắc attempt), x = 0,1%, 1%, 5% | Số dòng bị từ chối khớp đúng số đã chèn (tính cả attempt cùng payment bị từ chối theo); KPI chỉ tính dòng hợp lệ |
| Tải 10× | Config `load10x.yaml` (`draft`): 1.500 payment/giờ, 7 ngày | Đo thời gian sinh, nạp, xuất KPI, chạy detector; dung lượng bảng (`pg_total_relation_size`); thời gian truy vấn mỗi view KPI. Ghi cấu hình máy. **Không phải benchmark** |

Phần "đến muộn" cần ingest nhận đường dẫn file tuỳ ý (thêm tham số `--events`, không đổi hành vi mặc định).

## 4. G10c — Nhãn nhiễu trên train (Product 02)

Chỉ dùng train và validation; nhãn **validation giữ nguyên**, chỉ nhãn train bị lật. Hai mô hình giữ cấu hình đã chốt: Logistic Regression (`baseline.yaml`) và Gradient Boosting (tham số của `run-f8807cb6f780`, không quét lưới). Config `configs/label-noise.yaml`, `draft`, `stage: exploratory`, lệnh `make label-noise`, kết quả `artifacts/experiments/noise-<mã>/`.

Lật đều hai chiều không thực tế: tỷ lệ gian lận chỉ 3,4%, nên lật 10% mọi nhãn sẽ tạo ra gấp ba lần "gian lận" giả. Vì vậy dùng hai loại nhiễu riêng:

| Loại | Ý nghĩa thực tế | Mức |
| --- | --- | --- |
| **Bỏ sót** (1 → 0) | Gian lận không bị phát hiện hoặc không có chargeback | 10%, 25%, 50% số dòng gian lận của train |
| **Báo nhầm** (0 → 1) | Giao dịch hợp lệ bị ghi nhầm là gian lận | Số dòng bằng 10%, 25%, 50% số gian lận thật của train |

Mỗi mức 3 seed lật. Đo trên validation sạch: PR-AUC, recall tại FPR 5%, độ chênh so với mức 0% (bootstrap cặp theo cụm `card1`, như Stage E).

**Kiểm tra bắt buộc:** mức 0% tái tạo đúng 0,497 (GBM) và 0,245 (LR); lật 100% nhãn dương thì kết quả về mức ngẫu nhiên; test xác nhận nhãn validation và mọi dòng test không bị đọc hay đổi.

Lưu ý khi giải thích: `class_weight="balanced"` tự tính lại trọng số theo nhãn **đã lật**, nên nhiễu "bỏ sót" vừa làm sai nhãn vừa đổi trọng số. Hai hiệu ứng này không tách riêng được trong thí nghiệm này.

## 5. Mã lần chạy và tái lập

`ramp-<mã>`, `pipe-<mã>`, `noise-<mã>` tính như các experiment Stage G (config, seed, checksum hoặc `simulation_id`, mốc chia). Mỗi lần chạy có `execution_id` (ADR 0010). Mỗi lệnh chạy hai lần và so `results.json`. Riêng số đo thời gian và dung lượng của G10b đổi theo máy, nên được ghi tách khỏi `results.json`.

## 6. Kiểm tra bắt buộc (CLAUDE.md mục 8)

| Kiểm tra | G10a | G10b | G10c |
| --- | --- | --- | --- |
| Đảo nhãn | Đổi nhãn sự cố sang khoảng thời gian khác: tỷ lệ "bắt được" về mức báo nhầm | — | Lật 100% nhãn dương: PR-AUC về mức tỷ lệ gian lận |
| Nhìn tương lai | Điểm detector tại khung t không đổi khi sửa dữ liệu sau t | KPI các khung trước mốc "đến muộn" không đổi khi chỉ thêm dữ liệu sau mốc | Nhãn validation và test không ảnh hưởng mô hình |
| Tính độc lập | Điểm D-B so với công thức đóng | Đếm dòng bị từ chối bằng cách khác (đọc lại file) | PR-AUC mức 0% so với Stage E |
| Phá hoại có chủ đích | Tạm bỏ nhánh `step` cũ: test hồi quy `simulation_id` phải thất bại | Tạm bỏ `ON CONFLICT`: test nạp trùng phải thất bại | Tạm lật cả nhãn validation: test phải thất bại |
| Tái lập | Cùng config → cùng `ramp-<mã>` và kết quả | Cùng config → cùng kết quả (trừ số đo thời gian) | Cùng `noise-<mã>`, `results.json` trùng từng byte |

## 7. Thứ tự làm và nhánh

1. **G10c** trước (`stage-g/g10c-label-noise`): chạy được trên máy này vì không cần PostgreSQL.
2. **G10a** (`stage-g/g10a-ramp`): code, test và mô phỏng làm trên máy này; phần KPI và detector cần PostgreSQL (D2).
3. **G10b** (`stage-g/g10b-pipeline`): như G10a.
4. Báo cáo `docs/architecture/stage-g10-report.md`, cập nhật Stage G và báo cáo tuần.

## 8. Hạn chế đã biết (ghi lại trong báo cáo G10)

- Mọi sự cố của G10a vẫn do dự án tự cài, nên đây là **kiểm chứng trên bất thường đã biết**, không phải tỷ lệ phát hiện thực tế.
- 3 seed mỗi ô chỉ đủ cho thấy xu hướng, không đủ cho khoảng tin cậy chặt.
- G10a cho thấy điểm mù nhưng **không sửa nó**: sửa (ví dụ CUSUM, đường nền cố định theo tuần) là thuật toán mới, ngoài phạm vi, và cần một cặp tuning/report mới để đánh giá trung thực.
- G10b đo trên một máy cá nhân; con số thời gian không chuyển sang hệ thống khác được.
- G10c dùng lại validation (thăm dò); nhiễu nhãn thật không ngẫu nhiên đều mà tập trung ở một số loại giao dịch.

## 9. Quyết định cần chủ dự án duyệt

| # | Câu hỏi | Đề xuất của agent |
| --- | --- | --- |
| **D1** | CLAUDE.md ghi "tăng `GENERATOR_VERSION`" khi thêm ramp. Nhưng `simulation_id` chứa `GENERATOR_VERSION`: tăng nó thì `demo.yaml` và `report.yaml` **ra mã mới**, `make demo`, `detector.yaml` và báo cáo Stage D không còn tái lập được mã cũ. Quy tắc 11 chỉ bắt buộc tăng khi cùng config cho **kết quả khác**. | **Không tăng.** Thêm `shape` sao cho config cũ ra đúng mã và đúng từng byte như trước, có test hồi quy chặn. Nếu sau này đổi hành vi của config cũ thì mới tăng |
| **D2** | KPI là SQL views (ADR 0005) nên G10a/G10b cần PostgreSQL; máy này không có Docker, PostgreSQL hay WSL | Agent viết code và test (test DB chạy trong CI). Phần chạy thật: (a) chủ dự án chạy trên máy có Docker, hoặc (b) thêm một workflow CI chạy tay (`workflow_dispatch`) để chạy G10a/G10b và tải kết quả về. Đề xuất (a); (b) nếu không có máy |
| **D3** | Mô phỏng G10a không dùng để chỉnh ngưỡng, nên không phải `tuning` hay `report` | Thêm `purpose: stress` (giá trị mới không đổi mã của config cũ) và lệnh `stress` riêng, không đi qua `detect` hay `detect-report` |
| **D4** | Lưới G10a: 60 mô phỏng (mục 2.2) | Giữ nguyên; giảm còn 1 seed nếu thời gian nạp quá lâu |
| **D5** | Mức nhiễu G10c: bỏ sót 10/25/50% và báo nhầm tương đương, mỗi mức 3 seed | Giữ nguyên |
| **D6** | G10c đo trên toàn bộ validation (không chia V1/V2/V3), vì không có bước chọn hay hiệu chỉnh | Đồng ý |
| **D7** | Không sửa điểm mù tìm được ở G10a (không thêm thuật toán) | Đồng ý; chỉ ghi vào "Hướng phát triển" |
| **D8** | Thứ tự G10c → G10a → G10b, mỗi phần một nhánh | Đồng ý |
| **D9** | Config G10 được commit **trước** lần chạy đầu (rút kinh nghiệm từ Stage G) | Đồng ý; commit config và code, rồi mới chạy |
