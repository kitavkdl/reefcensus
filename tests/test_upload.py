"""SAM clip uploads (api._upload, 11/21) against a local HTTP server, no network and no spend: one upload per clip
for many calls and threads, a retry after a dropped or 5xx upload, a re-upload when the server no longer has a reused
id, and a send timeout that grows with the file (a slow upload used to fail at 300 s whatever its progress)."""
import http.server, json, os, sys, tempfile, threading, time, unittest
from unittest import mock
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fishcount import api
import requests

_sleep = time.sleep     # the server's own pace: setUp silences time.sleep (retry back-off), which must not stop this


class Server:
    """POST /files: reads the body at `bps` bytes a second (0 = at once), answers {"id": "u<n>"}; the first `fail`
    uploads get HTTP 500. POST /responses: 404 for ids in `gone`, else a completed SAM stream."""

    def __init__(self, bps=0, fail=0, gone=()):
        self.bps, self.fail, self.gone, self.uploads, self.responses = bps, fail, set(gone), 0, []
        srv = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                n = int(self.headers.get("Content-Length", 0))
                if self.path.endswith("/files"):
                    left = n
                    while left:
                        k = min(left, 16384 if srv.bps else left)
                        left -= len(self.rfile.read(k))
                        if srv.bps:
                            _sleep(k / srv.bps)
                    srv.uploads += 1
                    if srv.uploads <= srv.fail:
                        return self._send(500, b"busy")
                    return self._send(200, json.dumps({"id": f"u{srv.uploads}"}).encode())
                body = json.loads(self.rfile.read(n))
                fid = body["input"][0]["content"][1]["file_id"]
                srv.responses.append(fid)
                if fid in srv.gone:
                    return self._send(404, b"no such file")
                ev = [{"type": "response.output_text.delta", "delta": "frame=0: none"},
                      {"type": "response.completed", "response": {"usage": {"video_frames_processed": 50}}}]
                self._send(200, "".join(f"data: {json.dumps(e)}\n\n" for e in ev).encode() + b"data: [DONE]\n\n")

            def _send(self, code, data):
                self.send_response(code)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class Upload(unittest.TestCase):
    def setUp(self):
        self.d = self.enterContext(tempfile.TemporaryDirectory())
        self.clip = os.path.join(self.d, "c.mp4")
        with open(self.clip, "wb") as fh:
            fh.write(os.urandom(200_000))
        api._uploads.clear()
        self.patches = [mock.patch.object(api, "CACHE", self.d), mock.patch.object(api, "LEDGER", os.path.join(self.d, "ledger.jsonl")),
                        mock.patch.object(api, "_key", lambda: "k"), mock.patch.object(api.time, "sleep", lambda s: None)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        api._uploads.clear()

    def serve(self, **kw):
        s = Server(**kw)
        self.addCleanup(s.close)
        mock.patch.object(api, "BASE", s.base).start()
        self.addCleanup(mock.patch.stopall)
        return s

    def sam(self, prompt):
        payload = {"clip": api.file_sha(self.clip), "prompt": prompt}
        return api._sam_live(self.clip, prompt, 50, payload, api._cache_path("sam", payload))

    def test_one_upload_for_several_words_and_threads(self):
        s = self.serve()
        ts = [threading.Thread(target=self.sam, args=(w,)) for w in ("fish", "crab", "shrimp", "eel")]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        self.sam("ray")
        self.assertEqual(s.uploads, 1)
        self.assertEqual(s.responses, ["u1"] * 5)

    def test_another_clip_is_uploaded(self):
        s = self.serve()
        self.sam("fish")
        with open(self.clip, "ab") as fh:
            fh.write(b"x")                    # other bytes: another file
        self.sam("fish ")
        self.assertEqual(s.uploads, 2)

    def test_retry_after_server_error(self):
        s = self.serve(fail=2)
        self.assertEqual(self.sam("fish"), "frame=0: none")
        self.assertEqual(s.uploads, 3)

    def test_gives_up_after_the_tries(self):
        s = self.serve(fail=5)
        with self.assertRaises(requests.HTTPError):
            self.sam("fish")
        self.assertEqual(s.uploads, api.UPLOAD_TRIES)

    def test_reused_id_the_server_lost_is_uploaded_again(self):
        s = self.serve(gone={"f1"})
        api._uploads[api.file_sha(self.clip)] = ("f1", time.time())
        self.assertEqual(self.sam("fish"), "frame=0: none")
        self.assertEqual(s.responses, ["f1", "u1"])
        self.assertEqual(s.uploads, 1)

    def test_old_id_is_not_reused(self):
        s = self.serve()
        api._uploads[api.file_sha(self.clip)] = ("old", time.time() - api.UPLOAD_REUSE_S - 1)
        self.sam("fish")
        self.assertEqual(s.responses, ["u1"])

    def test_send_timeout_grows_with_the_file(self):
        """The body goes out in one sendall under the connect timeout, and the timeout bounds the whole sendall: a
        24 MB body read at 6 MB/s (4 s; loopback buffers take ~10 MB at once) fails with a 1 s timeout though bytes
        flow the whole time, and goes through when the timeout is size / UPLOAD_MIN_BPS."""
        with open(self.clip, "wb") as fh:
            fh.write(os.urandom(24_000_000))
        s = self.serve(bps=6_000_000)
        with open(self.clip, "rb") as fh, self.assertRaises((requests.ConnectionError, requests.Timeout)):
            requests.post(f"{s.base}/files", files={"file": ("c.mp4", fh, "video/mp4")}, timeout=(1, 5))
        seen, post = [], requests.post
        def spy(*a, **k):
            seen.append(k["timeout"])
            return post(*a, **k)
        with mock.patch.object(api, "UPLOAD_MIN_BPS", 24_000_000 / 600), mock.patch.object(api.requests, "post", spy):
            fid, reused = api._upload(self.clip, "k")
        self.assertFalse(reused)
        self.assertTrue(fid.startswith("u"))
        self.assertEqual(seen, [(600.0, 600)])      # 24 MB at 40 kB/s allowed: 600 s, not the old fixed 300


if __name__ == "__main__":
    unittest.main()
