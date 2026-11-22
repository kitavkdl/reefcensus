"""A source file that is cut short, damaged in the middle, or has no length in it is no longer analysed short in
silence (round 3, data-manager view). Reproduced 11/21c on synthetic clips: a 120-s file cut to 45 % of its bytes
gave 54 s of analysis with no error, one with a zeroed middle printed 2,992 decoder errors and went on, and a 700-s
raw H.264 stream (frame count -1.9e14 in OpenCV) took the CLI's short path and only its first 600 s were analysed.
Intact clips: the ingest output bytes are what they were and no warning is raised (12 real clips from 6+ cameras,
11/21c, round3_work/r4/real_check.log). No network."""
import hashlib, os, subprocess, sys, tempfile, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fishcount import _pylib  # noqa: F401
from fishcount import longvideo, video


def sha(p):
    with open(p, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def ff(*a):
    subprocess.run([video.FFMPEG, "-hide_banner", "-loglevel", "error", "-y", *a], check=True)


class SourceCheck(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.full = cls.p("full.mp4")
        ff("-f", "lavfi", "-i", "testsrc2=size=192x108:rate=10", "-t", "40", "-c:v", "libx264", "-preset", "ultrafast",
           "-g", "20", "-movflags", "+faststart", "-pix_fmt", "yuv420p", cls.full)
        with open(cls.full, "rb") as fh:
            b = fh.read()
        with open(cls.p("cut.mp4"), "wb") as fh:
            fh.write(b[: int(len(b) * 0.45)])
        lo, hi = int(len(b) * 0.4), int(len(b) * 0.6)
        with open(cls.p("hole.mp4"), "wb") as fh:
            fh.write(b[:lo] + bytes(hi - lo) + b[hi:])
        ff("-f", "lavfi", "-i", "testsrc2=size=192x108:rate=10", "-t", "30", "-c:v", "libx264", "-preset", "ultrafast",
           "-f", "h264", cls.p("raw.h264"))

    @classmethod
    def p(cls, n):
        return os.path.join(cls.tmp, n)

    def test_intact_clip_no_warning_and_same_bytes(self):
        got = video.ingest(self.full, self.p("new.mp4"))
        self.assertEqual(got["source_warnings"], [])
        self.assertEqual(got["n_frames"], 200)
        # the ingest command as it was before (check=True, stderr to the terminal)
        ff("-i", self.full, "-t", "600", "-vf", "fps=5,scale='min(1920,iw)':-2", "-an", "-c:v", "libx264",
           *video.X264_ARGS, "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", self.p("old.mp4"))
        self.assertEqual(sha(self.p("new.mp4")), sha(self.p("old.mp4")))

    def test_cut_short_file_is_named(self):
        got = video.ingest(self.p("cut.mp4"), self.p("cut5.mp4"))
        self.assertLess(got["n_frames"], 150)                   # still analysed as far as it goes
        self.assertTrue(any("ends early" in w and "40 s" in w for w in got["source_warnings"]), got["source_warnings"])

    def test_damaged_middle_is_named(self):
        got = video.ingest(self.p("hole.mp4"), self.p("hole5.mp4"))
        self.assertTrue(any("decoder error" in w for w in got["source_warnings"]), got["source_warnings"])

    def test_unknown_length_cut_at_the_limit_is_named(self):
        self.assertLessEqual(video.info(self.p("raw.h264"))["n_frames"], 0)       # what OpenCV says of a raw stream
        got = video.ingest(self.p("raw.h264"), self.p("raw5.mp4"), max_seconds=20)
        self.assertEqual(got["n_frames"], 100)
        self.assertTrue(any("length is unknown" in w and "first 20 s" in w for w in got["source_warnings"]),
                        got["source_warnings"])

    def test_unknown_length_read_whole_is_not_a_warning(self):
        got = video.ingest(self.p("raw.h264"), self.p("raw5b.mp4"), max_seconds=10 ** 7)
        self.assertEqual((got["n_frames"], got["source_warnings"]), (150, []))

    def test_cli_sends_unknown_length_to_the_long_video_path(self):
        self.assertTrue(longvideo.needs_split(video.info(self.p("raw.h264"))))
        self.assertFalse(longvideo.needs_split(video.info(self.full)))
        self.assertTrue(longvideo.needs_split(dict(n_frames=3005, fps=5.0)))
        self.assertFalse(longvideo.needs_split(dict(n_frames=3000, fps=5.0)))
        self.assertTrue(longvideo.needs_split(video.info(self.full), segment=20))


if __name__ == "__main__":
    unittest.main()
