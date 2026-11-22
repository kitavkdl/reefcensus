"""A cache file cut short (process killed while writing: OOM, power) is a miss, not a crash; answers are written
through a temporary file (round 3, 11/21c). Against a local HTTP server: no network, no spend."""
import json, os, sys, tempfile, unittest
from unittest import mock
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fishcount import api
from test_call_retry import Server


class CacheFile(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.clip = os.path.join(self.d, "c.mp4")
        with open(self.clip, "wb") as fh:
            fh.write(os.urandom(10_000))
        api._uploads.clear()
        for p in (mock.patch.object(api, "CACHE", self.d), mock.patch.object(api, "LEDGER", os.path.join(self.d, "ledger.jsonl")),
                  mock.patch.object(api, "_key", lambda: "k"), mock.patch.object(api.time, "sleep", lambda s: None)):
            p.start()
        self.addCleanup(mock.patch.stopall)
        self.addCleanup(api._uploads.clear)
        self.cp = api._cache_path("sam", {"clip": api.file_sha(self.clip), "prompt": "fish"})

    def serve(self):
        s = Server()
        self.addCleanup(s.close)
        mock.patch.object(api, "BASE", s.base).start()
        return s

    def cut_short(self, path, obj):
        txt = json.dumps(obj)
        with open(path, "w") as fh:
            fh.write(txt[: len(txt) // 2])

    def test_whole_cache_file_is_read_as_before(self):
        with open(self.cp, "w") as fh:
            json.dump({"payload": {}, "output_text": "frame=3: x", "usage": None}, fh)
        self.assertTrue(api.sam_cached(self.clip, "fish"))
        self.assertEqual(api.sam_video(self.clip, "fish", 60, offline=True), "frame=3: x")

    def test_cut_short_sam_file_is_a_miss_offline(self):
        self.cut_short(self.cp, {"payload": {}, "output_text": "frame=3: x" * 50, "usage": None})
        self.assertFalse(api.sam_cached(self.clip, "fish"))
        with self.assertRaisesRegex(FileNotFoundError, "not cached"):
            api.sam_video(self.clip, "fish", 60, offline=True)

    def test_cut_short_sam_file_is_called_again_and_replaced(self):
        self.cut_short(self.cp, {"payload": {}, "output_text": "frame=3: x" * 50, "usage": None})
        s = self.serve()
        self.assertEqual(api.sam_video(self.clip, "fish", 60), "frame=0: none")
        self.assertEqual(s.responses, 1)
        self.assertEqual(json.load(open(self.cp))["output_text"], "frame=0: none")
        self.assertEqual([f for f in os.listdir(self.d) if f.endswith(".tmp")], [])     # no temporary file left
        self.assertEqual(api.sam_video(self.clip, "fish", 60, offline=True), "frame=0: none")

    def test_cut_short_spark_file_is_called_again(self):
        payload = {"model": api.SPARK_MODEL, "messages": [{"role": "user", "content": [{"type": "text", "text": "p"}]}],
                   "max_tokens": 10, "reasoning_effort": "low"}
        cp = api._cache_path("spark", payload)
        self.cut_short(cp, {"text": "an old answer " * 20, "usage": {}})
        with self.assertRaisesRegex(FileNotFoundError, "not cached"):
            api.spark("p", max_tokens=10, offline=True)
        s = self.serve()
        self.assertEqual(api.spark("p", max_tokens=10), "ok")
        self.assertEqual(s.chats, 1)
        self.assertEqual(json.load(open(cp))["text"], "ok")

    def test_not_a_dict_is_a_miss(self):
        with open(self.cp, "w") as fh:
            json.dump(["frame=3: x"], fh)
        self.assertFalse(api.sam_cached(self.clip, "fish"))


if __name__ == "__main__":
    unittest.main()
