"""Which queued tracks can still change a count. The human queue holds every track the auditor was unsure of; on a long
video that is most tracks (the 53-min NOAA run queues 1,017 of 1,373). A person does not need to look at all of them to
settle the survey numbers. For each label, MaxN after review lies between the count of the frame with the most sure
boxes (counted and not queued, or already reviewed) and the count with every open queued track in it accepted. A queued
track can move MaxN only if it appears in a frame whose upper count is above the current lower end; it can move first
arrival only if it starts before the label's first sure box. Every other queued track, whatever a person says, leaves
MaxN and first arrival as they are. The review screen asks the deciding tracks first, from the frame with the highest
possible count, and recomputes after each answer, so accepting a track raises the lower end and drops tracks that can
no longer matter. Group rows (all fish, all crabs) are not used for this ordering; they follow from the labels.

decisive(res, review) -> {track: rank} (1 = ask first) for the unreviewed queued tracks that can change a count."""
from collections import defaultdict

from fishcount import pipeline


def accept_label(res, t):
    """The label a queued track is counted under if a person says yes: its current label if counted, else the name the
    review screen's "Yes" button gives, as pipeline.auto_labels names it (Spark's species if any, else "<category>
    (unidentified)", so a restored track joins the row of the same kind)."""
    if res.get("auto_labels", {}).get(t):
        return res["auto_labels"][t]
    v = res.get("verdicts", {}).get(t) or {}
    sp = v.get("species")
    return sp.lower() if sp and sp != "unknown" else f"{res['tracks'][t]['label']} (unidentified)"


def decisive(res, review=None):
    review = review or {}
    labels = dict(res.get("auto_labels", {})); labels.update(review)
    open_q = {t for t, v in res.get("verdicts", {}).items() if pipeline.needs_review(v) and t not in review}
    sure = defaultdict(lambda: defaultdict(int))        # label -> frame -> boxes that stay whatever the queue says
    maybe = defaultdict(lambda: defaultdict(set))       # label -> frame -> open queued tracks that would add a box
    first_sure, first_track = {}, {}
    for f, ks in res.get("frames", {}).items():
        f = int(f)
        for k in ks:
            t = k["track"]
            if t in open_q:
                L = accept_label(res, t)
                maybe[L][f].add(t)
                first_track[t] = min(first_track.get(t, f), f)
            elif labels.get(t):
                L = labels[t]
                sure[L][f] += 1
                first_sure[L] = min(first_sure.get(L, f), f)
    score = {}
    for L, fr in maybe.items():
        frames = set(fr) | set(sure[L])
        low = max((sure[L][f] for f in frames), default=0)
        for f, ts in fr.items():
            up = sure[L][f] + len(ts)
            if up > low:
                for t in ts:
                    score[t] = max(score.get(t, (0, 0)), (up, -f))
        for ts in fr.values():
            for t in ts:
                if t not in score and first_track[t] < first_sure.get(L, float("inf")):
                    score[t] = (0, -first_track[t])     # first arrival only: after every MaxN question, earliest first
    ranked = sorted(score, key=lambda t: (score[t][0], score[t][1]), reverse=True)
    return {t: i + 1 for i, t in enumerate(ranked)}
