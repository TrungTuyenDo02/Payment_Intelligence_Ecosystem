# Đặc tả Stage F — Dashboard và báo cáo

- **Trạng thái:** **Đã duyệt theo uỷ quyền** (chủ dự án: "tự động theo đề xuất của agent", 2026-11-04). Chủ dự án có thể đổi bất kỳ quyết định nào ở mục 4.
- **Liên quan:** [ADR 0007](../decisions/0007-static-html-dashboard.md), [dàn ý báo cáo](../report/report-outline.md).

## 1. Mục tiêu

1. Một dashboard cho cả hai sản phẩm, dựng lại được bằng một lệnh, đủ để demo với mentor.
2. Dàn ý báo cáo thực tập, gắn mỗi số với run id và mỗi hình với file nguồn, để chủ dự án viết bản PDF.

## 2. Dashboard (`make dashboard`)

| Phần | Nguồn | Nội dung |
| --- | --- | --- |
| Product 01, vận hành | `artifacts/kpi/<sim>/provider_15m.parquet`, `artifacts/detections/<run>/[report/]incidents.json` | Ô số tổng (attempt, thành công, thành công lần đầu, lỗi kỹ thuật, số sự cố); bảng theo provider; tỷ lệ lỗi kỹ thuật và độ trễ theo giờ, giờ Việt Nam, tô vùng sự cố đúng chỉ số; danh sách sự cố |
| Product 01, đánh giá | `evaluation.json` | Bảng đối chiếu với sự cố đã cài sẵn, thu gọn mặc định |
| Product 02 | `artifacts/runs/**/metrics.json`, `artifacts/experiments/leak-*/summary.md` | So sánh mô hình (validation, test), thí nghiệm rò rỉ |

- Ưu tiên lần chạy detector trên bộ `report`; nếu chưa có thì dùng lần chạy tuning mới nhất.
- Biểu đồ ẩn các giờ có dưới 20 attempt: tỷ lệ tính trên vài attempt chủ yếu là nhiễu, đúng cái bẫy làm detector D-A báo nhầm ở Stage D.
- Số theo định dạng Việt Nam, thời gian theo giờ Việt Nam, màu provider theo bảng màu đã kiểm tra mù màu; luôn kèm nhãn trực tiếp hoặc bảng số.

## 3. Task

| ID | Task | Tiêu chí nghiệm thu |
| --- | --- | --- |
| F01 | `shared/dashboard/`, `make dashboard` | Có đủ hai sản phẩm khi có kết quả; ghi rõ lệnh cần chạy khi thiếu; thời gian hiển thị đúng giờ Việt Nam; ưu tiên lần chạy report; không tràn ngang ở bề rộng 390 px |
| F02 | Dàn ý báo cáo `docs/report/report-outline.md` | Mỗi số có run id, mỗi hình có file nguồn; phần chưa có số thật được đánh dấu |
| F03 | Cập nhật README, HANDOFF, tổng quan, sơ đồ | Trạng thái đúng với repo |

## 4. Quyết định (đề xuất của agent, áp dụng theo uỷ quyền)

| # | Câu hỏi | Quyết định | Lý do |
| --- | --- | --- | --- |
| F-Q1 | Công nghệ dashboard | HTML tĩnh (ADR 0007) | Không thêm thư viện; chạy offline; đưa vào báo cáo PDF được; tuần cuối không còn thời gian cho Grafana |
| F-Q2 | Nơi đặt code | `shared/dashboard/` | Dashboard đọc kết quả của **cả hai** sản phẩm, không thuộc riêng sản phẩm nào; chỉ đọc file kết quả nên không vi phạm ranh giới dữ liệu (ADR 0002) |
| F-Q3 | Có hiện nhãn sự cố đã cài sẵn không | Có, trong phần thu gọn riêng, ghi rõ là phần đánh giá | Người vận hành thật không có nhãn; mentor cần thấy kết quả đánh giá |
| F-Q4 | Commit file dashboard | Không; ghi vào `artifacts/dashboard/` | Sinh lại được bằng một lệnh; tránh commit số liệu IEEE-CIS chi tiết khi điều khoản Kaggle chưa được kiểm tra |
