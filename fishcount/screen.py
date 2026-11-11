"""--skip-empty (opt-in, long videos): which stretches go to the models, decided from pixels alone ($0).

Stretches where the picture does not change from the last analysed frame are not sent; empty water stays empty and
a resting animal keeps its box (longvideo carries the last analysed frame's boxes over the stretch, marked carried).
The full analysis runs wherever something appears or moves.

- Every 5 fps frame is read at 480x270 (a fish that crosses the frame in a second is not skipped by sampling).
- The test is against a reference, not the previous frame (a still animal never differs from the previous frame):
  while skipping, the reference is the last frame of the last stretch sent, the very frame whose boxes are carried.
- Brightness and contrast (Lab L mean / std) are matched to the reference first: sun, cloud and lamp drift are not a
  change. A pixel differs when its blurred Lab distance passes max(FLOOR, the clip's own noise); a 16x9 cell is hot
  when its count of such pixels stands out from the other cells (median + 4 MAD), so turbidity or marine snow over the
  whole frame does not count; a change = a blob of >= MIN_BLOB pixels in a hot cell, or more than BIG of the frame
  differing (camera knocked, an animal filling the view).
- Swaying weed: pixels that differ frame to frame in most frames of the reference stretch get their threshold raised
  to that difference's mean + 3 sd (raised, not masked: an animal moving more than the weed is still seen).
- A sent stretch starts PAD_S before the change and runs until STABLE_S pass with no change (so the carried frame is
  a settled scene, not a fish half out of view); stretches closer than MERGE_S are joined, each lasts >= MIN_S, the
  first HEAD_S always go, and stretches over 600 s are split as longvideo.plan splits a video.
- Probes: a skipped stretch gets PROBE_S sent every PROBE_EVERY_S; longvideo compares the probe's boxes with the
  carried ones and re-sends the stretch once if they disagree.
"""
from fishcount import video   # also sets up the optional FISH_PYLIB path before cv2
import math
import cv2
import numpy as np

W, H = 480, 270
GX, GY = 16, 9                # 30x30-pixel cells
FLOOR = 12.0                  # Lab distance (8-bit Lab, after a 5x5 blur) below which a pixel never counts
K_MAD = 4
MIN_BLOB = 12                 # pixels at 480x270 (~14x14 at 1080p; motion.candidates' min_area at its own scale)
BIG = 0.25                    # this share of the frame differing = a change whatever the cells say
SWAY_SHARE = 0.5              # a pixel differing frame to frame in this share of a stretch's frames is sway
SWAY_MIN_FRAMES = 25

HEAD_S, PAD_S, STABLE_S, MERGE_S, MIN_S, MAX_S = 60, 10, 10, 60, 60, 600
PROBE_EVERY_S, PROBE_S = 600, 10


def small(bgr):
    if bgr.shape[1] != W or bgr.shape[0] != H:
        bgr = cv2.resize(bgr, (W, H), interpolation=cv2.INTER_AREA)
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB).astype(np.float32)


def _dist(ref, cur):
    """Blurred Lab distance after matching cur's L mean/std to ref's."""
    c = cur.copy()
    rm, rs, cm, cs = ref[..., 0].mean(), ref[..., 0].std(), c[..., 0].mean(), c[..., 0].std()
    c[..., 0] = (c[..., 0] - cm) * (rs / cs if cs > 1e-3 else 1.0) + rm
    return cv2.GaussianBlur(np.linalg.norm(c - ref, axis=2), (5, 5), 0)


def _cells(m):
    return m.reshape(GY, H // GY, GX, W // GX).sum(axis=(1, 3))


class State:
    """Change test, with the sway allowance learnt while the current reference stretch is sent."""

    def __init__(self):
        self.noise = np.zeros((H, W), np.float32)     # per-pixel threshold (swaying weed); 0 = FLOOR applies
        self.new_stretch()

    def new_stretch(self):
        self.cnt = np.zeros((H, W), np.int32)
        self.s1 = np.zeros((H, W), np.float32)
        self.s2 = np.zeros((H, W), np.float32)
        self.seen = 0

    def changed(self, ref, cur):
        m = _dist(ref, cur) > np.maximum(FLOOR, self.noise)
        if m.mean() > BIG:
            return True
        c = _cells(m)
        med = float(np.median(c))
        hot = (c > med + K_MAD * float(np.median(np.abs(c - med)))) & (c > 0)
        if not hot.any():
            return False
        n, lab, st, _ = cv2.connectedComponentsWithStats(m.astype(np.uint8), connectivity=8)
        big = np.flatnonzero(st[1:, cv2.CC_STAT_AREA] >= MIN_BLOB) + 1
        if not len(big):
            return False
        hotpix = np.repeat(np.repeat(hot, H // GY, axis=0), W // GX, axis=1)
        return bool(np.isin(lab[hotpix], big).any())

    def learn(self, prev, cur):
        """While sending: pixels that differ frame to frame in most frames of the stretch are sway; their threshold
        becomes mean + 3 sd of that frame-to-frame difference. Raised, not masked: something moving more than the
        weed still counts.
        ponytail: a fish milling on one spot for most of a stretch looks like sway there; probes catch what that
        hides; a per-pixel periodicity test if real footage shows misses there."""
        d = _dist(prev, cur)
        self.cnt += d > FLOOR
        self.s1 += d
        self.s2 += d * d
        self.seen += 1
        if self.seen >= SWAY_MIN_FRAMES:
            mean = self.s1 / self.seen
            sd = np.sqrt(np.maximum(self.s2 / self.seen - mean * mean, 0))
            self.noise = np.where(self.cnt >= SWAY_SHARE * self.seen, mean + 3 * sd, 0).astype(np.float32)


def windows(frames, fps, head_s=HEAD_S, pad_s=PAD_S, stable_s=STABLE_S, merge_s=MERGE_S, min_s=MIN_S, max_s=MAX_S,
            probe_every_s=PROBE_EVERY_S, probe_s=PROBE_S):
    """frames: iterable of BGR frames (any size). Returns the stretches to send, in order:
    [dict(start, n, kind, triggers)] with kind "head" (the first head_s), "change" or "probe"; triggers = the frames
    first seen to differ from the reference (one per change joined into the stretch; the detection delay is measured
    from them). head_s=0: judged from the first frame, which is then the reference (a report of
    how many changes the test sees, not a run)."""
    P, ST, MG, MN, PE, PN = (int(round(x * fps)) for x in (pad_s, stable_s, merge_s, min_s, probe_every_s, probe_s))
    head = int(round(head_s * fps))
    st = State()
    wins, cur, ref, anchor, prev, last_change = [], None, None, None, None, 0
    t = -1
    for t, bgr in enumerate(frames):
        f = small(bgr)
        if t == 0:
            if head:
                cur = dict(start=0, kind="head", triggers=[])
                anchor = f
            else:
                ref = f
        if cur is not None:                       # sending: extend until STABLE_S without change
            if prev is not None:
                st.learn(prev, f)
            if st.changed(anchor, f):
                anchor, last_change = f, t
            if t + 1 - cur["start"] >= MN and t + 1 >= head and t - last_change >= ST:
                cur["n"] = t + 1 - cur["start"]
                wins.append(cur)
                cur, ref = None, f
        elif st.changed(ref, f):                  # skipping: something differs from the carried frame
            end = wins[-1]["start"] + wins[-1]["n"] if wins else 0
            cur = dict(start=max(end, t - P), kind="change", triggers=[t])
            anchor, last_change = f, t
            st.new_stretch()
        prev = f
    n = t + 1 if t >= 0 else 0
    if cur is not None:                           # the video ended while sending
        end = wins[-1]["start"] + wins[-1]["n"] if wins else 0
        cur["start"] = min(cur["start"], max(end, n - MN))
        cur["n"] = n - cur["start"]
        wins.append(cur)
    joined = []
    for w in wins:                                # close stretches are one (the gap would cost a window's fixed cost)
        if joined and w["start"] - (joined[-1]["start"] + joined[-1]["n"]) < MG:
            joined[-1].update(n=w["start"] + w["n"] - joined[-1]["start"], triggers=joined[-1]["triggers"] + w["triggers"])
        else:
            joined.append(dict(w, triggers=list(w["triggers"])))
    out, last = [], 0
    for w in joined:
        out += _probes(last, w["start"], PE, PN)
        cap = max(1, int(max_s * fps))
        k = max(1, math.ceil(w["n"] / cap))
        size = math.ceil(w["n"] / k)
        for i, s in enumerate(range(0, w["n"], size)):
            out.append(dict(start=w["start"] + s, n=min(size, w["n"] - s), kind=w["kind"],
                            triggers=[x for x in w["triggers"] if w["start"] + s <= x < w["start"] + s + size]))
        last = w["start"] + w["n"]
    return out + _probes(last, n, PE, PN)


def _probes(a, b, every, n):
    return [dict(start=s, n=n, kind="probe", triggers=[]) for s in range(a + every, b - n + 1, every)] if every > 0 else []


def _read(clip):
    cap = cv2.VideoCapture(clip)
    try:
        while True:
            ok, f = cap.read()
            if not ok:
                return
            yield f
    finally:
        cap.release()


def scan(clip, fps, **kw):
    """windows() over a clip, streamed frame by frame (one 480x270 frame in memory at a time)."""
    return windows(_read(clip), fps, **kw)
