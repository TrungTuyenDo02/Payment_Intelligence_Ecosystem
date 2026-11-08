# Báo cáo thực tập (LaTeX)

Biên dịch bằng XeLaTeX (cần font TeX Gyre Heros và DejaVu Sans Mono, có sẵn trong TeX Live):

```bash
xelatex bai-bao-khoa-hoc.tex && xelatex bai-bao-khoa-hoc.tex
```

Hai file nguồn: `bao-cao-thuc-tap.tex` (báo cáo thực tập, giải thích chi tiết) và `bai-bao-khoa-hoc.tex` (dạng bài báo khoa học, 10 trang). Chạy hai lần để có mục lục và tham chiếu. Sau đó chép file PDF ra `docs/report/`. Hình trong `figures/` lấy từ `docs/assets/` (sơ đồ SVG xuất PNG gấp đôi độ phân giải). Trên Overleaf: chọn compiler XeLaTeX.
