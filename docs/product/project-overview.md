# Payment_Intelligence_Ecosystem — Tổng quan đề tài

> Tài liệu giới thiệu ban đầu cho các team. Hướng dẫn cài đặt, lệnh và phương pháp đánh giá chi tiết xem [`README.md`](../../README.md).
> Cập nhật: 2026-11-03. Phần "Kế hoạch" và "Hướng đi" là **dự kiến**, chưa phải cam kết; chủ dự án có thể điều chỉnh.

## 1. Đề tài là gì

**Payment Intelligence Ecosystem** là nền tảng dữ liệu và AI dạng module cho lĩnh vực thanh toán, gồm một nền tảng dùng chung và hai sản phẩm độc lập:

| Thành phần | Mục đích |
| --- | --- |
| **Shared Foundation** | Hợp đồng dữ liệu (data contract), bộ sinh dữ liệu thanh toán giả lập, quản lý dataset (manifest, checksum), kiểm tra dữ liệu, hạ tầng chung |
| **Product 01 — Payment Reliability** | Theo dõi độ tin cậy giao dịch: KPI (tỷ lệ thành công, độ trễ, lỗi theo provider), phát hiện bất thường, sự cố, API, dashboard |
| **Product 02 — Fraud & Risk** | Phát hiện gian lận: đặc trưng, mô hình, đánh giá, chấm điểm rủi ro, hỗ trợ điều tra |

**Bối cảnh:** demo 6 tuần cho báo cáo thực tập, có thể phát triển thành đề xuất nội bộ. Chạy cục bộ bằng Docker.

**Tiêu chí ưu tiên:** đánh giá trung thực (không rò rỉ dữ liệu, tái lập được, báo cáo đúng số thật) quan trọng hơn điểm số mô hình. Mọi bước phải giải thích được cho mentor.

## 2. Nguyên tắc không được vi phạm

- **Không dùng dữ liệu thật hay dữ liệu công ty.** Chỉ dùng dataset công khai (IEEE-CIS từ Kaggle) và dữ liệu giả lập. Không có dữ liệu thẻ, thông tin xác thực hay secret trong repo.
- **Chia dữ liệu theo thời gian**, không chia ngẫu nhiên. Tập test chỉ dùng **một lần** cho mỗi cấu hình đã đóng băng (`frozen`).
- **Mọi thứ được "học" (scaler, encoder, imputer, ngưỡng luật) chỉ fit trên train**; ngưỡng quyết định chọn trên validation.
- **Nhãn tách khỏi đặc trưng**: code tạo feature không đọc được cột nhãn.
- **Quyết định tiền xử lý phải có bằng chứng** từ partition train và được chủ dự án duyệt (`docs/data-analysis/eda-summary.md`).
- **Điểm rủi ro chỉ để hỗ trợ quyết định**, không tự động chặn giao dịch.
- **Không dùng mô hình pretrained** từ Internet (dễ nhiễm dữ liệu test, và file pickle có thể thực thi mã).
- **Chỉ chủ dự án** được duyệt contract, duyệt quyết định EDA, đặt config `frozen` và chạy đánh giá test.

## 3. Trạng thái hiện tại

| Giai đoạn | Nội dung | Trạng thái |
| --- | --- | --- |
| **A — Khung dự án** | Cấu trúc repo, tooling, Docker Compose (PostgreSQL 16), contract `payment-event` bản nháp, công cụ manifest dataset | Code xong (T01–T03). Contract đang **chờ duyệt** |
| **B — Baseline gian lận** | Adapter IEEE-CIS, chia theo thời gian 60/20/20, EDA 6 bước, metrics, baseline luật + Logistic Regression, run log, test chống rò rỉ | Code xong (T04–T10). 9 quyết định EDA **đã duyệt**, config baseline đã `frozen`. **Chưa có kết quả trên tập test** |

Hiện mới chỉ T01 nằm trên `main`. Code T02–T10 đang ở các nhánh `task/*`, chờ chủ dự án review và merge.

## 4. Kế hoạch 6 tuần (dự kiến)

| Tuần | Giai đoạn | Việc chính | Đầu ra |
| --- | --- | --- | --- |
| 1–2 | A, B | Khung repo, contract, baseline fraud trên IEEE-CIS | Baseline có số liệu validation, chạy test một lần |
| 3 | C | Bộ sinh dữ liệu thanh toán giả lập theo contract `payment-event` (dựa trên luật, có `simulation_id`), pipeline ingestion vào PostgreSQL | Dữ liệu sự kiện giả lập tái lập được |
| 4 | D | dbt marts, KPI độ tin cậy, bộ phát hiện bất thường (Product 01) | Bảng KPI và danh sách bất thường/sự cố |
| 5 | E | Thí nghiệm rò rỉ (so sánh split ngẫu nhiên và split theo thời gian), Gradient Boosting, API chấm điểm | Báo cáo so sánh, API `score` |
| 6 | F | Dashboard, tích hợp hai sản phẩm, viết báo cáo | Demo chạy end-to-end và báo cáo thực tập |

Mỗi giai đoạn kết thúc bằng một lần review của chủ dự án. Không bắt đầu giai đoạn sau khi giai đoạn trước chưa được duyệt.

## 5. Hướng đi dự kiến

**Ngắn hạn (hoàn thiện Stage A/B)**
- Duyệt contract `payment-event`, review và merge các nhánh T02–T10 vào `main`.
- Chạy `make baseline-final` một lần, ghi kết quả thật kèm `run_id` vào README.

**Các ý tưởng đề xuất cho giai đoạn sau (cần chủ dự án quyết định)**
- **Thêm metric recall tại FPR cố định** (ví dụ 5%) bên cạnh recall tại precision. FPR không phụ thuộc tỷ lệ gian lận, nên ổn định hơn khi tỷ lệ này thay đổi theo thời gian. Căn cứ: Jesus et al., *Turning the Tables*, NeurIPS 2022.
- **Cờ `has_identity`**: EDA cho thấy fraud rate 6,73% khi có bảng identity, so với 2,12% khi không. Đây là ứng viên feature cho Stage E.
- **Thí nghiệm drift theo thời gian**: đo hiệu năng baseline giảm thế nào khi phân phối dữ liệu thay đổi giữa train và test.
- **Kết nối hai sản phẩm**: điểm rủi ro gian lận (Product 02) và tín hiệu độ tin cậy (Product 01) cùng dùng chung contract sự kiện thanh toán.

**Ngoài phạm vi của demo:** Kafka, Spark, Kubernetes, MLflow, xác thực người dùng, chatbot/LLM, chặn giao dịch tự động.

## 6. Kiến thức cần sử dụng

| Mảng | Nội dung cần nắm | Dùng ở đâu |
| --- | --- | --- |
| **Nghiệp vụ thanh toán** | Vòng đời giao dịch (payment, attempt), provider/merchant, mã lỗi, độ trễ; các loại gian lận phổ biến | Contract, Product 01, Product 02 |
| **Data contract** | JSON Schema, versioning theo semver, kiểm tra ràng buộc chéo trường | `contracts/payment-event/` |
| **Quản trị dữ liệu** | Nguồn gốc dữ liệu, checksum SHA-256, giấy phép dataset, không lưu dữ liệu nhạy cảm | `datasets/manifests/`, `docs/data-governance/` |
| **Phân tích dữ liệu (EDA)** | Missing values, mất cân bằng lớp, phân phối lệch và biến đổi log, biến phân loại nhiều giá trị | `fraud_risk/eda/` |
| **Đánh giá mô hình** | Chia theo thời gian, rò rỉ dữ liệu (leakage), PR-AUC, precision/recall/F1, FPR, chọn ngưỡng, bootstrap confidence interval; vì sao accuracy gây hiểu nhầm khi dữ liệu mất cân bằng | `fraud_risk/evaluation/` |
| **Machine learning** | Baseline dựa trên luật, Logistic Regression, scikit-learn `Pipeline`, `class_weight`; sau này Gradient Boosting và Isolation Forest | `fraud_risk/baselines/` |
| **Tái lập thí nghiệm** | Seed, config đóng băng, `run_id` tất định, quy tắc test-một-lần | `fraud_risk/evaluation/run_log.py` |
| **Kỹ thuật dữ liệu** | PostgreSQL, Parquet, pipeline ingestion, dbt (Stage D) | `infrastructure/`, Stage C–D |
| **Phát hiện bất thường** | Ngưỡng thống kê trên chuỗi thời gian KPI, phân biệt bất thường và sự cố | Product 01 (Stage D) |
| **Công cụ** | Python 3.11, `uv`, `pandas`, `numpy`, `pytest`, `ruff`, Docker Compose, Git (mỗi task một nhánh) | Toàn dự án |

**Tài liệu tham khảo chính**
- IEEE-CIS Fraud Detection (Kaggle): dataset chính của Product 02. Chỉ dùng cho nghiên cứu, theo điều khoản cuộc thi.
- Jesus et al., *Turning the Tables: Biased, Imbalanced, Dynamic Tabular Datasets for ML Evaluation*, NeurIPS 2022 ([arXiv 2211.13358](https://arxiv.org/abs/2211.13358)). Căn cứ cho việc chia theo thời gian và metric recall tại FPR cố định. Chỉ dùng làm tài liệu tham khảo, không dùng dataset của bài.

## 7. Bắt đầu nhanh

```bash
make setup   # cài môi trường
make lint    # kiểm tra code style
make test    # chạy test
make up      # khởi động PostgreSQL
```

Dataset IEEE-CIS phải do chủ dự án tải thủ công từ Kaggle và đặt vào `datasets/raw/ieee-cis/`. Không commit dataset.
