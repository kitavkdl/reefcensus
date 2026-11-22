"""SAM and Spark requests sent again after a failed connection or a 429/5xx (api._post), and a SAM stream that breaks
after the call started logged in the ledger, against a local HTTP server: no network, no spend."""
import http.server, json, os, socket, sys, tempfile, threading, unittest
from unittest import mock
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fishcount import api
import requests


class Server:
    """POST /chat/completions: the first `fail` calls get `code`, then a Spark reply. POST /files: {"id": "u1"}.
    POST /responses: a SAM stream; with `cut` the connection closes half-way through the promised body."""

    def __init__(self, fail=0, code=503, cut=False):
        self.fail, self.code, self.cut, self.chats, self.responses = fail, code, cut, 0, 0
        srv = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                self.rfile.read(int(self.headers.get("Content-Length", 0)))
                if self.path.endswith("/files"):
                    return self._send(200, b'{"id": "u1"}')
                if self.path.endswith("/chat/completions"):
                    srv.chats += 1
                    if srv.chats <= srv.fail:
                        return self._send(srv.code, b"busy")
                    return self._send(200, json.dumps({"choices": [{"message": {"content": "ok"}}],
                                                       "usage": {"prompt_tokens": 10, "completion_tokens": 2}}).encode())
                srv.responses += 1
                ev = [{"type": "response.output_text.delta", "delta": "frame=0: none"},
                      {"type": "response.completed", "response": {"usage": {"video_frames_processed": 50}}}]
                data = "".join(f"data: {json.dumps(e)}\n\n" for e in ev).encode() + b"data: [DONE]\n\n"
                if srv.cut:
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                    self.send_header("Content-Length", str(len(data) * 4))
                    self.end_headers()
                    self.wfile.write(data[:60])
                    self.wfile.flush()
                    self.connection.shutdown(socket.SHUT_RDWR)
                    return
                self._send(200, data)

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


class Retry(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.ledger = os.path.join(self.d, "ledger.jsonl")
        self.clip = os.path.join(self.d, "c.mp4")
        with open(self.clip, "wb") as fh:
            fh.write(os.urandom(10_000))
        api._uploads.clear()
        self.sleeps = []
        for p in (mock.patch.object(api, "CACHE", self.d), mock.patch.object(api, "LEDGER", self.ledger),
                  mock.patch.object(api, "_key", lambda: "k"), mock.patch.object(api.time, "sleep", self.sleeps.append)):
            p.start()
        self.addCleanup(mock.patch.stopall)
        self.addCleanup(api._uploads.clear)

    def serve(self, **kw):
        s = Server(**kw)
        self.addCleanup(s.close)
        mock.patch.object(api, "BASE", s.base).start()
        return s

    def rows(self):
        return [json.loads(x) for x in open(self.ledger)] if os.path.exists(self.ledger) else []

    def spark(self, prompt="p"):
        return api.spark(prompt, max_tokens=10)

    def test_spark_retries_a_busy_server(self):
        s = self.serve(fail=2, code=503)
        self.assertEqual(self.spark(), "ok")
        self.assertEqual(s.chats, 3)
        self.assertEqual(self.sleeps, [5, 15])
        self.assertEqual(len(self.rows()), 1)          # only the answered call is logged

    def test_spark_retries_429(self):
        s = self.serve(fail=1, code=429)
        self.assertEqual(self.spark(), "ok")
        self.assertEqual(s.chats, 2)

    def test_spark_gives_up_after_the_tries(self):
        s = self.serve(fail=9, code=502)
        with self.assertRaisesRegex(RuntimeError, "Spark HTTP 502"):
            self.spark()
        self.assertEqual(s.chats, api.CALL_TRIES)
        self.assertEqual(self.rows(), [])

    def test_spark_400_is_not_retried(self):
        s = self.serve(fail=9, code=400)
        with self.assertRaisesRegex(RuntimeError, "Spark HTTP 400"):
            self.spark()
        self.assertEqual(s.chats, 1)

    def refused_addr(self):
        port = socket.socket()
        port.bind(("127.0.0.1", 0))
        addr = port.getsockname()[1]
        port.close()                                    # nothing listens there: every connect is refused
        return f"http://127.0.0.1:{addr}"

    def test_connection_refused_is_retried_for_the_wait_then_raised(self):
        # round 3: a request that never connected (refused, DNS, connect timeout) never reached the server, so it is
        # sent again for about CONNECT_WAIT_S of pauses (a router or uplink drop overnight), not given up after 20 s
        seen, post = [], requests.post
        def spy(*a, **k):
            seen.append(a[0])
            return post(*a, **k)
        with mock.patch.object(api, "BASE", self.refused_addr()), mock.patch.object(api.requests, "post", spy):
            with self.assertRaises(requests.ConnectionError):
                self.spark()
        self.assertEqual(self.sleeps[:4], [5, 15, 45, 60])
        self.assertTrue(all(s <= 60 for s in self.sleeps))
        self.assertGreaterEqual(sum(self.sleeps), api.CONNECT_WAIT_S)
        self.assertLess(sum(self.sleeps) - self.sleeps[-1], api.CONNECT_WAIT_S)    # stops once the wait is used
        self.assertEqual(len(seen), len(self.sleeps) + 1)

    def test_long_outage_then_up(self):
        s = self.serve()
        up, calls, post = s.base, [], requests.post
        down = self.refused_addr()
        def flaky(url, *a, **k):
            calls.append(1)
            return post(url.replace(up, down) if len(calls) <= 8 else url, *a, **k)    # 8 refusals: ~6 min down
        with mock.patch.object(api.requests, "post", flaky):
            self.assertEqual(self.spark(), "ok")
        self.assertEqual(s.chats, 1)
        self.assertEqual(len(self.sleeps), 8)
        self.assertEqual(len(self.rows()), 1)

    def test_connect_timeout_counts_as_never_connected(self):
        s = self.serve()
        calls, post = [], requests.post
        def flaky(*a, **k):
            calls.append(1)
            if len(calls) <= 4:
                raise requests.ConnectTimeout("connect timed out")
            return post(*a, **k)
        with mock.patch.object(api.requests, "post", flaky):
            self.assertEqual(self.spark(), "ok")
        self.assertEqual(self.sleeps, [5, 15, 45, 60])

    def test_drop_after_connecting_keeps_three_tries(self):
        # the connection broke after the request may have reached the server: the old CALL_TRIES policy, unchanged
        import urllib3
        calls = []
        def dropped(*a, **k):
            calls.append(1)
            raise requests.ConnectionError(urllib3.exceptions.ProtocolError("Connection aborted.", ConnectionResetError()))
        with mock.patch.object(api.requests, "post", dropped):
            with self.assertRaises(requests.ConnectionError):
                self.spark()
        self.assertEqual(len(calls), api.CALL_TRIES)
        self.assertEqual(self.sleeps, [5, 15])

    def test_read_timeout_is_not_sent_again(self):
        calls = []
        def slow(*a, **k):
            calls.append(1)
            raise requests.ReadTimeout("read timed out")
        with mock.patch.object(api.requests, "post", slow):
            with self.assertRaises(requests.ReadTimeout):
                self.spark()
        self.assertEqual(calls, [1])
        self.assertEqual(self.sleeps, [])

    def test_upload_waits_out_an_outage(self):
        s = self.serve()
        up, calls, post = s.base, [], requests.post
        down = self.refused_addr()
        def flaky(url, *a, **k):
            if url.endswith("/files"):
                calls.append(1)
                if len(calls) <= 6:
                    url = url.replace(up, down)
            return post(url, *a, **k)
        payload = {"clip": api.file_sha(self.clip), "prompt": "fish"}
        with mock.patch.object(api.requests, "post", flaky):
            self.assertEqual(api._sam_live(self.clip, "fish", 120, payload, api._cache_path("sam", payload)), "frame=0: none")
        self.assertEqual(len(calls), 7)
        self.assertEqual(s.responses, 1)

    def test_connection_refused_then_up(self):
        s = self.serve()
        calls, post = [], requests.post
        def flaky(*a, **k):
            calls.append(1)
            if len(calls) == 1:
                raise requests.ConnectionError("Failed to resolve")    # the cr9 DNS failure
            return post(*a, **k)
        with mock.patch.object(api.requests, "post", flaky):
            self.assertEqual(self.spark(), "ok")
        self.assertEqual(s.chats, 1)

    def test_sam_broken_stream_is_logged_and_raised(self):
        s = self.serve(cut=True)
        payload = {"clip": api.file_sha(self.clip), "prompt": "fish"}
        cp = api._cache_path("sam", payload)
        with self.assertRaises((requests.RequestException, OSError)):
            api._sam_live(self.clip, "fish", 120, payload, cp)
        self.assertEqual(s.responses, 1)                # a started stream is never sent again
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["kind"], "sam")
        self.assertAlmostEqual(rows[0]["usd"], max(api.SAM_MIN_FRAMES, 120) * api.SAM_PER_FRAME)
        self.assertIn("stream broke", rows[0]["note"])
        self.assertFalse(os.path.exists(cp))            # nothing cached

    def test_sam_whole_stream_unchanged(self):
        s = self.serve()
        payload = {"clip": api.file_sha(self.clip), "prompt": "fish"}
        cp = api._cache_path("sam", payload)
        self.assertEqual(api._sam_live(self.clip, "fish", 120, payload, cp), "frame=0: none")
        self.assertEqual(s.responses, 1)
        self.assertEqual([r["usd"] for r in self.rows()], [50 * api.SAM_PER_FRAME])
        self.assertTrue(os.path.exists(cp))


if __name__ == "__main__":
    unittest.main()
