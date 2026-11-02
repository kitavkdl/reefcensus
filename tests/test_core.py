"""Unit tests for the parts every count depends on: SAM output parsing, merging passes, group boxes, stitching,
MaxN / first arrival, mask decoding (C vs reference), and an exact $0 replay of a saved demo run.
Run: python3 -m unittest discover -s tests -v   (no network, no API key, no spend)."""
import glob, json, os, sys, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from fishcount import _pylib  # noqa: F401
from fishcount import tracks


def det(i, box, conf=0.9, **kw):
    return dict(id=i, box=box, conf=conf, **kw)


class ParseBoxes(unittest.TestCase):
    TEXT = ("<0f>0<|box;x1=10;y1=20;x2=29;y2=39;c=0.91|>1<|box;x1=100;y1=100;x2=149;y2=129;c=0.5|>\n"
            "<1f>0<|box;x1=12;y1=20;x2=31;y2=39;c=0.88|>\n<2f>\n")

    def test_boxes_are_half_open_and_keep_ids_and_conf(self):
        d = tracks.parse_boxes(self.TEXT)
        self.assertEqual(sorted(d), [0, 1, 2])
        self.assertEqual(d[0][0], dict(id=0, box=(10.0, 20.0, 30.0, 40.0), conf=0.91))
        self.assertEqual(d[0][1]["id"], 1)
        self.assertEqual(d[2], [])
        self.assertEqual(tracks.max_per_frame(d), 2)

    def test_reverse_text_renumbers_frames(self):
        d = tracks.parse_boxes(tracks.reverse_text(self.TEXT, 3))
        self.assertEqual(sorted(d), [0, 1, 2])
        self.assertEqual(len(d[2]), 2)   # old frame 0 is now frame 2
        self.assertEqual(d[0], [])


class Geometry(unittest.TestCase):
    def test_iou(self):
        self.assertAlmostEqual(tracks.iou((0, 0, 10, 10), (0, 0, 10, 10)), 1.0)
        self.assertAlmostEqual(tracks.iou((0, 0, 10, 10), (5, 0, 15, 10)), 50 / 150)
        self.assertEqual(tracks.iou((0, 0, 10, 10), (20, 20, 30, 30)), 0.0)

    def test_overlap_catches_a_partial_box_inside_a_whole_one(self):
        whole, part = (0, 0, 100, 100), (0, 0, 30, 100)
        self.assertLess(tracks.iou(whole, part), 0.5)
        self.assertGreaterEqual(tracks.overlap(whole, part), 0.5)

    def test_from_tile_maps_back_and_flags_cut_boxes(self):
        out = tracks.from_tile({0: [det(0, (0, 40, 60, 80)), det(1, (100, 100, 140, 140))]}, (500, 300, 200, 200), 2)
        a, b = out[0]
        self.assertEqual(a["box"], (500, 320, 530, 340))
        self.assertTrue(a["cut"])            # touches the tile's left edge
        self.assertFalse(b["cut"])


class Merge(unittest.TestCase):
    def test_lower_priority_duplicate_is_dropped_and_linked(self):
        fish = {f: [det(0, (10 + f, 10, 50 + f, 40))] for f in range(5)}
        zoom = {f: [det(7, (11 + f, 10, 51 + f, 40))] for f in range(5)}
        frames, trk = tracks.merge([("fish", "fish", fish), ("zoom", "fish", zoom)])
        self.assertEqual(list(trk), ["fish:0"])
        self.assertTrue(all(len(ks) == 1 for ks in frames.values()))

    def test_separate_animals_are_both_kept(self):
        a = {0: [det(0, (0, 0, 10, 10))]}
        b = {0: [det(0, (50, 50, 60, 60))]}
        frames, trk = tracks.merge([("fish", "fish", a), ("shrimp", "shrimp", b)])
        self.assertEqual(sorted(trk), ["fish:0", "shrimp:0"])
        self.assertEqual(len(frames[0]), 2)

    def test_uncut_tile_box_inside_a_bigger_box_is_not_dropped(self):
        big = {0: [det(0, (0, 0, 200, 200))]}
        small = {0: [det(3, (20, 20, 60, 60), cut=False)]}
        _, trk = tracks.merge([("nautilus", "nautilus", big), ("tile", "nautilus", small)])
        self.assertEqual(len(trk), 2)

    def test_group_box_around_two_animals_is_removed(self):
        ks = [dict(track="a", label="shrimp", box=(0, 0, 100, 50)),
              dict(track="b", label="shrimp", box=(5, 5, 40, 45)),
              dict(track="c", label="shrimp", box=(55, 5, 95, 45))]
        self.assertEqual([k["track"] for k in tracks.drop_group_boxes(ks)], ["b", "c"])
        self.assertEqual(len(tracks.drop_group_boxes(ks[:2])), 2)   # holding one animal is not a group


class StitchAndMetrics(unittest.TestCase):
    def frames(self):
        fr = {}
        for f in range(0, 4):
            fr.setdefault(f, []).append(dict(track="s:1", label="fish", box=(10, 10, 30, 30)))
        for f in range(6, 9):
            fr.setdefault(f, []).append(dict(track="s:2", label="fish", box=(12, 10, 32, 30)))
        for f in range(2, 5):
            fr.setdefault(f, []).append(dict(track="s:3", label="fish", box=(200, 200, 230, 230)))
        trk = {t: dict(label="fish", source="s", frames=[f for f, ks in fr.items() if any(k["track"] == t for k in ks)])
               for t in ("s:1", "s:2", "s:3")}
        return fr, trk

    def test_stitch_joins_a_fragment_after_a_short_gap(self):
        fr, trk = self.frames()
        new = tracks.stitch(fr, trk, max_gap=10)
        self.assertEqual(sorted(new), ["s:1", "s:3"])
        self.assertEqual(sorted(new["s:1"]["frames"]), [0, 1, 2, 3, 6, 7, 8])

    def test_stitch_never_joins_tracks_that_coexist(self):
        fr, trk = self.frames()
        new = tracks.stitch(fr, trk, max_gap=10)
        self.assertIn("s:3", new)   # far away and overlapping in time with s:1

    def test_maxn_and_first_arrival(self):
        fr, trk = self.frames()
        m = tracks.metrics(fr, trk, 10, 5)["fish"]
        self.assertEqual(m["maxn"], 2)
        self.assertEqual(m["maxn_frame"], 2)
        self.assertEqual(m["maxn_time"], 0.4)
        self.assertEqual(m["first_frame"], 0)
        self.assertEqual(m["tracks"], 3)

    def test_human_review_relabels_and_removes(self):
        fr, trk = self.frames()
        m = tracks.metrics(fr, trk, 10, 5, labels={"s:3": "crab", "s:2": None})
        self.assertEqual(m["fish"]["maxn"], 1)
        self.assertEqual(m["fish"]["tracks"], 1)
        self.assertEqual(m["crab"]["maxn"], 1)
        self.assertEqual(m["crab"]["first_frame"], 2)


class MaskCodec(unittest.TestCase):
    def test_c_decoder_matches_reference_on_saved_sam_output(self):
        try:
            import numpy as np
            import meta_sam_parser  # noqa: F401
        except ImportError:
            self.skipTest("numpy / meta_sam_parser not installed")
        from fishcount import maskcodec
        if not maskcodec.fast():
            self.skipTest("no C compiler; the reference decoder is used anyway")
        from meta_sam_parser import decode_mask_to_raster, SegmentationMask
        checked = 0
        for path in sorted(glob.glob(os.path.join(ROOT, "cache", "sam_*.json")))[:20]:
            text = json.load(open(path)).get("output_text") or ""
            for f, box, h, w, payload in maskcodec.records(text):
                if not payload.startswith("!"):
                    continue
                ref = decode_mask_to_raster(SegmentationMask(encoding="one_bit", payload=payload, width=w, height=h))
                ref = np.frombuffer(ref, np.uint8).reshape(h, w).astype(bool)
                self.assertTrue((maskcodec.decode(payload, w, h) == ref).all(), (path, f))
                checked += 1
                if checked >= 40:
                    return
        if not checked:
            self.skipTest("no cached one_bit masks found")


class NameDisagreement(unittest.TestCase):
    """A second look (no names shown) that names a different animal group queues the track but keeps it counted."""

    def test_groups(self):
        from fishcount import pipeline as P
        self.assertIsNone(P.name_disagreement("small red crab", "crab"))
        self.assertIsNone(P.name_disagreement("hagfish", "eel"))
        self.assertIsNone(P.name_disagreement("large striped shrimp", "none"))
        self.assertEqual(P.name_disagreement("caridean shrimp", "fish"), "caridean shrimp vs fish")

    def test_queue(self):
        from fishcount import pipeline as P
        ok = {"confidence": 0.7, "species": "caridean shrimp", "confirm": {"is_animal": True, "confidence": 0.6}}
        self.assertFalse(P.needs_review(ok))
        self.assertTrue(P.needs_review(dict(ok, name_disagrees="caridean shrimp vs fish")))


class GroupMetrics(unittest.TestCase):
    def test_same_frame_sum(self):
        from fishcount import pipeline as P
        m = {"caridean shrimp": dict(curve=[1, 3, 2], first_frame=0, tracks=3),
             "shrimp (unidentified)": dict(curve=[0, 0, 2], first_frame=2, tracks=2),
             "hagfish": dict(curve=[1, 1, 0], first_frame=0, tracks=1)}
        g = P.group_metrics(m, 5.0)
        self.assertEqual(list(g), ["crustacean"])          # a one-label group is that label's own row
        self.assertEqual((g["crustacean"]["maxn"], g["crustacean"]["maxn_frame"]), (4, 2))


class Replay(unittest.TestCase):
    """The saved demo run must replay from cache/ with no API call and give the same counts."""
    CLIP = os.path.join(ROOT, "spikes", "L1", "clips", "nautilus_s004_0_12.mp4")
    SAVED = os.path.join(ROOT, "demo", "runs", "L1_s004_v16", "result.json")

    def test_s004_offline_replay_matches_saved_run(self):
        if not os.path.exists(self.CLIP):
            self.skipTest("clip not present (videos are not in git; see README Data)")
        from fishcount import pipeline
        r = pipeline.run_pipeline(self.CLIP, "test_replay_s004", True, False, True, True, ["fish"], 0.0, True)
        saved = json.load(open(self.SAVED))["metrics"]
        got = {k: (v["maxn"], v["maxn_frame"], v["first_frame"]) for k, v in r["metrics"].items()}
        want = {k: (v["maxn"], v["maxn_frame"], v["first_frame"]) for k, v in saved.items()}
        self.assertEqual(got, want)


if __name__ == "__main__":
    unittest.main()
