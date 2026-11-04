"""FISH_BUDGET is a hard cap even when calls run in parallel (GPT review 11/4: check, call, then log let parallel
calls all pass the same check). No network: requests.post is replaced by a slow fake."""
import json, os, sys, tempfile, threading, time, unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from fishcount import api


class FakeResp:
    status_code = 200

    def json(self):
        time.sleep(0.2)          # every thread is past the check before any call is logged
        return {"usage": {"prompt_tokens": 8000, "completion_tokens": 0},       # $0.01 per call
                "choices": [{"message": {"content": "ok"}}]}


class BudgetUnderParallelCalls(unittest.TestCase):
    def test_parallel_spark_calls_never_pass_the_cap(self):
        d = tempfile.mkdtemp()
        with mock.patch.object(api, "LEDGER", os.path.join(d, "ledger.jsonl")), \
                mock.patch.object(api, "CACHE", os.path.join(d, "cache")), \
                mock.patch.object(api.requests, "post", lambda *a, **k: FakeResp()), \
                mock.patch.object(api, "_key", lambda: "x"), \
                mock.patch.dict(os.environ, {"FISH_BUDGET": "0.05"}):
            done, refused = [], []

            def one(i):
                try:
                    api.spark(f"call {i}")
                    done.append(i)
                except api.BudgetExceeded:
                    refused.append(i)
            ts = [threading.Thread(target=one, args=(i,)) for i in range(12)]
            [t.start() for t in ts]
            [t.join() for t in ts]
            self.assertLessEqual(api.spent(), 0.05 + 1e-9)
            self.assertEqual(len(done), 2)        # reserve $0.02 each: 2 fit under $0.05, a third would not
            self.assertEqual(len(refused), 10)
            self.assertEqual(open(api.LEDGER + ".resv").read(), "")   # nothing left held

    def test_a_dead_process_does_not_hold_budget(self):
        d = tempfile.mkdtemp()
        led = os.path.join(d, "ledger.jsonl")
        with open(led + ".resv", "w") as f:
            f.write(json.dumps(dict(id="x", pid=2 ** 22 + 12345, usd=5.0)) + "\n")
        with mock.patch.object(api, "LEDGER", led), mock.patch.dict(os.environ, {"FISH_BUDGET": "1"}):
            with api.reserve(0.5):
                pass


if __name__ == "__main__":
    unittest.main()
