"""Figure: luderick counting metrics for five audit-sheet designs (values from rescoring saved runs
runs/{eval,eval3,eval4,eval5,eval6}_fish_* with evaluate_pipeline's scorer at IoU 0.3)."""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

variants = ["V1 one crop", "V2 three moments", "V3 V2 + captions", "V4 judged frame at end", "V5 / V6 (V2 layout)"]
recall = [95.9, 97.4, 97.4, 96.3, 97.4]
exact = [3, 4, 4, 5, 4]
queue = [13, 7, 10, 9, 9]
LIGHT, DARK, INK, MUTED = "#86b6ef", "#2a78d6", "#0b0b0b", "#52514e"
cols = [LIGHT] * 4 + [DARK]

plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9, "axes.edgecolor": "#c9c8c3",
                     "axes.labelcolor": MUTED, "xtick.color": MUTED, "ytick.color": INK})
fig, axs = plt.subplots(1, 3, figsize=(7.2, 2.3), sharey=True, gridspec_kw={"wspace": 0.12})
panels = [(recall, "Recall (%)", (94, 98), "{:.1f}"), (exact, "Clips with exact MaxN (of 6)", (0, 6), "{:d}"),
          (queue, "Tracks sent to a person (of 27)", (0, 27), "{:d}")]
y = list(range(len(variants)))[::-1]
for ax, (vals, title, lim, fmt) in zip(axs, panels):
    if lim[0] > 0:   # a truncated axis gets dots, not bars (bar length must start at zero)
        ax.scatter(vals, y, s=46, color=cols, edgecolor="white", linewidth=1.5, zorder=3)
    else:
        ax.barh(y, vals, height=0.62, color=cols, edgecolor="white", linewidth=2)
    for yy, v in zip(y, vals):
        ax.text(v + (lim[1] - lim[0]) * (0.05 if lim[0] > 0 else 0.015), yy, fmt.format(v), va="center", fontsize=8, color=INK)
    ax.set_xlim(lim[0], lim[1] + (lim[1] - lim[0]) * (0.2 if lim[0] > 0 else 0.12))
    ax.set_title(title, fontsize=9, color=INK, loc="left")
    ax.grid(axis="x", color="#ecebe7", linewidth=0.8)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
axs[0].set_yticks(y, variants)
axs[0].tick_params(axis="y", length=0)
fig.savefig("report/paper/figures/ablation.png", dpi=220, bbox_inches="tight", facecolor="white")
print("ok")
