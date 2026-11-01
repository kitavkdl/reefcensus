"""List / extract members of a remote zip using HTTP range requests (no full download).
usage: python3 rangezip.py <url> list [substr] | extract <prefix> <outdir>"""
import io, os, sys, zipfile
sys.path.insert(0, os.path.expanduser("~/meta-smoke/pylib"))
import requests


class RangeFile(io.RawIOBase):
    def __init__(self, url):
        self.url, self.pos = url, 0
        self.size = int(requests.head(url, timeout=30).headers["content-length"])
    def seekable(self): return True
    def readable(self): return True
    def tell(self): return self.pos
    def seek(self, off, whence=0):
        self.pos = {0: off, 1: self.pos + off, 2: self.size + off}[whence]
        return self.pos
    def read(self, n=-1):
        if n < 0: n = self.size - self.pos
        if n == 0 or self.pos >= self.size: return b""
        end = min(self.size, self.pos + n) - 1
        b = requests.get(self.url, headers={"Range": f"bytes={self.pos}-{end}"}, timeout=60).content
        self.pos += len(b)
        return b
    def readinto(self, buf):
        b = self.read(len(buf)); buf[:len(b)] = b; return len(b)


if __name__ == "__main__":
    url, cmd = sys.argv[1], sys.argv[2]
    z = zipfile.ZipFile(io.BufferedReader(RangeFile(url), buffer_size=1 << 20))
    names = z.namelist()
    if cmd == "list":
        sub = sys.argv[3] if len(sys.argv) > 3 else ""
        dirs = {}
        for n in names:
            if sub in n:
                d = os.path.dirname(n); dirs[d] = dirs.get(d, 0) + 1
        for d, c in sorted(dirs.items()): print(c, d)
    else:
        prefix, out = sys.argv[3], sys.argv[4]
        for n in names:
            if n.startswith(prefix) and not n.endswith("/"):
                p = os.path.join(out, os.path.basename(n))
                with open(p, "wb") as f: f.write(z.read(n))
        print("extracted", len(os.listdir(out)))
