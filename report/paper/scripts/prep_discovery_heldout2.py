"""Second held-out discovery set DH6-DH11 (protocol: report/paper/discovery_heldout2_protocol.md; selection log:
report/paper/data/discovery_heldout2/candidates.md). Same ingest and sheets as prep_discovery_heldout.py (that module's
main() is reused with these paths and clips): the 12 s centred on the file midpoint (whole file if shorter), 5 fps,
width <= 1920, no audio, a 4-frame sheet per clip (frames 0, 20, 40, 59). Also writes one combined label-free sheet of
all clips for a second marker.
  python3 report/paper/scripts/prep_discovery_heldout2.py
Raw files are expected in spikes/DHB/raw/ (download URLs and sha256 in report/paper/data/discovery_heldout2/clips.json)."""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import prep_discovery_heldout as P   # noqa: E402

ROOT = P.ROOT
P.RAW = os.path.join(ROOT, "spikes", "DHB", "raw")
P.OUT = os.path.join(ROOT, "spikes", "DHB", "clips")
P.DATA = os.path.join(ROOT, "report", "paper", "data", "discovery_heldout2")
D = "PLOS ONE, doi:10.1371/journal.pone."
P.CLIPS = [
    ("DH6", "f/f8/Reef-Fidelity-and-Migration-of-Tiger-Sharks-Galeocerdo-cuvier-across-the-Coral-Sea-pone.0083249.s002.ogv",
     f"Werry et al. 2014, {D}0083249 (9(1)), Video S2 (Lord Howe Island BRUV)", "CC BY 4.0"),
    ("DH7", "9/99/Methane-Carbon-Flow-into-the-Benthic-Food-Web-at-Cold-Seeps---A-Case-Study-from-the-Costa-Rica-pone.0074894.s001.ogv",
     f"Niemann et al. 2013, {D}0074894 (8(10)), Video S1 (stationary seafloor time-lapse, 2 images/h)", "CC BY 2.5"),
    ("DH8", "2/2f/Oceanic-Sharks-Clean-at-Coastal-Seamount-pone.0014755.s004.ogv",
     f"Oliver et al. 2011, {D}0014755 (6(3)), Video S4 (remote video camera, Station A)", "CC BY 2.5"),
    ("DH9", "4/49/Bioturbation-in-a-Declining-Oxygen-Environment-in-situ-Observations-from-Wormcam-pone.0034539.s004.ogv",
     f"Sturdivant, Diaz & Cutter 2012, {D}0034539 (7(4)), Video S4 (Wormcam, hourly images, Aug-Sep 2009)", "CC BY 2.5"),
    ("DH10", "a/a7/Bioturbation-in-a-Declining-Oxygen-Environment-in-situ-Observations-from-Wormcam-pone.0034539.s001.ogv",
     f"Sturdivant, Diaz & Cutter 2012, {D}0034539 (7(4)), Video S1 (Wormcam, hourly images, May-Jun 2009)", "CC BY 2.5"),
    ("DH11", "2/2a/Rhythms-and-Community-Dynamics-of-a-Hydrothermal-Tubeworm-Assemblage-at-Main-Endeavour-Field---A-pone.0096924.s004.ogv",
     f"Cuvelier et al. 2014, {D}0096924 (9(5)), Video S4 (Grotto vent, 2186 m)", "CC BY 4.0"),
]
AUTHORS = {"DH6": "Werry J, Planes S, Berumen M, Lee K, Braun C, Clua E",
           "DH7": "Niemann H, Linke P, Knittel K, MacPherson E, Boetius A, Bruckmann W, et al. (13 authors)",
           "DH8": "Oliver S, Hussey N, Turner J, Beckett A",
           "DH9": "Sturdivant S, Diaz R, Cutter G", "DH10": "Sturdivant S, Diaz R, Cutter G",
           "DH11": "Cuvelier D, Legendre P, Laes A, Sarradin P, Sarrazin J"}


def combined_sheet(h=300):
    """One row per clip (frames 0, 20, 40, 59), every frame resized to the same height, labelled after resizing."""
    from fishcount import video
    import cv2, numpy as np
    rows = []
    for cid, *_ in P.CLIPS:
        dst = os.path.join(P.OUT, f"{cid}.mp4")
        n = video.info(dst)["n_frames"]
        idx = [i for i in (0, 20, 40, 59) if i < n]
        cells = []
        for i, im in sorted(video.frames(dst, idx).items()):
            im = cv2.resize(im, (int(im.shape[1] * h / im.shape[0]), h), interpolation=cv2.INTER_AREA)
            cells.append(np.pad(video.label(im, f"{cid} frame {i}"), ((0, 0), (0, 8), (0, 0)), constant_values=255))
        rows.append(np.pad(np.hstack(cells), ((0, 8), (0, 0), (0, 0)), constant_values=255))
    w = max(r.shape[1] for r in rows)
    sheet = np.vstack([np.pad(r, ((0, 0), (0, w - r.shape[1]), (0, 0)), constant_values=255) for r in rows])
    open(os.path.join(P.DATA, "sheet_DH6-11.jpg"), "wb").write(video.jpg(sheet, max_w=2400, q=88))


if __name__ == "__main__":
    P.main()
    cp = os.path.join(P.DATA, "clips.json")
    j = json.load(open(cp))
    j["note"] = "second held-out discovery set (DH6-DH11); window = 12 s centred on the file midpoint"
    for c in j["clips"]:
        c["authors"] = AUTHORS[c["id"]]
    json.dump(j, open(cp, "w"), indent=1)
    combined_sheet()
