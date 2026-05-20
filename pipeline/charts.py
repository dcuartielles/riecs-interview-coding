"""Theme charts for the analysis reports.

Renders two diagrams from the corpus theme matrix as PNG bytes, suitable for
embedding in both the HTML and DOCX reports:

  * theme_frequency_chart   — themes ranked by relevance
  * theme_cooccurrence_chart — themes linked by shared interviews

Relevance is derived from the ordinal frequency rating each theme receives
per interview (high / medium / low), mapped to a numeric score and summed
across the corpus.
"""

import io
import math
import textwrap

import matplotlib

matplotlib.use("Agg")  # headless: no display required
import matplotlib.pyplot as plt  # noqa: E402

# RIECS brand palette (mirrors .streamlit/config.toml).
_TEAL = "#376782"
_NAVY = "#2c324c"
_STEEL = "#648a9e"
_EDGE = "#a9c0d2"
_CREAM = "#f5f2ea"

_FREQ_SCORE = {"high": 3, "medium": 2, "low": 1}


def _relevance(by_interview: dict) -> int:
    """Sum the ordinal frequency ratings of a theme across all interviews."""
    return sum(_FREQ_SCORE.get(str(v).strip().lower(), 0)
               for v in by_interview.values())


def _fig_to_png(fig) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight",
                facecolor="white")
    plt.close(fig)
    return buf.getvalue()


def theme_frequency_chart(matrix_codes: dict) -> bytes | None:
    """Horizontal bar chart of themes ranked by relevance score.

    `matrix_codes` is the `codes` mapping from the corpus themes matrix.
    Returns PNG bytes, or None if there is nothing to plot.
    """
    if not matrix_codes:
        return None

    items = []
    for code, info in matrix_codes.items():
        by_iv = info.get("by_interview", {}) or {}
        label = info.get("label") or code
        items.append((label, _relevance(by_iv), len(by_iv)))
    if not items:
        return None

    items.sort(key=lambda x: x[1])  # ascending: highest bar ends up on top
    labels = [textwrap.fill(i[0], 28) for i in items]
    scores = [i[1] for i in items]
    counts = [i[2] for i in items]

    fig, ax = plt.subplots(figsize=(8, max(2.6, 0.62 * len(items) + 1.2)))
    bars = ax.barh(labels, scores, color=_TEAL, height=0.62)

    for bar, score, count in zip(bars, scores, counts):
        ax.text(bar.get_width() + max(scores) * 0.02,
                bar.get_y() + bar.get_height() / 2,
                f"{score}  ·  {count} interview{'s' if count != 1 else ''}",
                va="center", ha="left", fontsize=8, color=_NAVY)

    ax.set_xlim(0, max(scores) * 1.28 if scores else 1)
    ax.set_xlabel("Relevance score  (high = 3, medium = 2, low = 1, "
                  "summed across interviews)", fontsize=9, color=_NAVY)
    ax.set_title("Theme relevance", fontsize=13, color=_NAVY,
                 fontweight="bold", pad=12)
    ax.tick_params(axis="y", labelsize=9)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    ax.set_axisbelow(True)
    ax.xaxis.grid(True, color="#e4e4e4", linewidth=0.8)
    return _fig_to_png(fig)


def theme_cooccurrence_chart(matrix_codes: dict) -> bytes | None:
    """Co-occurrence map: themes on a circle, linked when they share interviews.

    Node size scales with relevance; edge width scales with the number of
    interviews in which both themes appear. Returns PNG bytes, or None if
    there are fewer than two themes.
    """
    if not matrix_codes or len(matrix_codes) < 2:
        return None

    codes = list(matrix_codes.items())
    n = len(codes)
    angles = [math.pi / 2 - 2 * math.pi * i / n for i in range(n)]
    pos = {code: (math.cos(a), math.sin(a))
           for (code, _), a in zip(codes, angles)}
    interviews_of = {
        code: set((info.get("by_interview", {}) or {}).keys())
        for code, info in codes
    }

    edges = []
    for i in range(n):
        ci = codes[i][0]
        for j in range(i + 1, n):
            cj = codes[j][0]
            weight = len(interviews_of[ci] & interviews_of[cj])
            if weight > 0:
                edges.append((ci, cj, weight))

    fig, ax = plt.subplots(figsize=(8, 8))
    max_w = max((w for *_, w in edges), default=1)
    for ci, cj, weight in edges:
        (x1, y1), (x2, y2) = pos[ci], pos[cj]
        ax.plot([x1, x2], [y1, y2], color=_EDGE,
                linewidth=1.0 + 4.0 * weight / max_w, alpha=0.75, zorder=1)

    for code, info in codes:
        x, y = pos[code]
        rel = _relevance(info.get("by_interview", {}) or {})
        ax.scatter([x], [y], s=420 + 240 * rel, color=_TEAL,
                   edgecolors="white", linewidths=1.5, zorder=2)
        label = textwrap.fill(info.get("label") or code, 18)
        ax.annotate(
            label, (x, y), (x * 1.22, y * 1.22),
            fontsize=8.5, color=_NAVY, zorder=3,
            ha="left" if x > 0.05 else ("right" if x < -0.05 else "center"),
            va="bottom" if y > 0.05 else ("top" if y < -0.05 else "center"),
        )

    ax.set_title("Theme co-occurrence  (shared interviews)", fontsize=13,
                 color=_NAVY, fontweight="bold", pad=14)
    ax.set_xlim(-1.7, 1.7)
    ax.set_ylim(-1.7, 1.7)
    ax.set_aspect("equal")
    ax.axis("off")
    return _fig_to_png(fig)
