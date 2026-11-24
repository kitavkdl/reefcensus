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


def tracker(num_maskmem=7, r=1, selection=False):
    return types.SimpleNamespace(num_maskmem=num_maskmem, memory_temporal_stride_for_eval=r, use_memory_selection=selection)


class FakeModel:
    def __init__(self):
        self.calls, self.sam2 = [], True
        self.tracker = types.SimpleNamespace(model=tracker())

    def init_state(self, resource_path, offload_video_to_cpu=False, async_loading_frames=False,
                   use_torchcodec=False, use_cv2=False, input_is_mp4=False):
        self.calls.append(dict(resource_path=resource_path, offload_video_to_cpu=offload_video_to_cpu,
                               async_loading_frames=async_loading_frames))
        state = {"clip": resource_path, "num_frames": 3, "cached_frame_outputs": {}}
        if self.sam2:
            state["sam2_inference_states"] = []
        return state


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
        self.assertEqual(p.model.calls, [dict(resource_path="c.mp4", offload_video_to_cpu=True,
                                              async_loading_frames=True)])
        self.assertEqual(p._all_inference_states, {})

    def test_frames_in_ram_unless_offload_is_0(self):
        for env, want in (({}, True), ({"FISH_SAM_OFFLOAD": "1"}, True), ({"FISH_SAM_OFFLOAD": "0"}, False)):
            p = FakePredictor()
            with mock.patch.dict(os.environ, env):
                if not env:
                    os.environ.pop("FISH_SAM_OFFLOAD", None)
                samworker.track(p, "c.mp4", "fish", STUB)
            self.assertEqual(p.model.calls[0]["offload_video_to_cpu"], want, env)

    def test_box_keeps_every_tracked_frame(self):
        p = FakePredictor()
        text = samworker.track(p, "c.mp4", "<1f>1<|box;x1=2;y1=1;x2=3;y2=2;w=6;h=4|>", STUB)
        self.assertEqual([line[:4] for line in text.splitlines()], ["<0f>", "<1f>", "<2f>"])

    def test_other_sam3_shape_is_a_plain_error(self):
        for broken in ("no states", "no init_state", "other args", "no tracker", "memory selection", "no sam2 states"):
            p = FakePredictor()
            if broken == "no states":
                del p._all_inference_states
            elif broken == "no init_state":
                p.model = object()
            elif broken == "other args":
                p.model.init_state = lambda **kw: {}
            elif broken == "no tracker":
                del p.model.tracker
            elif broken == "memory selection":       # sam3 would read old "good" frames back: parking them is unsafe
                p.model.tracker.model.use_memory_selection = True
            else:
                p.model.sam2 = False
            with self.subTest(broken), self.assertRaisesRegex(RuntimeError, "docs/local-sam.md"):
                samworker.track(p, "c.mp4", "fish", STUB)
            self.assertNotIn("start_session", p.types)


class FakeT:
    """A tensor as far as parking looks: where it lives, and .cpu() (a copy in RAM; already there = itself)."""
    def __init__(self, cuda=True):
        self.is_cuda = cuda

    def cpu(self):
        return FakeT(False) if self.is_cuda else self


class MemoryPredictor(FakePredictor):
    """sam3's tracking memory over N frames (31cb7e6, video_tracking_multiplex.py:1384-1407 and :1467): each frame
    reads the earlier outputs within (num_maskmem-1)*r+2 frames in its direction (backward: later ones), including
    their image features, then stores its own output in output_dict and in each object's dict. "both" runs
    forward from the prompt frame, then backward over the same state (sam3_base_predictor.py:343-361)."""
    def __init__(self, n):
        super().__init__()
        self.n, self.lost, self.pos = n, [], FakeT()      # pos: maskmem_pos_enc, one shared copy

    def handle_stream_request(self, req):
        state = self._all_inference_states[req["session_id"]]["state"]
        trk, start = self.model.tracker.model, req["start_frame_index"]
        reach = (trk.num_maskmem - 1) * trk.memory_temporal_stride_for_eval + 2
        s2 = {"output_dict": {"cond_frame_outputs": {}, "non_cond_frame_outputs": {}},
              "output_dict_per_obj": {0: {"cond_frame_outputs": {}, "non_cond_frame_outputs": {}}}}
        m = np.zeros((1, 4, 6), bool)
        m[0, 1:3, 2:4] = True
        hit = dict(out_obj_ids=np.array([1]), out_probs=np.array([0.9], np.float32), out_binary_masks=m)
        order = [(f, 1) for f in range(start, self.n)]
        if req["propagation_direction"] == "both":
            order += [(f, -1) for f in range(start, -1, -1)]
        for f, step in order:
            state["sam2_inference_states"] = [s2]        # sam3 swaps the list itself as objects come and go
            dicts = [s2["output_dict"]] + list(s2["output_dict_per_obj"].values())
            for t in range(1, reach + 1):
                for d in dicts:
                    o = d["non_cond_frame_outputs"].get(f - t * step)
                    if o is not None and not ("image_features" in o and "image_pos_enc" in o):
                        self.lost.append((f, f - t * step))
            for d in dicts:
                out = dict(maskmem_features=FakeT(), pred_masks=FakeT(), pred_masks_high_res=FakeT(),
                           image_features=FakeT(), image_pos_enc=FakeT(), obj_ptr=FakeT(), maskmem_pos_enc=self.pos)
                d["cond_frame_outputs" if f == start else "non_cond_frame_outputs"].setdefault(f, out)
            yield dict(frame_index=f, outputs=hit)
        self.s2 = s2


class Parking(unittest.TestCase):
    """Old tracking outputs go to RAM (D-LOCALSAM-F3): sam3 keeps every past frame's output on the GPU, so an 8 GB
    card spills from ~150 frames on. An output further back than sam3 ever reads moves its masks and memory to RAM
    and drops its image features; nothing sam3 reads again is touched (on the GPU: 600/600 frames byte-identical)."""
    def run_track(self, prompt, n, **trk):
        p = MemoryPredictor(n)
        p.model.tracker.model = tracker(**trk)
        samworker.track(p, "c.mp4", prompt, STUB)
        self.assertEqual(p.lost, [], "sam3 read a frame whose image features were dropped")
        return p

    def check(self, p, start, k):
        for d in [p.s2["output_dict"]] + list(p.s2["output_dict_per_obj"].values()):
            for f, o in d["non_cond_frame_outputs"].items():
                parked = start + k < f <= p.n - 1 - k or k <= f < start - k
                with self.subTest(frame=f):
                    self.assertEqual("image_features" in o, not parked)
                    self.assertEqual("image_pos_enc" in o, not parked)
                    for key in ("maskmem_features", "pred_masks", "pred_masks_high_res"):
                        self.assertEqual(o[key].is_cuda, not parked, key)
                    self.assertTrue(o["obj_ptr"].is_cuda)       # later frames read pointers far back: stays
                    self.assertIs(o["maskmem_pos_enc"], p.pos)   # shared by all frames: never copied
            for o in d["cond_frame_outputs"].values():
                self.assertIn("image_features", o)

    def test_word_call_forward(self):
        self.check(self.run_track("fish", 60), 0, 9)            # K = 7 * 1 + 2

    def test_box_call_both_ways_keeps_the_prompt_frame_neighbours(self):
        box = "<30f>1<|box;x1=2;y1=1;x2=3;y2=2;w=6;h=4|>"
        self.check(self.run_track(box, 60), 30, 9)

    def test_memory_stride(self):
        box = "<40f>1<|box;x1=2;y1=1;x2=3;y2=2;w=6;h=4|>"
        self.check(self.run_track(box, 90, num_maskmem=4, r=3), 40, 14)     # K = 4 * 3 + 2

    def test_parking_twice_changes_nothing(self):
        o = dict(maskmem_features=FakeT(), pred_masks=FakeT(), image_features=FakeT(), obj_ptr=FakeT())
        state = {"sam2_inference_states": [{"output_dict": {"non_cond_frame_outputs": {3: o}},
                                            "output_dict_per_obj": {}}]}
        samworker._park(state, 3)
        once = state["sam2_inference_states"][0]["output_dict"]["non_cond_frame_outputs"][3]
        samworker._park(state, 3)
        twice = state["sam2_inference_states"][0]["output_dict"]["non_cond_frame_outputs"][3]
        self.assertEqual(sorted(once), ["maskmem_features", "obj_ptr", "pred_masks"])
        self.assertIs(twice["maskmem_features"], once["maskmem_features"])
        self.assertIs(twice["obj_ptr"], o["obj_ptr"])
        samworker._park(state, 99)          # nothing stored there: nothing happens


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

    def test_bad_batch_is_a_plain_error(self):
        for v in ("0", "-2", "two", "1.5", "", "²"):
            m = types.SimpleNamespace(batched_grounding_batch_size=16, postprocess_batch_size=16)
            with self.assertRaisesRegex(RuntimeError, "FISH_SAM_BATCH"):
                self.build(m, FISH_SAM_BATCH=v)

    def test_other_sam3_shape_is_a_plain_error(self):
        with self.assertRaisesRegex(RuntimeError, "docs/local-sam.md"):
            self.build(types.SimpleNamespace(postprocess_batch_size=16))


if __name__ == "__main__":
    unittest.main()
