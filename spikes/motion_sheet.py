"""Contact sheet of motion candidates (spikes/motion.py json): one 3x crop per candidate at its middle frame,
numbered, for a person or Spark to say which are animals.   python3 spikes/motion_sheet.py <clip> <motion.json> <out.jpg> [k]"""
import json, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.expanduser("~/meta-smoke/pylib"))
import cv2, numpy as np
from fishcount import video

def sheet(clip, mj, out, k=12, side=240):
    d = json.load(open(mj)); s = d["scale"]
    cands = [c for c in d["candidates"] if c["inside"] < 0.5 and c["area"] >= 20]
    cands.sort(key=lambda c: -(c["n"] * min(c["area"], 400)))
    cands = cands[:k]
    mids = sorted({(c["first"] + c["last"]) // 2 for c in cands})
    fr = video.frames(clip, mids)
    tiles = []
    for i, c in enumerate(cands):
        img = fr[(c["first"] + c["last"]) // 2]
        cx, cy = c["c"][0] / s, c["c"][1] / s
        half = max(40, int(np.sqrt(c["area"]) / s * 2.5))
        x0, y0 = int(max(0, cx - half)), int(max(0, cy - half))
        crop = img[y0:int(cy + half), x0:int(cx + half)]
        t = cv2.resize(crop, (side, side), interpolation=cv2.INTER_CUBIC)
        cv2.putText(t, str(i + 1), (8, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (29, 85, 242), 2, cv2.LINE_AA)
        tiles.append(t)
        c["sheet_no"] = i + 1; c["crop"] = [x0, y0, int(cx + half), int(cy + half)]
    while len(tiles) % 4:
        tiles.append(np.zeros_like(tiles[0]))
    rows = [np.hstack(tiles[i:i + 4]) for i in range(0, len(tiles), 4)]
    cv2.imwrite(out, np.vstack(rows), [cv2.IMWRITE_JPEG_QUALITY, 80])
    json.dump(cands, open(os.path.splitext(out)[0] + ".json", "w"), indent=1)
    for c in cands:
        print(c["sheet_no"], c["first"], c["last"], c["n"], [round(v / s) for v in c["c"]], c["area"], c["crop"])

if __name__ == "__main__":
    sheet(sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4]) if len(sys.argv) > 4 else 12)
