"""Long videos: the next segment is cut and uploaded while this one runs (longvideo.run_long upload_ahead, on in the
CLI, --no-upload-ahead turns it off). A 600-s segment's clip is ~360 MB and its first SAM call waited for it to go up
(4.5-11 min on this server's 0.53-1.3 MB/s uplink) before anything else could happen. The upload only gives SAM a
file id for the same bytes, so answers, cache keys and the merge are unchanged. The fake server below sleeps on
/files; nothing leaves the machine. Run: python3 -m unittest discover -s tests -v"""
import json, os, shutil, sys, tempfile, threading, time, unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fishcount import _pylib  # noqa: F401
from fishcount import api, longvideo, pipeline, video
from test_longvideo import _fake_seg

UP, WORK = 0.5, 1.0     # seconds one fake upload takes / one fake segment works after its first SAM call


class _Resp:
    def __init__(self, code, fid):
        self.status_code, self.text, self._fid = code, "bad" if code >= 400 else "", fid

    def raise_for_status(self):
        if self.status_code >= 400:
            raise api.requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return {"id": self._fid}


class UploadAhead(unittest.TestCase):
    N = 3000    # 600 s at 5 fps -> 4 segments of 150 s at seg_s=150

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cuts, self.n_cut, self.waits, self.posts, self.refuse = {}, {}, {}, [], set()
        self.dark = False
        plock = threading.Lock()

        def ingest(src, dst, **k):
            open(dst, "w").close()

        def cut(clip, dst, start, n):
            self.cuts[dst] = (start, n)
            self.n_cut[dst] = self.n_cut.get(dst, 0) + 1
            with open(dst, "w") as f:
                f.write(f"{start}+{n}")         # each segment clip its own bytes

        def run_pipeline(sp, srid, **kw):
            # what the real one does before its first SAM call: copy the 5-fps cut to clip.mp4, upload it by content
            start, n = self.cuts[sp]
            d = os.path.join(self.tmp, srid)
            os.makedirs(d, exist_ok=True)
            clip = os.path.join(d, "up.mp4")       # stands for clip.mp4 (the merge would concat a real clip.mp4)
            shutil.copy(sp, clip)
            if kw.get("lowlight") == "on":          # a brightened clip is other bytes
                with open(clip, "a") as f:
                    f.write(" bright")
            if not kw.get("offline"):
                t = time.time()
                api._upload(clip, api._key(), sha=api.file_sha(clip))
                self.waits[start] = time.time() - t
            time.sleep(WORK)
            _fake_seg(d, n, [(10 * i, 10, 5, 5) for i in range(start // 750 + 1)])
            json.dump(dict(live_calls=2, cached_calls=1, billed_usd=0.25), open(os.path.join(d, "status.json"), "w"))

        def post(url, files=None, **k):
            assert url.endswith("/files"), url
            body = files["file"][1].read()
            with plock:
                self.posts.append(body)
                refuse = body in self.refuse
                if refuse:
                    self.refuse.discard(body)
            if refuse:
                return _Resp(400, None)
            time.sleep(UP)
            return _Resp(200, f"file-{len(self.posts)}")

        light = lambda p: dict(median_l=5, mean_l=20) if self.dark else dict(median_l=100, mean_l=100)
        for p in (mock.patch.object(pipeline, "RUNS", self.tmp), mock.patch.object(video, "ingest", ingest),
                  mock.patch.object(video, "info", lambda p: dict(n_frames=self.N, fps=5.0, width=100, height=100)),
                  mock.patch.object(video, "light_stats", light),
                  mock.patch.object(longvideo, "cut", cut), mock.patch.object(pipeline, "run_pipeline", run_pipeline),
                  mock.patch.object(api, "_key", lambda: "k"), mock.patch.object(api.requests, "post", post),
                  mock.patch.object(api, "LEDGER", os.path.join(self.tmp, "ledger.jsonl")),
                  mock.patch.dict(api._uploads, clear=True)):
            p.start()
        self.addCleanup(mock.patch.stopall)
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def run_long(self, rid="v", **kw):
        kw.setdefault("max_usd", 1.0)
        R = longvideo.run_long("v.mp4", rid, seg_s=150, **kw)
        return R, json.load(open(os.path.join(self.tmp, rid, "status.json")))

    def test_later_segments_find_their_clip_already_up(self):
        R, st = self.run_long("ahead", upload_ahead=True)
        w = [self.waits[s] for s in sorted(self.waits)]
        self.assertEqual(len(w), 4)
        self.assertGreater(w[0], UP * 0.8)                  # nothing before the first segment to hide it behind
        self.assertTrue(all(x < 0.2 for x in w[1:]), w)     # S2-S4: uploaded while the one before ran
        self.assertEqual(len(self.posts), 4)                # each clip went up once, never twice
        self.assertTrue(all(v == 1 for v in self.n_cut.values()), self.n_cut)     # and was cut once
        self.assertEqual(sum("uploaded ahead" in l for l in st["log"]), 3)
        api._uploads.clear()
        R0, _ = self.run_long("plain", upload_ahead=False)
        self.assertEqual(json.dumps(R, sort_keys=True).replace('"ahead', '"plain'), json.dumps(R0, sort_keys=True))
        self.assertTrue(all(self.waits[s] > UP * 0.8 for s in self.waits))   # off: every segment waits, as before

    def test_off_unless_asked(self):
        self.run_long("lib")       # the library default: the tests above and every caller but the CLI
        self.assertTrue(all(self.waits[s] > UP * 0.8 for s in self.waits))
        self.assertEqual(len(self.posts), 4)

    def test_offline_uploads_nothing(self):
        self.run_long("off", upload_ahead=True, offline=True)
        self.assertEqual(self.posts, [])

    def test_a_brightened_video_is_not_uploaded_ahead(self):
        self.dark = True        # lowlight auto -> on: the segment's clip.mp4 is not the cut's bytes
        self.run_long("dark", upload_ahead=True)
        self.assertEqual(len(self.posts), 4)
        self.assertTrue(all(b.endswith(b" bright") for b in self.posts))

    def test_kept_segments_are_not_uploaded_again(self):
        self.run_long("v", upload_ahead=True)
        self.posts.clear()
        api._uploads.clear()
        R, st = self.run_long("v", upload_ahead=True, resume=True)
        self.assertEqual(self.posts, [])
        self.assertEqual(sum("kept from the earlier run" in l for l in st["log"]), 4)

    def test_a_failed_upload_ahead_leaves_it_to_the_segment(self):
        self.refuse.add(b"750+750")         # S2's look-ahead upload is refused (HTTP 400: not sent again)
        R, st = self.run_long("refused", upload_ahead=True)
        self.assertEqual(st["stage"], "done")
        self.assertEqual(sum("upload ahead failed" in l for l in st["log"]), 1)
        self.assertEqual(len(self.posts), 5)                # S2 went up from its own first SAM call
        self.assertGreater(self.waits[750], UP * 0.8)
        self.assertEqual(len(self.waits), 4)

    def test_segment_workers_do_not_look_ahead(self):
        self.run_long("pair", upload_ahead=True, segment_workers=2)
        self.assertEqual(len(self.posts), 4)
        self.assertTrue(all(self.waits[s] > UP * 0.8 for s in self.waits))


if __name__ == "__main__":
    unittest.main()
