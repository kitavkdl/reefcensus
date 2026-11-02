"""Second held-out discovery set (DH6-DH11): what each pipeline run counted, queued and cost, plus the label-free
evidence sheet for metric 3. Same code as score_discovery_heldout.py (its functions are reused with this set's
paths); no API calls.
    python3 report/paper/scripts/score_discovery_heldout2.py
Writes report/paper/data/discovery_heldout2/runs_summary.json and crops_sheet.jpg (crop numbers map to rows in the
JSON, which the judge does not see)."""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import score_discovery_heldout as S   # noqa: E402
import cv2, numpy as np   # noqa: E402

S.OUT = os.path.join(S.ROOT, "report", "paper", "data", "discovery_heldout2")
IDS = range(6, 12)

if __name__ == "__main__":
    res = [S.summarise(n) for n in IDS if os.path.exists(os.path.join(S.run_dir(n), "result.json"))]
    tiles, k = [], 0
    for s in res:
        n = int(s["clip"][2:])
        print(f"{s['clip']}: named {s['named']}  queued tracks {s['queued_tracks']}  ${s['cost_usd']}")
        for row in s["rows"]:
            tag = ""
            # metric 3 is defined on counted (non-queued) rows; rows that are in the MaxN but also queued get a crop
            # too and are reported separately (they are shown as counts on the review screen and CSV)
            if (row["counted"] or row.get("in_maxn")) and row["non_fish"]:
                k += 1
                row["crop"] = k
                if os.path.exists(os.path.join(S.ROOT, "runs", f"DH{n}_eval", "clip.mp4")):
                    t = S.crop(n, row)
                    cv2.putText(t, f"#{k}", (10, 38), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (255, 255, 255), 2, cv2.LINE_AA)
                    tiles.append(t)
                tag = f"  crop #{k}"
            state = "COUNTED" if row["counted"] else ("in MaxN, queued" if row.get("in_maxn") else "queued ")
            print(f"   {state} {row['label']!r} maxn {row['maxn']} "
                  f"conf {row['confidence']} {'non-fish' if row['non_fish'] else 'fish'}{tag}")
    json.dump(res, open(os.path.join(S.OUT, "runs_summary.json"), "w"), indent=1)
    if len(tiles) == k and tiles:
        while len(tiles) % 4:
            tiles.append(np.zeros_like(tiles[0]))
        grid = np.vstack([np.hstack(tiles[i:i + 4]) for i in range(0, len(tiles), 4)])
        cv2.imwrite(os.path.join(S.OUT, "crops_sheet.jpg"), grid, [cv2.IMWRITE_JPEG_QUALITY, 90])
    print("total cost $%.4f" % sum(s["cost_usd"] for s in res))
