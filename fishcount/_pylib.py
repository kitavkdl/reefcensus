"""Optional extra import folder for dependencies unpacked without pip (e.g. a vendored site-packages):
env FISH_PYLIB, or the first line of a git-ignored `.pylib` file in the repo root. With neither, packages come from
`pip install -r requirements.txt` as usual. Imported for its side effect before numpy/cv2/requests."""
import os, sys

# OpenCV's Intel IPP picks a code path per CPU, and its resize gives slightly different pixels on each (11/3: the VM
# went from an SSE4.2-only virtual CPU to the host CPU with AVX-512; audit sheets changed by up to 7 grey levels, so
# their JPEG bytes and the Spark cache key changed and two replay tests failed). Pinned to the SSE4.2 path every
# cached sheet was made with, so a sheet is the same bytes on any x86-64 machine. Must be set before cv2 is imported.
os.environ.setdefault("OPENCV_IPP", "sse42")

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
