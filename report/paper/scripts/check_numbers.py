"""Cross-check the numbers and claims that appear in more than one document (paper, READMEs, demo page, and any
extra drafts passed on the command line) against one registry of the measured values.

  python3 report/paper/scripts/check_numbers.py [extra.md ...]

Each FACT has a regex that recognises a mention of that quantity and the value(s) it must have. Every mention is
listed; a mention whose value differs is marked MISMATCH. STALE lists phrases that should no longer appear at all
(retracted numbers, removed data, wording two reviews flagged). Nothing is changed; exit code 1 if anything is off.
The registry is the paper's numbers (report/paper/paper.md) as of the submission freeze; update it when they change."""
import os, re, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
DOCS = ["report/paper/paper.md", "README.md", "report/README.md", "web/index.html"]

# (name, regex with groups, expected values) — expected is a tuple, or a list of tuples when the same wording is used
# for two different measured quantities (each alternative names one of them); None in a slot = not checked
FACTS = [
    ("held-out luderick recall, queue accepted", r"(\d+\.\d)% of the boxed fish|recall (\d+\.\d)%, MaxN exact on \d+ of 24", ("98.9",)),
    ("held-out MaxN exact (of 24)", r"MaxN (?:is )?exact on (\d+) of 24", ("20",)),
    ("held-out recall, queue rejected", r"within ±1 at (\d+\.\d)% recall|within ±1 \(recall (\d+\.\d)%\)", ("95.6",)),
    ("development luderick queue (of 27)", r"\b(\d+) of 27\b(?! luderick tracks\))", ("9",)),
    ("'animal' prompt: clips with no box (of 39)", r"(\d+) of (?:the |our )?39 clips", ("29",)),
    ("'animal' overlap with counted non-fish (of 11)", r"(\d+) of the 11 non-fish", ("3",)),
    ("ledger total", r"ledger total of \$(\d+\.\d\d)|\$(\d+\.\d\d) over [\d,]+ calls|\$(\d+\.\d\d) / [\d,]+ calls", ("13.57",)),
    ("ledger calls", r"over ([\d,]+) calls|/ ([\d,]+) calls", ("2,067",)),
    ("cost of one 12 s discovery run (range)", r"12 s (?:discovery run|clip) costs? (?:about )?\$(\d\.\d\d)(?:–|-|\s+\(counting only\) to \$)(\d?\.?\d\d)", ("0.02", "0.40")),
    ("same-animal nested pairs", r"\b(\d+|six) of (\d+|eight) (?:nested )?pairs", [("6", "8"), ("six", "eight")]),
    ("held-out discovery: named / counted", r"named all (\d) non-fish animals marked beforehand, counted (\d)|names (\d) of 4 non-fish animals marked beforehand, counts (\d)", ("4", "3")),
    ("held-out discovery: named / counted (words)", r"names all (\w+) non-fish animals marked beforehand", ("four",)),
    ("held-out discovery cost (five clips)", r"\$(\d\.\d\d) for all five", ("1.06",)),
    ("discovery counted at the end (development 7/7, held-out 3/4, DH6-11 1/1)", r"counted at the end \| (\d) of (\d)", [("7", "7"), ("3", "4"), ("1", "1")]),
    ("s001 night nautiluses (final code, brightened)", r"(\d) (?:counted )?of at least (\d)", ("4", "4")),
    ("one_bit masks checked against the reference decoder", r"([\d,]+) masks", ("10,415",)),
    ("MBARI annotation effort", r"(\d+) hours of (?:survey )?video takes (\d+)[–-](\d+) hours", ("90", "180", "400")),
    ("box prompt with no word, s004 shrimp (pipeline)", r"(\d+) of 60 (?:frames )?in the pipeline|with no word, in (\d+) of 60 frames", ("55",)),
    ("Table 4b edge vs centre (of 25; 11 vs 4 is the track-survival comparison)", r"(\d+)/25 vs\.? (\d+)/25|(\d+) of 25 vs\.? (\d+) of 25", [("11", "0"), ("11", "4"), ("4", "0")]),   # 4 vs 0 of 25: the example-phrase test (7.1)
    ("luderick clips in total", r"Counting: (\d+) luderick clips", ("30",)),
]

STALE = [
    (r"\bIMAS\b", "IMAS footage was removed (licence not specified at the source)"),
    (r"never seen(?! the$)(?!.*project)", "only true for a clip not used in development; the planned live clip is from development video s002"),
    (r"nautilus_s002_24_36", "live clip cut from development video s002"),
    (r"two people(?!.*(marked beforehand|marked nothing|listed|saw 4 frames))", "DH1-DH5 reference lists were the author and an AI assistant (DH6-DH11: two people)"),
    (r"6 of 10 pairs", "v16: 6 of 8 nested pairs"),
    (r"can never find|alone can never", "the fixed 16-word list finds 5 of 7"),
    (r"pink seabream", "IMAS-era claim"),
    (r"2 of 124", "not recomputable; removed"),
    (r"\$8\.30|\$6\.62|\$3\.03\b|\$9\.78\b", "old spend totals (ledger is $13.57)"),
    (r"0\.05[–-]0?\.25", "old per-clip cost range"),
    (r"animal 0\b|0/13[–-]16", "IMAS-era 'animal' numbers"),
]


def heading_at(lines, i):
    for j in range(i, -1, -1):
        if lines[j].lstrip().startswith("#"):
            return lines[j].strip()[:70]
    return ""


def main():
    docs = [os.path.join(ROOT, d) for d in DOCS] + [os.path.abspath(p) for p in sys.argv[1:]]
    texts = {}
    for p in docs:
        if os.path.exists(p):
            texts[p] = open(p, encoding="utf-8").read().splitlines()
        else:
            print(f"(missing: {p})")
    bad = 0

    def short(p):
        return os.path.relpath(p, ROOT) if p.startswith(ROOT) else os.path.basename(p)

    print("== FACTS")
    for name, rx, want in FACTS:
        hits = []
        for p, lines in texts.items():
            for i, line in enumerate(lines):
                for m in re.finditer(rx, line):
                    vals = [g for g in m.groups() if g is not None]
                    alts = want if isinstance(want, list) else [want]
                    ok = any(all(w is None or (k < len(vals) and vals[k] == w) for k, w in enumerate(a)) for a in alts)
                    hits.append((ok, p, i, vals))
        n_bad = sum(not ok for ok, *_ in hits)
        bad += n_bad
        shown = " or ".join("/".join(w or "*" for w in a) for a in (want if isinstance(want, list) else [want]))
        print(f"- {name}: expected {shown}; {len(hits)} mention(s), {n_bad} mismatch")
        for ok, p, i, vals in hits:
            if not ok:
                print(f"    MISMATCH {short(p)}:{i + 1} value {'/'.join(vals)}  [{heading_at(texts[p], i)}]")
                print(f"      {texts[p][i].strip()[:160]}")
        if not hits:
            print("    (no mention found: check the regex or the wording)")

    print("== STALE")
    for rx, why in STALE:
        for p, lines in texts.items():
            for i, line in enumerate(lines):
                if re.search(rx, line):
                    bad += 1
                    print(f"- {short(p)}:{i + 1} /{rx}/ ({why})  [{heading_at(lines, i)}]")
                    print(f"      {line.strip()[:160]}")

    print("== REPOSITORY")
    paper = "\n".join(texts.get(os.path.join(ROOT, "report/paper/paper.md"), []))
    tags = subprocess.run(["git", "-C", ROOT, "tag"], capture_output=True, text=True).stdout.split()
    if re.search(r"is tagged", paper) and not tags:
        bad += 1
        print("- paper says the submitted version is tagged, but the repository has no tag")
    print(f"\n{bad} item(s) to look at")
    sys.exit(1 if bad else 0)


main()
