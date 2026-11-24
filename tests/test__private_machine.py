"""Stops the whole test run at once on a machine marked private (D-LOCALSAM-F5).

A private marker (~/.config/fishcount/private, /etc/fishcount/private, or an account with no home: fishcount/api.py)
turns api.PRIVATE on and makes the last gate refuse every SAM call, so hundreds of replay tests would fail with
LocalSamError and the one reason would be lost among them. A server must never have a marker; this says so first.
`discover` imports test files in name order and `test__` comes before every other test file, so nothing else has run.

Exceptions: FISH_TEST_ON_PRIVATE=1 (a private desktop on purpose) warns and goes on; a single test file run directly
(python -m unittest tests/test_samlocal.py) never imports this one; tests that point the markers at temporary paths
are not affected, since only the real markers are looked at here. Nothing here changes api.PRIVATE or the gate.
No network, $0."""
import os, sys, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from fishcount import _pylib  # noqa: F401
from fishcount import api


def why(environ, markers):
    """-> what marks this machine private ("home-marker" / "etc-marker" / "no-home"), FISH_PRIVATE left out."""
    return api._private({}, markers)[1] if environ.get("FISH_TEST_ON_PRIVATE") != "1" else []


def message(by):
    return (f"This machine is marked private ({', '.join(by)}: ~/{api.MARKER} or {api.ETC_MARKER}), so every SAM call "
            "in the tests would be refused. On the server, delete the marker. On a private desktop, set "
            "FISH_TEST_ON_PRIVATE=1, or run a single test file directly (python -m unittest tests/test_samlocal.py).")


class PrivateMachine(unittest.TestCase):
    def test_stops_only_on_a_real_marker(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            m = os.path.join(d, "private")
            self.assertEqual(why({}, [("home-marker", m)]), [])
            open(m, "w").close()
            self.assertEqual(why({}, [("home-marker", m)]), ["home-marker"])
            self.assertEqual(why({"FISH_TEST_ON_PRIVATE": "1"}, [("home-marker", m)]), [])
            self.assertEqual(why({"FISH_TEST_ON_PRIVATE": "0"}, [("home-marker", m)]), ["home-marker"])
        self.assertEqual(why({}, None), ["no-home"])
        self.assertIn("delete the marker", message(["etc-marker"]))


_by = why(os.environ, api._markers(os.environ))
if _by:
    sys.stderr.write(message(_by) + "\n")
    sys.stderr.flush()
    # ponytail: os._exit, because the test loader turns SystemExit or any error raised while importing a test file
    # into one failed test and runs all the others anyway
    os._exit(2)
if api._private({}, api._markers(os.environ))[0]:
    sys.stderr.write("FISH_TEST_ON_PRIVATE=1: this machine is marked private; SAM replay tests will fail.\n")
