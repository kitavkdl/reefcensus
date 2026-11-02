"""Optional extra import folder for dependencies unpacked without pip (e.g. a vendored site-packages):
env FISH_PYLIB, or the first line of a git-ignored `.pylib` file in the repo root. With neither, packages come from
`pip install -r requirements.txt` as usual. Imported for its side effect before numpy/cv2/requests."""
import os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _extra():
    p = os.environ.get("FISH_PYLIB", "").strip()
    f = os.path.join(ROOT, ".pylib")
    if not p and os.path.exists(f):
        p = open(f).readline().strip()
    return os.path.expanduser(p) if p else None


_p = _extra()
if _p and _p not in sys.path:
    sys.path.insert(0, _p)
