"""Small inline-SVG charts for the static dashboard (ADR 0007: no new library, works offline).

Colors are CSS custom properties (`var(--s1)` …) defined by the page, so light and dark mode
swap in one place. Every mark that carries data has a `data-tip` attribute; a few lines of
page JavaScript show it as a tooltip (and a crosshair on line charts). Each chart is also
paired with a table or direct labels on the page, so nothing depends on hover or color alone.
"""

import math
from collections.abc import Callable, Sequence
from html import escape

Fmt = Callable[[float], str]

W = 960  # viewBox width; the SVG scales to its container
PAD_L, PAD_R, PAD_T, PAD_B = 56, 96, 16, 28


def nice_ticks(lo: float, hi: float, n: int = 4) -> list[float]:
    """About `n` round tick values covering [lo, hi]."""
    if not math.isfinite(lo) or not math.isfinite(hi):
        return [0.0]
    if hi <= lo:
        hi = lo + (abs(lo) or 1.0)
    raw = (hi - lo) / n
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
    start = math.floor(lo / step + 1e-9) * step
    end = math.ceil(hi / step - 1e-9) * step  # the top tick is >= the largest value
    count = round((end - start) / step)
    return [round(start + k * step, 12) for k in range(count + 1)]


def _svg(height: int, body: str, label: str, width: int = W) -> str:
    return (
        f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="{escape(label)}" '
        f'preserveAspectRatio="xMidYMid meet">{body}</svg>'
    )


def _spread(ys: list[float], gap: float, lo: float, hi: float) -> list[float]:
    """Move direct labels apart vertically (keeps order, stays inside [lo, hi])."""
    order = sorted(range(len(ys)), key=lambda i: ys[i])
    out = list(ys)
    for a, b in zip(order, order[1:], strict=False):
        out[b] = max(out[b], out[a] + gap)
    over = max((out[i] - hi for i in order), default=0)
    if over > 0:
        out = [y - over for y in out]
    return [max(lo, y) for y in out]


def line_chart(
    labels: Sequence[str],
    series: Sequence[tuple[str, int, Sequence[float | None]]],
    *,
    y_fmt: Fmt,
    title: str,
    x_ticks: Sequence[tuple[int, str]] = (),
    bands: Sequence[tuple[int, int, str, str]] = (),
    height: int = 240,
    y_min: float | None = 0.0,
    y_max: float | None = None,
    markers: bool = False,
    width: int = W,
) -> str:
    """Lines over evenly spaced x positions; `labels` name each x (tooltip header).

    series: (name, color slot 1-8, values with None for gaps).
    bands: (first index, last index, css class, tooltip) shaded behind the lines.
    """
    n = len(labels)
    values = [v for _, _, vs in series for v in vs if v is not None and math.isfinite(v)]
    if n == 0 or not values:
        return '<p class="empty">Không có dữ liệu để vẽ.</p>'
    lo = min(values) if y_min is None else min(y_min, min(values))
    hi = max(values) if y_max is None else max(y_max, max(values))
    ticks = nice_ticks(lo, hi, 3 if height < 160 else 4)
    y0, y1 = ticks[0], ticks[-1] if ticks[-1] > ticks[0] else ticks[0] + 1
    plot_w, plot_h = width - PAD_L - PAD_R, height - PAD_T - PAD_B
    step = plot_w / max(n - 1, 1)

    def x(i: float) -> float:
        return PAD_L + i * step

    def y(v: float) -> float:
        return PAD_T + plot_h * (1 - (v - y0) / (y1 - y0))

    parts = []
    for i0, i1, cls, tip in bands:
        left, right = x(i0) - step / 2, x(i1) + step / 2
        parts.append(
            f'<rect class="{cls}" x="{max(left, PAD_L):.1f}" y="{PAD_T}" '
            f'width="{max(right - max(left, PAD_L), 2):.1f}" height="{plot_h}" '
            f'data-tip="{escape(tip)}"/>'
        )
    for t in ticks:
        parts.append(f'<line class="grid" x1="{PAD_L}" x2="{width - PAD_R}" y1="{y(t):.1f}" '
                     f'y2="{y(t):.1f}"/>')  # fmt: skip
        parts.append(f'<text class="tick" x="{PAD_L - 8}" y="{y(t) + 4:.1f}" '
                     f'text-anchor="end">{escape(y_fmt(t))}</text>')  # fmt: skip
    parts.append(f'<line class="axis" x1="{PAD_L}" x2="{width - PAD_R}" y1="{y(y0):.1f}" '
                 f'y2="{y(y0):.1f}"/>')  # fmt: skip
    for i, text in x_ticks:
        parts.append(f'<text class="tick" x="{x(i):.1f}" y="{height - 8}" '
                     f'text-anchor="middle">{escape(text)}</text>')  # fmt: skip

    ends: list[tuple[float, str, int]] = []
    for name, slot, vs in series:
        path, pen = [], False
        for i, v in enumerate(vs):
            if v is None or not math.isfinite(v):
                pen = False
                continue
            path.append(f"{'L' if pen else 'M'}{x(i):.1f},{y(v):.1f}")
            pen = True
        parts.append(f'<path class="line" style="stroke:var(--s{slot})" d="{" ".join(path)}"/>')
        if markers:
            parts += [
                f'<circle class="dot" cx="{x(i):.1f}" cy="{y(v):.1f}" r="4" '
                f'style="fill:var(--s{slot})"/>'
                for i, v in enumerate(vs) if v is not None and math.isfinite(v)
            ]  # fmt: skip
        last = next((v for v in reversed(vs) if v is not None and math.isfinite(v)), None)
        if last is not None:
            ends.append((y(last), name, slot))
    ys = _spread([e[0] for e in ends], 14, PAD_T + 6, PAD_T + plot_h)
    for (_, name, slot), yy in zip(ends, ys, strict=True):
        parts.append(f'<circle cx="{width - PAD_R + 10}" cy="{yy - 4:.1f}" r="4" '
                     f'style="fill:var(--s{slot})"/>')  # fmt: skip
        parts.append(f'<text class="direct" x="{width - PAD_R + 18}" y="{yy:.1f}">'
                     f"{escape(name)}</text>")  # fmt: skip

    # Hover columns: one invisible rect per x with every series' value (crosshair + tooltip).
    for i, lab in enumerate(labels):
        rows = "".join(
            f"<br><i style='background:var(--s{slot})'></i>{escape(name)}: "
            f"<b>{escape(y_fmt(vs[i]) if vs[i] is not None and math.isfinite(vs[i]) else '—')}</b>"
            for name, slot, vs in series
        )
        notes = "".join(f"<br><small>{b[3]}</small>" for b in bands if b[0] <= i <= b[1])
        tip = escape("<b>" + escape(lab) + "</b>" + rows + notes)
        parts.append(
            f'<rect class="hover" x="{x(i) - step / 2:.1f}" y="{PAD_T}" width="{step:.2f}" '
            f'height="{plot_h}" data-cx="{x(i):.1f}" data-tip="{tip}"/>'
        )
    parts.append(f'<line class="crosshair" x1="0" x2="0" y1="{PAD_T}" y2="{PAD_T + plot_h}"/>')
    return _svg(height, "".join(parts), title, width)


def bar_chart(
    rows: Sequence[tuple[str, float, str, str]],
    *,
    x_fmt: Fmt,
    title: str,
    ref: tuple[float, str] | None = None,
    value_fmt: Fmt | None = None,
    width: int = W,
    label_w: int = 230,
) -> str:
    """Horizontal bars: (label, value, css fill, tooltip). Value printed at the bar end.

    `ref` draws one labelled reference line (for example the true fraud rate).
    """
    if not rows:
        return '<p class="empty">Không có dữ liệu để vẽ.</p>'
    bar_h, gap, right = 22, 10, 90
    top_pad = PAD_T + (18 if ref else 0)  # room for the reference label above the bars
    height = top_pad + len(rows) * (bar_h + gap) + 24
    hi = max([r[1] for r in rows] + ([ref[0]] if ref else []))
    ticks = nice_ticks(0, hi)
    top = ticks[-1] or 1.0
    plot_w = width - label_w - right

    def x(v: float) -> float:
        return label_w + plot_w * v / top

    parts = []
    for t in ticks:
        parts.append(f'<line class="grid" x1="{x(t):.1f}" x2="{x(t):.1f}" y1="{PAD_T - 4}" '
                     f'y2="{height - 22}"/>')  # fmt: skip
        parts.append(f'<text class="tick" x="{x(t):.1f}" y="{height - 6}" '
                     f'text-anchor="middle">{escape(x_fmt(t))}</text>')  # fmt: skip
    for k, (label, value, fill, tip) in enumerate(rows):
        yy = top_pad + k * (bar_h + gap)
        bar_w = max(x(value) - label_w, 1.5)
        parts.append(f'<text class="label" x="{label_w - 10}" y="{yy + bar_h / 2 + 4}" '
                     f'text-anchor="end">{escape(label)}</text>')  # fmt: skip
        # Square at the baseline, rounded (4px) at the data end.
        r = min(4.0, bar_w / 2)
        d = (f"M{label_w},{yy} H{label_w + bar_w - r} Q{label_w + bar_w},{yy} "
             f"{label_w + bar_w},{yy + r} V{yy + bar_h - r} Q{label_w + bar_w},{yy + bar_h} "
             f"{label_w + bar_w - r},{yy + bar_h} H{label_w} Z")  # fmt: skip
        parts.append(f'<path class="bar {fill}" d="{d}" data-tip="{escape(tip)}"/>')
        parts.append(f'<text class="value" x="{label_w + bar_w + 6}" y="{yy + bar_h / 2 + 4}">'
                     f"{escape((value_fmt or x_fmt)(value))}</text>")  # fmt: skip
    if ref:
        parts.append(f'<line class="ref" x1="{x(ref[0]):.1f}" x2="{x(ref[0]):.1f}" '
                     f'y1="{PAD_T - 6}" y2="{height - 22}"/>')  # fmt: skip
        parts.append(f'<text class="ref-label" x="{x(ref[0]) + 4:.1f}" y="{PAD_T + 6}">'
                     f"{escape(ref[1])}</text>")  # fmt: skip
    return _svg(height, "".join(parts), title, width)


def histogram(
    edges: Sequence[float], counts: Sequence[int], *, x_fmt: Fmt, title: str, unit: str
) -> str:
    """Vertical bars of counts per bin [edges[i], edges[i+1])."""
    if not counts:
        return '<p class="empty">Không có dữ liệu để vẽ.</p>'
    height = 200
    plot_w, plot_h = W - PAD_L - 24, height - PAD_T - PAD_B
    ticks = nice_ticks(0, max(counts))
    top = ticks[-1] or 1
    bw = plot_w / len(counts)

    def y(v: float) -> float:
        return PAD_T + plot_h * (1 - v / top)

    parts = []
    for t in ticks:
        parts.append(f'<line class="grid" x1="{PAD_L}" x2="{W - 24}" y1="{y(t):.1f}" '
                     f'y2="{y(t):.1f}"/>')  # fmt: skip
        parts.append(f'<text class="tick" x="{PAD_L - 8}" y="{y(t) + 4:.1f}" '
                     f'text-anchor="end">{t:g}</text>')  # fmt: skip
    for i, c in enumerate(counts):
        x0 = PAD_L + i * bw + 1
        tip = f"{x_fmt(edges[i])}–{x_fmt(edges[i + 1])}: <b>{c}</b> {unit}"
        parts.append(f'<rect class="bar fill-s1" x="{x0:.1f}" y="{y(c):.1f}" '
                     f'width="{max(bw - 2, 1):.1f}" height="{max(y(0) - y(c), 0):.1f}" '
                     f'rx="2" data-tip="{escape(tip)}"/>')  # fmt: skip
    for i in range(0, len(edges), max(len(edges) // 5, 1)):
        parts.append(f'<text class="tick" x="{PAD_L + i * bw:.1f}" y="{height - 8}" '
                     f'text-anchor="middle">{escape(x_fmt(edges[i]))}</text>')  # fmt: skip
    parts.append(f'<line class="axis" x1="{PAD_L}" x2="{W - 24}" y1="{y(0):.1f}" '
                 f'y2="{y(0):.1f}"/>')  # fmt: skip
    return _svg(height, "".join(parts), title)
