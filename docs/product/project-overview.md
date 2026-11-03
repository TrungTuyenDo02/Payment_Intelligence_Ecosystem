# Payment_Intelligence_Ecosystem — Tổng quan đề tài

> Tài liệu giới thiệu ban đầu. **Phần I** dành cho mentor và người hướng dẫn: đề tài, phạm vi, phương pháp, kế hoạch, rủi ro, tài liệu tham khảo. **Phần II** là phụ lục kỹ thuật cho team phát triển.
> Cài đặt và lệnh chi tiết: xem [`README.md`](../../README.md). Cập nhật: 2026-11-03 (tuần 1–2 của lịch 6 tuần).

---

# Phần I — Đề tài

## 1. Bài toán

Một hệ thống thanh toán cần trả lời hai câu hỏi khác nhau:

1. **Hệ thống có đang chạy ổn không?** Tỷ lệ giao dịch thành công, độ trễ, lỗi theo nhà cung cấp, và phát hiện sớm khi có bất thường.
2. **Giao dịch này có rủi ro gian lận không?** Chấm điểm rủi ro để người vận hành ưu tiên kiểm tra.

Đề tài xây dựng một **nền tảng dữ liệu dùng chung** và **hai sản phẩm** trả lời hai câu hỏi trên. Đây là demo 6 tuần cho báo cáo thực tập, chạy cục bộ bằng Docker.

## 2. Mục tiêu

- Xây dựng nền tảng dữ liệu có hợp đồng dữ liệu rõ ràng, quản lý nguồn gốc dataset và quy tắc đánh giá thống nhất.
- **Product 01 — Payment Reliability:** KPI độ tin cậy và bộ phát hiện bất thường trên dữ liệu thanh toán giả lập.
- **Product 02 — Fraud & Risk:** mô hình chấm điểm rủi ro gian lận trên dataset công khai IEEE-CIS, kèm quy trình đánh giá không rò rỉ dữ liệu.
- **Tiêu chí thành công:** đánh giá trung thực, tái lập được, giải thích được từng bước. Điểm số mô hình là ưu tiên thứ yếu.

## 3. Phạm vi

### 3.1 Kiến trúc: hai sản phẩm độc lập về dữ liệu

Không có dataset công khai nào chứa đồng thời dữ liệu vận hành thanh toán (độ trễ, mã lỗi, nhà cung cấp) và nhãn gian lận với chung khoá giao dịch. Vì vậy:

| Thành phần | Dữ liệu | Nội dung |
| --- | --- | --- |
| **Shared Foundation** | — | Contract `payment-event`, quản lý dataset (manifest, checksum SHA-256), quy tắc đánh giá (chia theo thời gian, test-một-lần, run log), hạ tầng (Docker, PostgreSQL) |
| **Product 01 — Payment Reliability** | Dữ liệu giả lập theo contract `payment-event` | KPI, phát hiện bất thường, sự cố, dashboard |
| **Product 02 — Fraud & Risk** | IEEE-CIS (Kaggle) | Đặc trưng, baseline, mô hình, đánh giá, API chấm điểm |

Hai sản phẩm **chung nền tảng, không chung dữ liệu** ([ADR 0002](../decisions/0002-product-boundaries.md)). Trong hệ thống thật, chúng sẽ nối với nhau qua khoá `payment_id` từ nguồn sự kiện. Contract đã giữ sẵn trường này cho bước đó.

### 3.2 Trong phạm vi

| Giai đoạn | Nội dung |
| --- | --- |
| A | Khung repo, tooling, PostgreSQL, contract `payment-event`, công cụ manifest dataset |
| B | Baseline gian lận trên IEEE-CIS: adapter, chia theo thời gian, EDA, metrics, baseline luật và Logistic Regression, run log |
| C | Bộ sinh dữ liệu thanh toán giả lập (dựa trên luật, tái lập bằng `simulation_id`) và pipeline ingestion |
| D | Mô hình dữ liệu (dbt), KPI độ tin cậy, bộ phát hiện bất thường |
| E | Thí nghiệm rò rỉ dữ liệu, Gradient Boosting, API chấm điểm |
| F | Dashboard và báo cáo |

### 3.3 Ngoài phạm vi

- Dữ liệu thật hoặc dữ liệu công ty; dữ liệu thẻ hoặc thông tin xác thực.
- Tự động chặn giao dịch. Điểm rủi ro chỉ hỗ trợ quyết định.
- Mô hình pretrained từ Internet.
- Kafka, Spark, Kubernetes, MLflow, xác thực người dùng, chatbot/LLM.
- Schema `risk-context` và luồng tích hợp dữ liệu giữa hai sản phẩm.
- Các dataset khác (ULB, MoMTSim, BAF); chỉ dùng làm tài liệu tham khảo.

## 4. Phương pháp

| Vấn đề | Cách làm | Vì sao |
| --- | --- | --- |
| Chia dữ liệu | Theo thời gian: 60% train, 20% validation, 20% test. Không chia ngẫu nhiên | Mô phỏng đúng tình huống dự đoán tương lai; chia ngẫu nhiên làm kết quả lạc quan giả tạo |
| Fit mô hình | Mọi bước tiền xử lý và ngưỡng luật chỉ học trên train; ngưỡng quyết định chọn trên validation | Tránh rò rỉ thông tin từ dữ liệu đánh giá |
| Tập test | Mỗi cấu hình đã chốt (`frozen`) chỉ chạy test **một lần** | Tránh chọn mô hình dựa trên kết quả test |
| Quyết định tiền xử lý | Dựa trên bằng chứng EDA từ train; chủ dự án duyệt từng quyết định | Mọi lựa chọn đều có căn cứ và giải thích được |
| Metrics | PR-AUC kèm khoảng tin cậy bootstrap, precision, recall, F1, FPR, recall tại precision mục tiêu, recall tại FPR 5%. Không dùng accuracy làm chỉ số chính | Dữ liệu mất cân bằng (gian lận khoảng 3,5%); accuracy gây hiểu nhầm |
| Tái lập | `run_id` tất định từ config, seed, checksum dataset và mốc split | Chạy lại cùng điều kiện cho ra cùng kết quả |

## 5. Kế hoạch 6 tuần

| Tuần | Giai đoạn | Đầu ra | Điểm dừng chờ duyệt |
| --- | --- | --- | --- |
| 1–2 | A, B | Baseline có số liệu validation; một lần chạy test | Duyệt contract; ADR 0003 đã chọn: để `gap_days` sang Stage E |
| 3 | C | Dữ liệu sự kiện giả lập (demo nhỏ, khoảng 5 nghìn payment) tái lập được, nạp vào PostgreSQL | Đặc tả Stage C đã duyệt; driver đã chọn ([ADR 0004](../decisions/0004-postgres-driver.md)) |
| 4 | D | Bảng KPI, danh sách bất thường và sự cố | ADR dbt (phương án dự phòng: SQL views) |
| 5 | E | Báo cáo thí nghiệm rò rỉ, mô hình Gradient Boosting, API chấm điểm | Đăng ký trước danh sách config chạy test; ADR framework API |
| 6 | F | Dashboard, báo cáo thực tập | ADR framework dashboard |

**Trạng thái hiện tại:** Stage A/B đã xong code (T01–T10 và bổ sung recall tại FPR) và đã merge vào `main` (PR #2). Contract `payment-event` 1.0.0 đã được duyệt (2026-11-03). 9 quyết định EDA đã duyệt. Đã chạy đánh giá test một lần với config `frozen` (`run-d6faa4699008`): Logistic Regression PR-AUC 0,165 trên test (0,245 trên validation), baseline luật 0,078 (xem [README](../../README.md#kết-quả)). Lần chạy test trước (`run-515a1190a0a4`, config cũ chưa có `fpr_target`) cho kết quả trùng khớp ở mọi metric chung. **Stage A/B hoàn tất.** Đặc tả Stage C đã duyệt (2026-11-04): [`stage-c-spec.md`](../architecture/stage-c-spec.md). Đang làm Stage C.

## 6. Rủi ro và hạn chế đã biết

| Rủi ro | Hệ quả | Cách xử lý |
| --- | --- | --- |
| Hai sản phẩm không chung dữ liệu | Không có luồng dữ liệu xuyên suốt | Tuyên bố rõ trong báo cáo (ADR 0002) |
| Đánh giá vòng tròn ở Product 01 | Detector chỉ chứng minh bắt được bất thường do chính dự án chèn vào | Chốt kịch bản bất thường trước khi chỉnh detector, tách seed chỉnh và seed báo cáo, giữ lại một loại bất thường không dùng khi chỉnh. Báo cáo là "kiểm chứng trên bất thường đã biết", không phải hiệu năng thực tế |
| PR-AUC phụ thuộc tỷ lệ gian lận | So sánh giữa các tập có tỷ lệ khác nhau bị nhiễu | Luôn báo tỷ lệ gian lận cạnh PR-AUC; đã thêm recall tại FPR cố định (không phụ thuộc tỷ lệ) |
| Cách gán nhãn IEEE-CIS | Nhãn lan sang các giao dịch sau của cùng tài khoản, email hoặc địa chỉ; cùng thực thể có thể nằm ở cả train và test | Đo tỷ lệ thực thể lặp lại; phân tích độ nhạy với khoảng trống thời gian ([ADR 0003](../decisions/0003-label-delay-and-entity-overlap.md): làm ở Stage E) |
| Độ trễ nhãn | Chưa có chuẩn chung để đánh giá | Tự định nghĩa giao thức và biện minh, không viết "theo chuẩn X" |
| Lịch 6 tuần chặt | Stage C–F mỗi giai đoạn chỉ một tuần | Mỗi ADR công cụ có phương án dự phòng đơn giản hơn |

## 7. Tài liệu tham khảo

Mỗi nhóm xếp theo thứ tự nên đọc. Chỉ nguồn có trong mục 7.5 là chưa qua bình duyệt.

### 7.1 Đánh giá mô hình gian lận

1. Le Borgne, Siblini, Lebichot, Bontempi. *Reproducible Machine Learning for Credit Card Fraud Detection — Practical Handbook*. Université Libre de Bruxelles, 2022. Sách mở: <https://fraud-detection-handbook.github.io/fraud-detection-handbook/>. **Nên đọc đầu tiên**: bao quát chia dữ liệu theo thời gian, độ trễ nhãn, metrics và bộ sinh giao dịch giả lập.
2. Dal Pozzolo, Boracchi, Caelen, Alippi, Bontempi. *Credit Card Fraud Detection: A Realistic Modeling and a Novel Learning Strategy*. IEEE TNNLS 29(8), 2018. Định nghĩa độ trễ xác minh (verification latency), concept drift và mất cân bằng lớp trong bài toán gian lận.
3. Saito, Rehmsmeier. *The Precision-Recall Plot Is More Informative than the ROC Plot When Evaluating Binary Classifiers on Imbalanced Datasets*. PLOS ONE 10(3), 2015. DOI 10.1371/journal.pone.0118432. Căn cứ dùng PR-AUC và lưu ý PR-AUC phụ thuộc tỷ lệ lớp dương.
4. Kaufman, Rosset, Perlich, Stitelman. *Leakage in Data Mining: Formulation, Detection, and Avoidance*. ACM TKDD 6(4), 2012. DOI 10.1145/2382577.2382579. Định nghĩa rò rỉ dữ liệu.
5. Kapoor, Narayanan. *Leakage and the Reproducibility Crisis in Machine-Learning-Based Science*. Patterns 4(9), 2023. DOI 10.1016/j.patter.2023.100804. Phân loại các kiểu rò rỉ; căn cứ cho thí nghiệm rò rỉ ở Stage E.
6. Gama, Žliobaitė, Bifet, Pechenizkiy, Bouchachia. *A Survey on Concept Drift Adaptation*. ACM Computing Surveys 46(4), 2014. DOI 10.1145/2523813.
7. Jesus et al. *Turning the Tables: Biased, Imbalanced, Dynamic Tabular Datasets for ML Evaluation*. NeurIPS 2022 Datasets and Benchmarks ([arXiv 2211.13358](https://arxiv.org/abs/2211.13358)). Căn cứ cho chia theo thời gian và metric recall tại FPR cố định. Không dùng dataset của bài.
8. Grinsztajn, Oyallon, Varoquaux. *Why Do Tree-Based Models Still Outperform Deep Learning on Typical Tabular Data?* NeurIPS 2022 Datasets and Benchmarks. Căn cứ chọn Gradient Boosting ở Stage E.

### 7.2 Độ tin cậy hệ thống và phát hiện bất thường (Product 01)

1. Beyer, Jones, Petoff, Murphy (eds.). *Site Reliability Engineering*. O'Reilly, 2016. Bản đọc miễn phí: <https://sre.google/sre-book/table-of-contents/>. Chương 4 (SLO) và chương 6 (Monitoring Distributed Systems: bốn tín hiệu latency, traffic, errors, saturation) là nền cho chọn KPI.
2. Hyndman, Athanasopoulos. *Forecasting: Principles and Practice*, 3rd ed. OTexts, 2021. Bản đọc miễn phí: <https://otexts.com/fpp3/>. Phân rã chuỗi thời gian (mùa vụ theo giờ, ngày), nền cho detector dựa trên phần dư.
3. Chandola, Banerjee, Kumar. *Anomaly Detection: A Survey*. ACM Computing Surveys 41(3), 2009. Phân loại các kiểu bất thường và phương pháp.
4. Wu, Keogh. *Current Time Series Anomaly Detection Benchmarks Are Flawed and Are Creating the Illusion of Progress*. IEEE TKDE, 2021. DOI 10.1109/TKDE.2021.3112126. Căn cứ trực tiếp cho rủi ro đánh giá vòng tròn và bất thường quá dễ phát hiện.
5. Lavin, Ahmad. *Evaluating Real-time Anomaly Detection Algorithms — the Numenta Anomaly Benchmark*. ICMLA 2015 ([arXiv 1510.03336](https://arxiv.org/abs/1510.03336)). Cách chấm điểm theo cửa sổ thời gian, thưởng phát hiện sớm.
6. Liu, Ting, Zhou. *Isolation Forest*. IEEE ICDM 2008. Phương pháp có sẵn trong scikit-learn.

### 7.3 Data contract, nền tảng dữ liệu, dữ liệu giả lập

1. Kleppmann. *Designing Data-Intensive Applications*. O'Reilly, 2017. Chương 4 (mã hoá và tiến hoá schema).
2. Reis, Housley. *Fundamentals of Data Engineering*. O'Reilly, 2022. Vòng đời dữ liệu, ingestion, mô hình hoá.
3. JSON Schema, bản 2020-12: <https://json-schema.org/specification>. Semantic Versioning 2.0.0: <https://semver.org/>.
4. Breck, Polyzotis, Roy, Whang, Zinkevich. *Data Validation for Machine Learning*. MLSys 2019. Kiểm tra schema và phân phối dữ liệu đầu vào.
5. Gebru et al. *Datasheets for Datasets*. Communications of the ACM 64(12), 2021. DOI 10.1145/3458723. Mô hình cho manifest dataset.
6. Mitchell et al. *Model Cards for Model Reporting*. ACM FAT\* 2019. Mẫu báo cáo mô hình cho Product 02.
7. Lopez-Rojas, Elmir, Axelsson. *PaySim: A Financial Mobile Money Simulator for Fraud Detection*. EMSS 2016. Tham khảo cách thiết kế bộ sinh giao dịch (Stage C).
8. Nygard. *Documenting Architecture Decisions*, 2011: <https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions>. Định dạng ADR dùng trong `docs/decisions/`.
9. dbt documentation: <https://docs.getdbt.com/> (Stage D, chờ ADR).

### 7.4 Nghiệp vụ thanh toán

1. IEEE-CIS Fraud Detection (Kaggle): <https://www.kaggle.com/c/ieee-fraud-detection>. Thread mô tả dữ liệu và cách gán nhãn: <https://www.kaggle.com/c/ieee-fraud-detection/discussion/101203>. Chỉ dùng cho nghiên cứu, theo điều khoản cuộc thi.
2. EBA, ECB. *2024 Report on Payment Fraud*, 2024: <https://www.eba.europa.eu/publications-and-media/press-releases/eba-and-ecb-release-joint-report-payment-fraud>. Số liệu và phân loại gian lận theo phương thức thanh toán.
3. PCI Security Standards Council. *PCI DSS v4.0*: <https://www.pcisecuritystandards.org/>. Căn cứ cho quy tắc không lưu dữ liệu thẻ.
4. NAPAS. Dịch vụ thanh toán QR (chuẩn EMVCo, mô hình merchant-presented): <https://en.napas.com.vn/qr-code-payment-service>. Bối cảnh cho `payment_method = QR`.
5. Ngân hàng Nhà nước Việt Nam. Quyết định 2345/QĐ-NHNN ngày 18/12/2023 về giải pháp an toàn, bảo mật trong thanh toán trực tuyến và thanh toán thẻ (hiệu lực 01/7/2024). Cần đối chiếu văn bản gốc trước khi trích dẫn.

### 7.5 Chưa qua bình duyệt — chỉ tham khảo ý tưởng

- Các preprint arXiv về đánh giá có độ trễ nhãn, ví dụ Dhama (arXiv 2605.29272, 2026). Không dùng làm căn cứ cho quyết định.
- Notebook và lời giải công khai của cuộc thi IEEE-CIS. Nếu dùng ý tưởng, phải ghi nguồn và giấy phép. Không sao chép code.
- Mọi con số hiệu năng công bố trên IEEE-CIS chỉ được trích như **mốc tham chiếu bên ngoài**, ghi rõ khác cách chia dữ liệu.

---

# Phần II — Phụ lục kỹ thuật

## 8. Trạng thái task (Stage A/B)

| ID | Việc | Trạng thái |
| --- | --- | --- |
| T01 | Khung repo và tooling | Xong, đã vào `main` |
| T02 | Contract `payment-event` | **Đã duyệt** 1.0.0 (2026-11-03), kèm quy tắc giữa các attempt trong changelog |
| T03 | Công cụ manifest dataset | Xong |
| T04 | Adapter IEEE-CIS | Xong |
| T05 | Chia dữ liệu theo thời gian | Xong |
| T05b | EDA 6 bước trên train | Xong, 9 quyết định đã duyệt |
| T06 | Metrics | Xong; bổ sung recall tại FPR 5% |
| T07 | Baseline dựa trên luật | Xong |
| T08 | Baseline Logistic Regression | Xong |
| T09 | Run log, CLI, quy tắc test-một-lần | Xong; config `frozen`, đã chạy test (`run-d6faa4699008`) |
| T10 | Test chống rò rỉ dữ liệu | Xong |

Toàn bộ Stage A/B đã gộp qua nhánh `integration/stage-ab` và merge vào `main` (PR #2).

## 9. Quy tắc bắt buộc

- Không dữ liệu thật, không dữ liệu thẻ, không secret trong repo. Không commit dataset, Parquet, mô hình, bảng EDA hay `.env`.
- Không tự tải dataset. Chủ dự án đặt file IEEE-CIS vào `datasets/raw/ieee-cis/`.
- Nhãn tách khỏi đặc trưng; code tạo feature không đọc được cột nhãn.
- Contract chỉ tạo dưới dạng draft; thay đổi kiến trúc đề xuất bằng ADR.
- Mỗi task một nhánh; chỉ xong khi `make lint` và `make test` đều pass.
- Không thêm thư viện mới khi chưa có ADR nêu lý do.
- **Chỉ chủ dự án** được duyệt contract, duyệt quyết định EDA, đặt `frozen` và chạy `make baseline-final`.

## 10. Kiến thức cần dùng

| Mảng | Nội dung | Dùng ở đâu | Tài liệu |
| --- | --- | --- | --- |
| Nghiệp vụ thanh toán | Vòng đời giao dịch (payment, attempt), provider, merchant, mã lỗi, chargeback, các loại gian lận | Contract, cả hai sản phẩm | 7.4 |
| Data contract | JSON Schema, semver, ràng buộc chéo trường | `contracts/payment-event/` | 7.3 (1, 3) |
| Quản trị dữ liệu | Nguồn gốc, checksum, giấy phép dataset, dữ liệu nhạy cảm | `datasets/manifests/` | 7.3 (5), 7.4 (3) |
| EDA | Missing values, mất cân bằng lớp, phân phối lệch, biến phân loại nhiều giá trị | `fraud_risk/eda/` | 7.1 (1) |
| Đánh giá mô hình | Chia theo thời gian, rò rỉ, PR-AUC, FPR, chọn ngưỡng, bootstrap, độ trễ nhãn | `fraud_risk/evaluation/` | 7.1 (1–7) |
| Machine learning | Baseline luật, Logistic Regression, `Pipeline`, `class_weight`; sau đó Gradient Boosting | `fraud_risk/baselines/` | 7.1 (8) |
| Tái lập thí nghiệm | Seed, config `frozen`, `run_id` tất định, test-một-lần | `fraud_risk/evaluation/run_log.py` | 7.1 (5) |
| Kỹ thuật dữ liệu | PostgreSQL, Parquet, ingestion, dbt | Stage C–D | 7.3 (1, 2, 9) |
| Chuỗi thời gian và bất thường | KPI theo thời gian, mùa vụ, phân rã, ngưỡng thống kê, đánh giá detector | Product 01 | 7.2 |
| Công cụ | Python 3.11, `uv`, `pandas`, `scikit-learn`, `pytest`, `ruff`, Docker Compose, Git | Toàn dự án | `README.md` |

## 11. Bắt đầu nhanh

```bash
make setup
```

```bash
make lint test
```

```bash
make up
```

Dataset IEEE-CIS do chủ dự án tải thủ công từ Kaggle, đặt vào `datasets/raw/ieee-cis/` và không commit.
