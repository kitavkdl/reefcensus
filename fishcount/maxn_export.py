"""MaxN table in the layout ecologists load into GlobalArchive / CheckEM (BRUV workflows).

Added after the evaluation (not used in any paper number). It only re-lays-out what web/server.effective() already
returns, so human review decisions apply exactly as in the plain CSV export.

Layout (README, "Standard MaxN export"): OpCode, Family, Genus, Species, MaxN, Frame, Time_mins come first, in the
names EventMeasure / GlobalArchive use. Family, Genus and Species are ALWAYS blank: Muse Spark gives common names, not
verified taxonomy, so the name goes in the clearly named column `spark_common_name` and a person fills the taxonomy.
Like CheckEM's maxn table, only rows with MaxN > 0 are written, and the group rows of the plain CSV are not (a group
is not a taxon).

  python3 fishcount/maxn_export.py <run id> [--opcode CODE] [-o out.csv]
"""
import csv, io, os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

COLUMNS = ["OpCode", "Family", "Genus", "Species", "MaxN", "Frame", "Time_mins",
           "spark_common_name", "maxn_confirmed", "origin", "taxonomy_status", "source_file", "run_id", "human_edits",
           "maxn_lower_bound"]


def default_opcode(e):
    """OpCode = the deployment code. We know no deployment metadata, so the video's file name stands in for it."""
    return os.path.splitext(e.get("source") or e.get("id") or "")[0]


def _cell(v):
    return "'" + v if isinstance(v, str) and v[:1] in "=+-@" else v      # no formulas from model text


def rows(e, opcode=None):
    """e = server.effective(run id). One row per label with MaxN > 0, biggest first."""
    opcode = opcode or default_opcode(e)
    out = []
    for name, m in sorted(e["metrics"].items(), key=lambda kv: (-kv[1]["maxn"], kv[0])):
        if m["maxn"] <= 0:
            continue
        mins = None if m.get("maxn_time") is None else round(m["maxn_time"] / 60, 3)
        out.append([_cell(opcode), "", "", "", m["maxn"], m["maxn_frame"], mins,
                    _cell(name), m.get("maxn_confirmed", m["maxn"]), e.get("origin", {}).get(name, ""),
                    "not verified: common name from Muse Spark or a reviewer", _cell(e.get("source") or ""), e.get("id", ""),
                    e.get("n_reviewed", 0), _lower_bound(e, name, m)])
    return out


def _lower_bound(e, name, m):
    """Crowd check (pipeline.crowd_check): the label's own row or its animal group's row is a lower bound."""
    rows = [(name, m)] + [(g, gg) for g, gg in (e.get("group_metrics") or {}).items() if name in gg.get("labels", [])]
    for row, r in rows:
        if r.get("lower_bound"):
            return f"yes ({row}): Spark counts about {r.get('crowd_total')} in frame {r.get('crowd_frame')} without boxes"
    return ""


def to_csv(e, opcode=None):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(COLUMNS)
    w.writerows(rows(e, opcode))
    return buf.getvalue()


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("run")
    ap.add_argument("--opcode", help="deployment code for the OpCode column (default: the video file name)")
    ap.add_argument("-o", "--out", help="write here instead of stdout")
    a = ap.parse_args()
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web"))
    import server
    eff = server.effective(a.run)
    if not eff:
        sys.exit(f"no finished result for run {a.run}")
    text = to_csv(eff, a.opcode)
    if a.out:
        open(a.out, "w", newline="").write(text)
    else:
        sys.stdout.write(text)
