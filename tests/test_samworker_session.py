"""samworker.track opens the sam3 session itself (no torch, no GPU: a fake predictor with sam3's shape).

sam3's start_session hands the multiplex model's init_state an offload_state_to_cpu it does not take, so
handle_request(start_session) always fails; the worker calls model.init_state and registers the session the
way start_session does, and stops with a plain error when that sam3 does not look the same. build() also sets
how many frames sam3 batches (FISH_SAM_BATCH), since its 16 does not fit an 8 GB GPU."""
import os, sys, tempfile, types, unittest
from unittest import mock

import numpy as np

from fishcount import samworker


STUB = lambda items: ["1,1,!A"] * len(items)     # the mask codec is not what this tests


class FakeModel:
    def __init__(self):
        self.calls = []

    def init_state(self, resource_path, offload_video_to_cpu=False, async_loading_frames=False,
                   use_torchcodec=False, use_cv2=False, input_is_mp4=False):
        self.calls.append(dict(resource_path=resource_path, offload_video_to_cpu=offload_video_to_cpu,
                               async_loading_frames=async_loading_frames))
        return {"clip": resource_path, "num_frames": 3, "cached_frame_outputs": {}}


class FakePredictor:
    async_loading_frames = True

    def __init__(self):
        self.model = FakeModel()
        self._all_inference_states = {}
        self.types = []

    def handle_request(self, req):
        self.types.append(req["type"])
        if req["type"] == "start_session":
            raise TypeError("init_state() got an unexpected keyword argument 'offload_state_to_cpu'")
        assert req["session_id"] in self._all_inference_states, "session not registered"
        if req["type"] == "close_session":
            del self._all_inference_states[req["session_id"]]
        elif "obj_id" in req:       # a box: sam3 caches the prompt frame's output only
            self._all_inference_states[req["session_id"]]["state"]["cached_frame_outputs"][req["frame_index"]] = {}
        return {}

    def handle_stream_request(self, req):
        """As sam3: a text prompt finds the fish on every frame; a tracked box's mask is kept only on a frame that has
        a cached output (_build_sam2_output)."""
        state = self._all_inference_states[req["session_id"]]["state"]
        assert state["clip"] == "c.mp4"
        m = np.zeros((1, 4, 6), bool)
        m[0, 1:3, 2:4] = True
        hit = dict(out_obj_ids=np.array([1]), out_probs=np.array([0.9], np.float32), out_binary_masks=m)
        none = dict(out_obj_ids=np.array([], int), out_probs=np.array([], np.float32), out_binary_masks=m[:0])
        text = req["propagation_direction"] == "forward"       # track() sends a box both ways
        for f in range(3):
            yield dict(frame_index=f, outputs=hit if text or f in state["cached_frame_outputs"] else none)


class TrackSession(unittest.TestCase):
    def test_opens_its_own_session_and_closes_it(self):
        p = FakePredictor()
        text = samworker.track(p, "c.mp4", "fish", STUB)
        self.assertTrue(text)
        self.assertNotIn("start_session", p.types)
        self.assertEqual(p.types, ["add_prompt", "close_session"])
        self.assertEqual(p.model.calls, [dict(resource_path="c.mp4", offload_video_to_cpu=False,
                                              async_loading_frames=True)])
        self.assertEqual(p._all_inference_states, {})

    def test_box_keeps_every_tracked_frame(self):
        p = FakePredictor()
        text = samworker.track(p, "c.mp4", "<1f>1<|box;x1=2;y1=1;x2=3;y2=2;w=6;h=4|>", STUB)
        self.assertEqual([line[:4] for line in text.splitlines()], ["<0f>", "<1f>", "<2f>"])

    def test_other_sam3_shape_is_a_plain_error(self):
        for broken in ("no states", "no init_state", "other args"):
            p = FakePredictor()
            if broken == "no states":
                del p._all_inference_states
            elif broken == "no init_state":
                p.model = object()
            else:
                p.model.init_state = lambda **kw: {}
            with self.subTest(broken), self.assertRaisesRegex(RuntimeError, "docs/local-sam.md"):
                samworker.track(p, "c.mp4", "fish", STUB)
            self.assertNotIn("start_session", p.types)


class RemovedMark(unittest.TestCase):
    def test_negative_prob_is_dropped(self):
        """sam3 gives an object it removes on a frame the score -1e4 and still sends its mask."""
        m = np.zeros((2, 4, 6), bool)
        m[:, 1:3, 2:4] = True
        recs = samworker.crops(np.array([1, 2]), np.array([0.8, -1e4], np.float32), m)
        self.assertEqual([r[0] for r in recs], [1])


class BuildBatch(unittest.TestCase):
    def build(self, model, **env):
        d = self.enterContext(tempfile.TemporaryDirectory())
        ck = os.path.join(d, "sam3.1_multiplex.pt")
        open(ck, "wb").write(b"weights")
        mb = types.SimpleNamespace(download_ckpt_from_hf=lambda version: ck,
                                   build_sam3_multiplex_video_predictor=lambda **kw: types.SimpleNamespace(model=model))
        with mock.patch.dict(sys.modules, {"sam3": types.ModuleType("sam3"), "sam3.model_builder": mb}), \
                mock.patch.dict(os.environ, FISH_SAM_CHECKPOINT="", **env), mock.patch.dict(samworker._SEEN, clear=True):
            if "FISH_SAM_BATCH" not in env:
                os.environ.pop("FISH_SAM_BATCH", None)
            samworker._SEEN[ck] = samworker._stat(ck)
            return samworker.build()

    def test_batch_is_one_unless_set(self):
        for env, want in (({}, 1), ({"FISH_SAM_BATCH": "4"}, 4)):
            m = types.SimpleNamespace(batched_grounding_batch_size=16, postprocess_batch_size=16)
            self.build(m, **env)
            self.assertEqual((m.batched_grounding_batch_size, m.postprocess_batch_size), (want, want))

    def test_other_sam3_shape_is_a_plain_error(self):
        with self.assertRaisesRegex(RuntimeError, "docs/local-sam.md"):
            self.build(types.SimpleNamespace(postprocess_batch_size=16))


if __name__ == "__main__":
    unittest.main()
