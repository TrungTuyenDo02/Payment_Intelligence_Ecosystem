"""Regenerate the README diagrams (SVG).

Usage: python docs/assets/diagrams/build_diagrams.py docs/assets/diagrams
"""

# ruff: noqa: E501  (SVG markup lines are long by nature)

import sys
from html import escape
from pathlib import Path

OUT = sys.argv[1]
FONT = "Segoe UI, Helvetica Neue, Helvetica, Arial, sans-serif"
# kind: (fill, stroke, ink, sub-label ink)
K = {
    "step": ("#eef2fb", "#3b5ea8", "#1b2a4a", "#3b5ea8"),
    "goal": ("#e3f5e6", "#2e8b3e", "#123d1b", "#2e8b3e"),
    "warn": ("#fdf3e1", "#b7791f", "#5a3a07", "#b7791f"),
    "todo": ("#ffffff", "#9aa3b2", "#5a6170", "#7a8190"),
    "prod": ("#1b2a4a", "#1b2a4a", "#ffffff", "#c9d3e6"),
    "muted": ("#f5f5f5", "#b5b5b5", "#8a8a8a", "#8a8a8a"),
}
STATUS = [("goal", "Đã xong"), ("warn", "Đang làm"), ("todo", "Chưa làm")]


class Svg:
    def __init__(self, w, h):
        self.w, self.h, self.parts = w, h, []

    def add(self, x):
        self.parts.append(x)

    def box(self, x, y, w, h, text, kind="step", bold=False, dashed=False, size=14, sub=None):
        fill, stroke, ink, sub_ink = K[kind]
        da = ' stroke-dasharray="5 4"' if dashed else ""
        self.add(
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="9" fill="{fill}" stroke="{stroke}" stroke-width="1.3"{da}/>'
        )
        lines = text.split("\n")
        n = len(lines) + (1 if sub else 0)
        lh = size * 1.3
        y0 = y + h / 2 - (n - 1) * lh / 2 + size * 0.35
        wt = "700" if bold else "400"
        for i, ln in enumerate(lines):
            self.add(
                f'<text x="{x + w / 2}" y="{y0 + i * lh:.1f}" text-anchor="middle" font-size="{size}" font-weight="{wt}" fill="{ink}">{escape(ln)}</text>'
            )
        if sub:
            self.add(
                f'<text x="{x + w / 2}" y="{y0 + len(lines) * lh:.1f}" text-anchor="middle" font-size="{size - 3}" fill="{sub_ink}">{escape(sub)}</text>'
            )

    def lane(self, x, y, text):
        self.add(
            f'<text x="{x}" y="{y}" font-size="13" font-weight="700" fill="#8a8f98">{escape(text)}</text>'
        )

    def arrow(self, pts, dashed=False, color="#7a7f87", label=None, lpos=None):
        d = "M " + " L ".join(f"{a},{b}" for a, b in pts)
        da = ' stroke-dasharray="6 4"' if dashed else ""
        self.add(
            f'<path d="{d}" fill="none" stroke="{color}" stroke-width="1.6"{da} marker-end="url(#ah)"/>'
        )
        if label:
            lx, ly = lpos
            self.add(
                f'<rect x="{lx - len(label) * 3.6 - 6}" y="{ly - 12}" width="{len(label) * 7.2 + 12}" height="18" rx="4" fill="#ffffff"/>'
            )
            self.add(
                f'<text x="{lx}" y="{ly + 1}" text-anchor="middle" font-size="12" fill="#5a5f66">{escape(label)}</text>'
            )

    def text(self, x, y, t, size=12, color="#5a5f66", anchor="start", bold=False):
        wt = "700" if bold else "400"
        self.add(
            f'<text x="{x}" y="{y}" text-anchor="{anchor}" font-size="{size}" font-weight="{wt}" fill="{color}">{escape(t)}</text>'
        )

    def legend(self, x, y, items, gap=150):
        for j, (kind, lab) in enumerate(items):
            fill, stroke, _, _ = K[kind]
            da = ' stroke-dasharray="3 2"' if kind == "todo" else ""
            self.add(
                f'<rect x="{x + j * gap}" y="{y - 11}" width="14" height="14" rx="3" fill="{fill}" stroke="{stroke}"{da}/>'
            )
            self.text(x + j * gap + 20, y, lab, 12)

    def save(self, name):
        head = (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.w}" height="{self.h}" viewBox="0 0 {self.w} {self.h}" font-family="{FONT}">'
            '<defs><marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
            '<path d="M0,0 L10,5 L0,10 z" fill="#7a7f87"/></marker></defs>'
            f'<rect width="{self.w}" height="{self.h}" rx="12" fill="#ffffff"/>'
        )
        Path(OUT, name).write_text(head + "\n".join(self.parts) + "</svg>\n", encoding="utf-8")


# ---------- 1. System overview ----------
s = Svg(1120, 470)
BW, BH, GAP, X0 = 150, 56, 22, 30
xs = [X0 + i * (BW + GAP) for i in range(5)]
PX, PW = 905, 180
rows = {"rel": 44, "fraud": 156, "found": 268}
s.lane(30, 30, "Payment Reliability (Product 01) · dữ liệu giả lập")
for x, (t, k) in zip(
    xs,
    [
        ("Bộ sinh dữ liệu\n(config + seed)", "goal"),
        ("Kiểm tra contract\n+ PostgreSQL", "goal"),
        ("KPI theo\nthời gian", "goal"),
        ("Phát hiện\nbất thường", "goal"),
        ("Dashboard\nsự cố", "todo"),
    ],
    strict=True,
):
    s.box(x, rows["rel"], BW, BH, t, k, dashed=(k == "todo"))
s.box(PX, rows["rel"], PW, BH, "Product 01", "prod", bold=True, sub="Hệ thống có chạy ổn không?")
s.lane(30, 142, "Fraud & Risk (Product 02) · IEEE-CIS")
for x, (t, k) in zip(
    xs,
    [
        ("IEEE-CIS\n(Kaggle, có nhãn)", "goal"),
        ("Adapter + chia\ntheo thời gian", "goal"),
        ("EDA + quyết định\ntiền xử lý", "goal"),
        ("Baseline: luật\n+ Logistic Reg.", "goal"),
        ("Rò rỉ dữ liệu\n+ Gradient Boosting", "warn"),
    ],
    strict=True,
):
    s.box(x, rows["fraud"], BW, BH, t, k, dashed=(k == "todo"))
s.box(PX, rows["fraud"], PW, BH, "Product 02", "prod", bold=True, sub="Giao dịch này có đáng nghi?")
s.lane(30, 254, "Nền tảng dùng chung (Shared Foundation)")
for x, t in zip(
    xs[1:],
    [
        "Contract\npayment-event",
        "Quản lý dataset\nmanifest",
        "Quy tắc đánh giá\nsplit · test 1 lần",
        "Docker\n+ PostgreSQL",
    ],
    strict=True,
):
    s.box(x, rows["found"], BW, BH, t, "goal")
s.box(PX, rows["found"], PW, BH, "Foundation", "prod", bold=True, sub="Dùng chung cho cả hai")
for key in ("rel", "fraud"):
    y = rows[key] + BH / 2
    for i in range(4):
        s.arrow([(xs[i] + BW, y), (xs[i + 1] - 2, y)])
    s.arrow([(xs[4] + BW, y), (PX - 2, y)])
yf = rows["found"] + BH / 2
for i in range(1, 4):
    s.arrow([(xs[i] + BW, yf), (xs[i + 1] - 2, yf)])
s.arrow([(xs[4] + BW, yf), (PX - 2, yf)])
s.arrow([(PX + PW / 2, rows["found"]), (PX + PW / 2, rows["fraud"] + BH + 2)])
s.arrow(
    [
        (PX + PW, yf),
        (PX + PW + 18, yf),
        (PX + PW + 18, rows["rel"] + BH / 2),
        (PX + PW + 2, rows["rel"] + BH / 2),
    ]
)
s.lane(30, 372, "Ngoài phạm vi đề tài (chỉ minh hoạ vị trí trong hệ thống lớn)")
for x, t in zip(
    xs[:3], ["Đối soát /\nsettlement", "Phân tích\nmerchant", "Phân tích\nkhách hàng"], strict=True
):
    s.box(x, 386, BW, 46, t, "muted", dashed=True, size=13)
s.legend(560, 414, STATUS, gap=175)
s.save("system-overview.svg")

# ---------- 2. Roadmap ----------
s = Svg(1120, 420)
LX, GX, GW = 30, 300, 130
s.text(LX, 34, "Giai đoạn", 13, "#8a8f98", bold=True)
for w in range(6):
    x = GX + w * GW
    s.add(
        f'<rect x="{x}" y="46" width="{GW}" height="320" fill="{"#fafbfd" if w % 2 == 0 else "#ffffff"}"/>'
    )
    s.text(x + GW / 2, 34, f"Tuần {w + 1}", 13, "#8a8f98", "middle", bold=True)
stages = [
    ("A · Nền tảng", 0, 2, "goal", "Repo, Docker, contract, manifest"),
    ("B · Fraud baseline", 0, 2, "goal", "Adapter, split, EDA, 2 baseline, run log"),
    ("C · Dữ liệu giả lập", 2, 1, "goal", "Bộ sinh dữ liệu\n+ ingestion"),
    ("D · Reliability", 3, 1, "goal", "KPI\n+ bất thường"),
    ("E · Fraud nâng cao", 4, 1, "warn", "Rò rỉ + GBM\n(API: cắt)"),
    ("F · Hoàn thiện", 5, 1, "todo", "Dashboard\n+ báo cáo"),
]
for i, (name, start, length, kind, desc) in enumerate(stages):
    y = 58 + i * 52
    s.text(LX, y + 27, name, 14, "#1b2a4a", bold=True)
    s.box(
        GX + start * GW + 6,
        y,
        length * GW - 12,
        44,
        desc,
        kind,
        dashed=(kind == "todo"),
        size=12 if length == 1 else 13,
    )
tx = GX + 4 * GW
s.add(
    f'<line x1="{tx}" y1="46" x2="{tx}" y2="366" stroke="#d14343" stroke-width="2" stroke-dasharray="4 3"/>'
)
s.text(tx, 384, "hiện tại: tuần 5", 12, "#d14343", "middle", bold=True)
s.legend(30, 404, STATUS, gap=175)
s.save("roadmap.svg")

# ---------- 3. Workflow ----------
s = Svg(1120, 300)
BW, BH, Y = 150, 58, 60
xs = [30 + i * 182 for i in range(6)]
labels = [
    ("Task trong\nkế hoạch", "step"),
    ("Nhánh\ntask/<ID>", "step"),
    ("Pull request\nvào main", "step"),
    ("CI GitHub\nlint + test", "warn"),
    ("Chủ dự án\nreview", "warn"),
    ("Merge\nvào main", "goal"),
]
for x, (t, k) in zip(xs, labels, strict=False):
    s.box(x, Y, BW, BH, t, k, bold=(k == "goal"))
for i in range(5):
    lab = {3: "xanh", 4: "duyệt"}.get(i)
    s.arrow([(xs[i] + BW, Y + BH / 2), (xs[i + 1] - 2, Y + BH / 2)])
    if lab:
        s.text((xs[i] + BW + xs[i + 1]) / 2, Y + BH / 2 - 8, lab, 11, "#2e8b3e", "middle")
bx = xs[1] + BW / 2
s.arrow(
    [
        (xs[3] + BW / 2, Y + BH),
        (xs[3] + BW / 2, Y + BH + 30),
        (bx + 12, Y + BH + 30),
        (bx + 12, Y + BH + 2),
    ],
    label="CI đỏ: sửa trên nhánh",
    lpos=((xs[3] + bx) / 2 + 40, Y + BH + 30),
)
s.arrow(
    [
        (xs[4] + BW / 2, Y + BH),
        (xs[4] + BW / 2, Y + BH + 58),
        (bx - 12, Y + BH + 58),
        (bx - 12, Y + BH + 2),
    ],
    label="cần sửa",
    lpos=((xs[4] + bx) / 2 + 60, Y + BH + 58),
)
s.lane(30, 40, "Mỗi thay đổi đi qua pull request; CI chạy trên Python 3.11 và 3.13")
s.lane(30, 228, "Điểm dừng chỉ chủ dự án thông qua")
for i, t in enumerate(
    ["Duyệt contract", "Duyệt quyết định EDA", "Đặt config frozen", "Chạy đánh giá test"]
):
    s.box(30 + i * 200, 240, 180, 40, t, "muted", size=13)
s.save("workflow.svg")
