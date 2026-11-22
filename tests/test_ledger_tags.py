"""Ledger lines name the run and the stage that paid (round 3, cost-auditor / survey / data-manager views): a shared
ledger.jsonl could not say which video or which stage spent a dollar. The four old keys (t, kind, usd, note) keep
their order and meaning, so spend totals and the paper's ledger_summary read old and new lines the same. No network."""
import json, os, sys, tempfile, threading, unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from fishcount import api, pipeline


class _Run:
    """Stand-in run: what _counted touches."""
    def __init__(self, rid):
        self.id, self._lock = rid, threading.Lock()
        self.status = dict(live_calls=0, cached_calls=0, billed_usd=0.0)


def _paid(usd, note="x"):
    api._log("sam", usd, note)
    return "ok"


def scout_stage(run, usd):
    return pipeline._counted(run, _paid, usd)


def refill_stage(run, usd):
    return pipeline._counted(run, _paid, usd)


class LedgerTags(unittest.TestCase):
    def setUp(self):
        self.d = self.enterContext(tempfile.TemporaryDirectory())
        self.led = os.path.join(self.d, "ledger.jsonl")
        self.p = [mock.patch.object(api, "LEDGER", self.led), mock.patch.object(api, "CACHE", self.d)]
        [p.start() for p in self.p]

    def tearDown(self):
        [p.stop() for p in self.p]

    def rows(self):
        with open(self.led) as fh:
            return [json.loads(l) for l in fh]

    def test_untagged_line_is_the_old_format(self):
        api._log("spark", 0.01, "n")
        self.assertEqual(list(self.rows()[0]), ["t", "kind", "usd", "note"])

    def test_counted_call_names_run_and_calling_stage(self):
        scout_stage(_Run("0101-000000"), 0.02)
        r = self.rows()[0]
        self.assertEqual(list(r)[:4], ["t", "kind", "usd", "note"])
        self.assertEqual((r["kind"], r["usd"], r["note"]), ("sam", 0.02, "x"))
        self.assertEqual((r["run"], r["stage"]), ("0101-000000", "scout_stage"))

    def test_tag_does_not_leak_past_the_call(self):
        scout_stage(_Run("a"), 0.01)
        api._log("spark", 0.01, "after")
        self.assertNotIn("run", self.rows()[1])

    def test_a_raising_call_still_clears_the_tag(self):
        def boom():
            api._log("spark", 0.01, "paid then broke")
            raise ValueError("bad reply")
        with self.assertRaises(ValueError):
            pipeline._counted(_Run("b"), boom)
        api._log("spark", 0.01, "after")
        rows = self.rows()
        self.assertEqual(rows[0]["run"], "b")
        self.assertNotIn("run", rows[1])

    def test_parallel_runs_each_sum_to_their_billed(self):
        runs = [_Run(f"r{i}") for i in range(4)]

        def work(run):
            for k in range(25):
                (scout_stage if k % 2 else refill_stage)(run, 0.001 * (1 + k % 3))
        ts = [threading.Thread(target=work, args=(r,)) for r in runs]
        [t.start() for t in ts]
        [t.join() for t in ts]
        rows = self.rows()
        self.assertEqual(len(rows), 100)
        for run in runs:
            mine = [r for r in rows if r["run"] == run.id]
            self.assertEqual(len(mine), 25)
            self.assertAlmostEqual(sum(r["usd"] for r in mine), run.status["billed_usd"], places=9)
            self.assertEqual({r["stage"] for r in mine}, {"scout_stage", "refill_stage"})

    def test_cached_call_writes_no_line(self):
        pipeline._counted(_Run("c"), lambda: "cached")
        self.assertFalse(os.path.exists(self.led))


if __name__ == "__main__":
    unittest.main()
