"""Re-score the Spark-alone counting baseline from the bundled per-frame replies (no model, no video needed).
  python3 report/paper/scripts/spark_count_rescore.py
Prints, per set: MaxN exact / within ±1 / Σ|err| (pre-registered primary), per-frame MAE (pre-registered secondary),
frames where Spark equals / exceeds / is below the human box count, and an EXPLORATORY variant that was not in the
protocol: MaxN of the low median over five consecutive annotated frames (damps single-frame spikes, since the max of
many independent noisy per-frame counts is biased upward)."""
import json, os, statistics as st

D = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data/spark_count")
for name in ("dev", "held"):
    rows = json.load(open(os.path.join(D, f"{name}.json")))
    ex = w1 = se = eq = over = under = n = ae = exs = w1s = ses = 0
    for c in rows:
        fr = sorted(int(k) for k in c["per_frame"])
        h = [c["per_frame"][str(f)][0] for f in fr]
        s = [c["per_frame"][str(f)][1] for f in fr]
        n += len(fr); ae += sum(abs(a - b) for a, b in zip(h, s))
        eq += sum(a == b for a, b in zip(h, s)); over += sum(b > a for a, b in zip(h, s))
        under += sum(b < a for a, b in zip(h, s))
        e = max(s) - max(h); ex += e == 0; w1 += abs(e) <= 1; se += abs(e)
        sm = [st.median_low(s[max(0, i - 2):i + 3]) for i in range(len(s))]
        e2 = max(sm) - max(h); exs += e2 == 0; w1s += abs(e2) <= 1; ses += abs(e2)
    k = len(rows)
    print(f"{name:4s} clips {k:2d}  MaxN exact {ex}/{k} within1 {w1}/{k} sum|err| {se}  |  per-frame MAE {ae / n:.3f} "
          f"over {n} frames: equal {eq} ({eq / n:.0%}) above {over} below {under}  |  "
          f"exploratory median-of-5 MaxN: exact {exs}/{k} within1 {w1s}/{k} sum|err| {ses}")
