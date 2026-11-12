# Báo cáo tuần

Mỗi tuần một file `YYYY-Www.md` (tuần ISO, ví dụ `2026-W46.md`), viết cho mentor: đọc trong 3 phút, mọi con số truy được về một lần chạy hoặc một commit. Sao chép khung dưới đây cho tuần mới.

Quy tắc:

- Con số test (đã công bố) chỉ **trích lại**, kèm mã lần chạy; không chạy lại.
- Kết quả trên validation ghi rõ **thăm dò**.
- Không dùng ngôn ngữ cam kết vận hành ("sẽ bắt được X%"). Viết: "trong dữ liệu phát triển, dưới giả định A, quan sát được B".
- Mục "Hạn chế" không được để trống.

```markdown
# Báo cáo tuần YYYY-Www (dd/mm – dd/mm/yyyy)

## 1. Đã làm

| Việc | Commit / nhánh | Kiểm chứng |
| --- | --- | --- |
| … | `abc1234` | `make lint test`: N pass, M skip |

## 2. Kết quả

| Kết quả | Số liệu | Mã lần chạy | Loại (test một lần / thăm dò) |
| --- | --- | --- | --- |
| … | … | `run-…` | … |

## 3. Chạy lại

Lệnh để người đọc tự chạy lại phần chính của tuần.

## 4. Hạn chế (kết quả tuần này không chứng minh)

- …

## 5. Tuần sau

- …

## 6. Cần mentor / chủ dự án quyết định

- …
```
