"""Cutting by seeking (-ss) gives the bytes the select-filter cut gave, so cached SAM calls on cut clips stay valid
(no network, no spend)."""
import hashlib, os, subprocess, sys, tempfile, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fishcount import _pylib  # noqa: F401
from fishcount import longvideo, video


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def enc(dst, crf, fps=5):
    return ["-an", "-fps_mode", "cfr", "-r", str(fps), "-c:v", "libx264", *video.X264_ARGS, "-preset", "veryfast",
            "-crf", str(crf), "-pix_fmt", "yuv420p", dst]


class SeekCut(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.src = os.path.join(cls.tmp, "src.mp4")
        # keyframes every 25 frames, so most cuts start between keyframes (the case a seek can get wrong)
        subprocess.run([video.FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                        "testsrc2=size=192x108:rate=5", "-frames:v", "137", "-c:v", "libx264", "-g", "25",
                        "-pix_fmt", "yuv420p", cls.src], check=True)

    def old_segment(self, dst, start, length):
        n = video.info(self.src)["n_frames"]
        end = n if length is None else min(n, start + length)
        sel = f"gte(n,{start})" if end == n else f"between(n,{start},{end - 1})"
        subprocess.run([video.FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-i", self.src, "-vf",
                        f"select='{sel}',setpts=N/FRAME_RATE/TB", *enc(dst, 18)], check=True)

    def test_segment_matches_the_select_cut(self):
        a, b = os.path.join(self.tmp, "a.mp4"), os.path.join(self.tmp, "b.mp4")
        for start, length in [(0, 40), (1, None), (13, 51), (24, 1), (25, 25), (26, 200), (70, None), (136, None), (100, 36)]:
            with self.subTest(start=start, length=length):
                self.old_segment(a, start, length)
                video.segment(self.src, b, start, length=length)
                self.assertEqual(sha(a), sha(b))

    def test_cut_matches_the_select_cut(self):
        a, b = os.path.join(self.tmp, "ca.mp4"), os.path.join(self.tmp, "cb.mp4")
        for start, n in [(0, 46), (46, 46), (92, 45), (31, 7)]:
            with self.subTest(start=start, n=n):
                subprocess.run([video.FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-i", self.src,
                                "-vf", f"select=between(n\\,{start}\\,{start + n - 1}),setpts=N/5/TB", "-r", "5", "-fps_mode", "cfr",
                                "-an", "-c:v", "libx264", *video.X264_ARGS, "-preset", "veryfast", "-crf", "20",
                                "-pix_fmt", "yuv420p", a], check=True)
                longvideo.cut(self.src, b, start, n)
                self.assertEqual(sha(a), sha(b))

    def test_chunked_reverse_matches_the_select_chunks(self):
        chunk = 40
        n = video.info(self.src)["n_frames"]
        parts = []
        for k, s in enumerate(range(0, n, chunk)):
            e = min(n, s + chunk) - 1
            p = os.path.join(self.tmp, f"old{k}.mp4")
            subprocess.run([video.FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-i", self.src, "-vf",
                            f"select='between(n,{s},{e})',setpts=N/FRAME_RATE/TB,reverse", *enc(p, 20)], check=True)
            parts.append(p)
        lst, old = os.path.join(self.tmp, "old.txt"), os.path.join(self.tmp, "old_rev.mp4")
        with open(lst, "w") as fh:
            fh.writelines(f"file '{p}'\n" for p in reversed(parts))
        subprocess.run([video.FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", lst,
                        "-c", "copy", old], check=True)
        new = os.path.join(self.tmp, "new_rev.mp4")
        video.reverse(self.src, new, chunk=chunk)
        self.assertEqual(sha(old), sha(new))


if __name__ == "__main__":
    unittest.main()
