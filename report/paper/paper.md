---
title: "Ask for Fish, Find the Hagfish: Failure Modes of a VLM-Audited Promptable Segmenter for Abundance Counts in Baited Underwater Video"
author: "Jiyul Ahn · Meta AI hackathon, 26 Oct – 4 Nov 2026 · draft of 2 Nov 2026"
lang: en
---

<div class="abstract">

**Abstract.** Baited remote underwater video (BRUV) surveys report abundance as MaxN, the largest number of
individuals of a species visible in one frame, and people still produce it by watching the footage. We analyse what
happens when two general-purpose models are combined for this task without training: SAM 3.1, a promptable video
segmenter that tracks whatever a short noun names, and Muse Spark, a vision-language model (VLM) that we use on still
frames to name and judge, not to track. The paper is organised around measured failure modes. What the segmenter
finds depends on the word: on the 39 clips we use, "animal" returned no box on 29, never more than one per frame on
the 30 seagrass clips where "fish" returned up to 10, and overlapped 3 of the 11 non-fish animals our pipeline
counted, while the species' own name, "luderick", returned nothing on all six clips of that species. Animals nobody
asked about are mostly missed unless the VLM names them. The VLM, used as an auditor, adopts names
placed in its prompt and changes its verdict with the layout of the evidence it is shown. We build a pipeline around
these observations, in which the VLM names, translates and audits and a person reviews a queue, and evaluate it
against model-free baselines and against the VLM counting on its own. On counting luderick, the audits match a tuned minimum-track-length rule on six
development clips and are exact on one clip more than it (20 vs 19 of 24) on held-out clips scored once under a
pre-committed protocol; since audits only remove tracks, neither the audits nor the length rule can raise box recall
above the segmenter's. The human queue holds most of the tracks behind the large count disagreements, together with real fish the VLM was unsure of.
Reported as a range between rejecting and accepting the queue (a post-hoc summary), MaxN contains the human count on 22 of the 24 held-out clips.
Asked to count each frame itself, the VLM's MaxN is above the human box count on 16 of the 24 held-out clips; the
boxes appear to omit faint fish on several of those clips (Figure 3), and a count without locations cannot be checked against them.
On four nautilus clips requested as "fish", VLM naming finds six of seven untargeted taxa without any audit (seven with
a motion cue), and the audits correct names, duplicates and one false taxon. On five held-out videos from other
studies, run once with frozen code under a pre-committed protocol, the pipeline names all four non-fish animals that
two people marked beforehand, counts three and sends the fourth to the person queue, and counts nothing that is not
an animal. We present an annotation accelerator whose counts a person confirms, not a finished census.

</div>

# Introduction

A baited remote underwater video system (BRUV) is a camera lowered next to a bait bag; it records for an hour or
more while animals arrive, feed and leave. The standard abundance metric extracted from such footage is MaxN: for
each species, the largest number of individuals visible in one frame (Priede et al., 1994; see Langlois et al.,
2020). MaxN is conservative by construction, since an animal that leaves and returns can never be counted twice,
and it is "the most commonly reported metric" for BRUVs (Whitmarsh et al., 2017, as cited by Connolly et al., 2021).
It is also expensive. BRUV analysis "typically tak[es] several hours per hour of video" (Francour et al., 1999, as
cited by Marrable et al., 2022),
and field guides ask annotators to identify "all fish ... to the lowest taxonomic level possible" (Langlois et al.,
2020, §2.6.3), then have a senior analyst re-check 10% of videos against a 95% accuracy bar (§2.6.7).

Automated counting for BRUV has made real progress, but almost always for a fixed list. Detectors have been trained
for luderick (Ditria et al., 2020a), Australasian snapper (Connolly et al., 2021), yellowfin bream
(Lopez-Marcano et al., 2021), elasmobranchs (Varini et al., 2024) and up to twelve target species plus a catch-all
"fish" class (Marrable et al., 2022). Single-habitat detectors transfer poorly to other habitats (Ditria et al.,
2020b). Two properties of the manual task are therefore hard to reach. First, the species list is open: a nautilus
survey also films hagfish and shrimp, as the supplementary video captions of Barord et al. (2014) note, and those
animals are often the interesting part. A detector trained on one taxon has no way to report them. Second, a count
is only useful if a scientist can check it. Every number needs an evidence frame, and doubtful cases need to be
surfaced rather than silently resolved.

Promptable foundation models change what an off-the-shelf system can attempt. SAM 3 performs promptable concept
segmentation in video, returning masks and identities "for all matching object instances" of a short noun phrase
(Carion et al., 2026); SAM 3.1 adds faster multi-object tracking (Meta, 2026). A general VLM can describe a frame in
open vocabulary. Neither alone does the BRUV task. The segmenter tracks only what it is told to look for, and we show
that the words it responds to are narrow. On still frames the VLM names animals, but it returns no identities to follow through a clip, and as a judge
it is subject to the anchoring, sycophancy and order effects documented for language and vision-language models
(Jones and Steinhardt, 2022; Dang et al., 2024; Tian et al., 2025).

This paper is an analysis of combining the two for abundance counting when the species list is not fixed in advance, organised around measured failure
modes rather than around a model. Our contributions are:

1. **Measurements of what a promptable video segmenter responds to on BRUV footage.** On 29 of our 39 clips SAM 3.1
   returned nothing for the hypernym "animal", and on all six luderick development clips nothing for "luderick";
   a rare name failed where a basic-level neighbour worked ("hagfish" vs. "eel"); word-prompted tracks began only
   once an animal was clear (a reversed pass recovered 16 → 60 frames for one nautilus); and a box prompt with no
   word tracked an animal that no word or zoom ever found (§7.4).
2. **A pipeline that uses the VLM as namer, translator and auditor of the segmenter,** with three audits aimed at the
   ways a MaxN goes wrong (a false track, a duplicated animal in the peak frame, a wrong box in the peak frame), a
   motion-residual path for animals no noun reaches, and a second unprimed look for tracks that rest on weak
   evidence (§4).
3. **An evaluation on two tasks** (counting against human boxes, discovery of untargeted taxa) **against model-free
   and no-audit baselines, with a design ablation** that shows recall and MaxN accuracy moving with the layout of the
   evidence sheet, including a variant that scores better on MaxN for the wrong reason, and repeated calls that
   separate the layout effect from nondeterminism (§6, §7.1). The baselines also bound the claim: on single-category
   counting a track-length rule does as well as the audits on the development clips and only one held-out clip worse, and on discovery the naming step, not the audits, finds
   the taxa.
4. **A catalogue of VLM-auditor failure modes observed in a counting pipeline**, each tied to the count it changed:
   name anchoring, vocabulary priming, layout and context sensitivity, nondeterminism, wrong rejections in the peak
   check, malformed output, and species names that are only proposals (§7.5).

We position the auditing loop as an application of a known pattern rather than a new agent: SAM 3's own data engine
uses MLLMs as "AI verifiers" of masks, and its "SAM 3 Agent" lets an MLLM propose noun phrases and check the returned
masks (Carion et al., 2026, §4 and §6). What is new here is the target (ecological counts with per-number evidence),
the specific checks that a MaxN requires, and measurements of how those checks fail.

![**Figure 1.** The same seagrass frame (luderick archive, clip 20190618_9, frame 35; CC BY 4.0) three ways. Left:
SAM 3.1 prompted with "animal", 0 detections (none in any of the clip's 107 frames). Middle: prompted with "fish", 10
detections. Right: the audited pipeline, with the names the VLM audit gave each track (7 striped seabream, 3 fish
left unidentified).](figures/compare3_luderick.jpg){.wide}

# Related work

**MaxN and BRUV annotation.** MaxN, also defined as MAXNO for baited video by Ellis and DeMartini (1995), is the
field's standard abundance index (Langlois et al., 2020). It is known to be a non-linear, saturating function of true
abundance (Schobernd et al., 2014) and to depend on non-density factors such as swimming speed and bait plume
(Kilfoil et al., 2021); Ellis and DeMartini (1995) already noted earlier deep-sea work in which MAXNO was unrelated or
inversely related to density. We do not take a position on MaxN as an index; we take it as the quantity annotators
are asked to produce, and note that because it is a single-frame maximum it inherits any duplicate or spurious
detection in that one frame (Connolly et al., 2021, report raw detector counts off by up to 50% at high density).
Shortcuts already used to cut effort have costs: subsampling 40 frames per hour kept MeanCount accurate but
underestimated species richness by about 40%, "missing the less common species" (Hsu et al., 2025).

**Automated fish detection and counting.** Closed-set detectors with tracking or sequence suppression are the norm
(Ditria et al., 2020a; Lopez-Marcano et al., 2021; Connolly et al., 2021; Varini et al., 2024). Marrable et al.
(2022) is the broadest BRUV system we found, and still reports that "88% of fish were located and given a fish label
and identified for manual labelling". Motion has been used to generate fish candidate regions for training a
detector (Salman et al., 2020) and background modelling with a false-positive filter is a classic approach for fixed
underwater cameras (Giordano et al., 2016). Datasets such as DeepFish (Saleh et al., 2020), FishNet (Khan et al.,
2023) and the luderick seagrass set (Ditria et al., 2021) support this line. Marine segmentation foundation models
are typically fine-tuned: CoralSCOP for coral stills (Zheng et al., 2024b), Dual-SAM for single-image marine animals
(Zhang et al., 2024), SAM-U for underwater video after a reported 13-point J&F drop of open-air models (Zhao et al.,
2026). SAM-family models have been used on BRUV footage in a training-free pipeline (Kavasidis et al., 2025) and as an
annotation aid (Sánchez et al., 2026). To our knowledge no prior BRUV work names and counts untargeted taxa without a
species list, or uses a VLM to audit a tracker's output at the MaxN frame.

**Open-set recognition in the ocean.** FathomNet aggregates expert-labelled ocean imagery for 2,244 concepts (Katija
et al., 2022), and its 2023 competition frames recognising "a new organism, an unusual collection of animals, or ...
out-of-sample" data as central (Orenstein et al., 2023). These works evaluate identification on images; they do not
connect open-vocabulary naming to an abundance metric and its evidence frame.

**Promptable and open-vocabulary segmentation.** SAM (Kirillov et al., 2023) and SAM 2 (Ravi et al., 2025) made
segmentation promptable by points and boxes; SAM 2 notes failures "in crowded scenes, after long occlusions or in
extended videos". SAM 3 adds concept prompts, constrained to "simple noun phrases" for "atomic visual concepts", and
lists weak zero-shot generalisation "to fine-grained out-of-domain concepts" as a limitation (Carion et al., 2026).
Open-vocabulary detectors (Liu et al., 2024; Minderer et al., 2022, 2023; Cheng et al., 2024) show the same pattern
on benchmarks: OVDEval reports that top models "all fail on the new tasks except for simple object types" (Yao et
al., 2024), detection depends on which synonym names an object (Nebbia and Kovashka, 2024) and on the choice of
class names (Parisot et al., 2023). VLMs themselves prefer basic-level categories in the sense of Rosch et al.
(1976) (Sawyer et al., 2025, for two open VLMs other than the one used here), which suggests that a VLM can act as
the translator between a scientist's request and the segmenter's vocabulary. Underwater, SAM 2's quality is "extremely dependent on the type of user-provided prompts",
with ground-truth boxes working far better than automatic point prompts (Lian and Li, 2024).

**VLMs as verifiers, and how they fail.** LLMs and MLLMs are used as judges and critics (Zheng et al., 2023; Chen et
al., 2024; Xiong et al., 2025), as tool users that call vision models (Gupta and Kembhavi, 2023; Surís et al., 2023)
and as reasoning segmenters (Lai et al., 2024). Marks drawn on an image steer a VLM's attention (Yang et al., 2023;
Shtedritski et al., 2023), and cropping helps with small subjects (Zhang et al., 2025). Their failure modes are well
documented: object hallucination (Rohrbach et al., 2018; Li et al., 2023), sycophancy (Sharma et al., 2024; Li et
al., 2025), flips after a single misleading cue in 65% of cases (Dang et al., 2024), anchoring that is not fixed by
telling the model to ignore the anchor (Lou and Sun, 2024), sensitivity to option order (Pezeshkpour and Hruschka,
2024; Zheng et al., 2024a) and to image position in multi-image inputs (Tian et al., 2025), and run-to-run
nondeterminism even at temperature zero (Atil et al., 2024; He, 2025). Self-correction without external feedback is
unreliable (Huang et al., 2024); answering verification questions independently, so that "answers are not biased by
other responses", reduces hallucination (Dhuliawala et al., 2023). Our second unprimed look follows that idea.

**Humans in the loop.** Camera-trap work combines models with people: automation is gated by confidence with the
rest sent to people (Norouzzadeh et al., 2018; Beery et al., 2019), models trained on citizen-science labels reduce
human effort on new studies (Willi et al., 2019), and accuracy drops on faunas new to a model (Tabak et al., 2019).
Marine annotation platforms such as BIIGLE (Langenkämper et al., 2017), MAIA (Zurowietz et al., 2018), CoralNet
(Beijbom et al., 2015) and Squidle+ (Friedman et al., 2026) keep a person in charge with machine suggestions and
"Needs Review" flags. Verification instead of drawing is a long-standing way to cut annotation cost (Papadopoulos et
al., 2016). We follow this norm: the pipeline's output is a set of counts plus a queue of tracks that a person
should confirm.

# Problem setting

**Input.** A clip $V = (I_1, \dots, I_T)$ from a fixed camera, re-encoded to 5 frames per second, and a request $R$:
a list of plain nouns (in this paper always $R = \{\text{fish}\}$).

**Output.** A set of tracks $\mathcal{K}$, each with frames $F_k \subseteq \{1..T\}$, a box $b_{k,t}$ per frame, a
label $\ell_k$ (a species name, a category marked "unidentified", or *none* if rejected), and a flag $q_k$ meaning
"a person should look at this". For each label $s$,
$$\mathrm{MaxN}_s = \max_{t} \bigl|\{k : \ell_k = s,\ t \in F_k\}\bigr|,\qquad
t^\star_s = \arg\max_t \bigl|\{k : \ell_k = s,\ t \in F_k\}\bigr| ,$$
with the evidence frame $t^\star_s$ rendered with every counted mask, and the time of first arrival
$\min_k \min F_k$ over tracks labelled $s$. Labels are not restricted to $R$: an animal outside the request is
reported under its own name.

**What a person does with it.** The reviewer confirms or corrects the queued tracks and spot-checks the evidence
frames. A count is "final" only after that review; the measurements below are of the pipeline output *before* review,
together with the size of the queue that review would require.

# Method

Figure 2 shows the pipeline. The design principle is that each model does only what it was measured to do well, and
that every decision which can change a count is made on evidence a person can inspect afterwards (a saved sheet).

<figure class="wide">
<svg viewBox="0 0 920 410" xmlns="http://www.w3.org/2000/svg" font-family="Inter, DejaVu Sans, sans-serif" font-size="12">
<defs><marker id="a" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#52514e"/></marker></defs>
<style>.s{fill:#e8f1fc;stroke:#2a78d6;stroke-width:1.4}.v{fill:#fdf0e9;stroke:#d95926;stroke-width:1.4}.p{fill:#f1f1ef;stroke:#8a8983;stroke-width:1.2}.t{fill:#0b0b0b}.m{fill:#52514e;font-size:10.5px}.l{stroke:#52514e;stroke-width:1.2;fill:none;marker-end:url(#a)}.h{font-weight:600}</style>
<rect class="p" x="10" y="170" width="100" height="56" rx="6"/><text class="t h" x="60" y="194" text-anchor="middle">clip + "fish"</text><text class="m" x="60" y="211" text-anchor="middle">5 fps</text>
<rect class="s" x="150" y="20" width="200" height="62" rx="6"/><text class="t h" x="250" y="43" text-anchor="middle">SAM 3.1 word tracks</text><text class="m" x="250" y="60" text-anchor="middle">request noun, reversed clip,</text><text class="m" x="250" y="73" text-anchor="middle">2×2-cell blocks, 3× cells</text>
<rect class="v" x="150" y="110" width="200" height="62" rx="6"/><text class="t h" x="250" y="133" text-anchor="middle">Spark: discover</text><text class="m" x="250" y="150" text-anchor="middle">"what else lives here?"</text><text class="m" x="250" y="163" text-anchor="middle">→ basic-level nouns, cells</text>
<rect class="s" x="150" y="200" width="200" height="50" rx="6"/><text class="t h" x="250" y="222" text-anchor="middle">SAM word ladder</text><text class="m" x="250" y="239" text-anchor="middle">"hagfish" 0 → "eel" 24 frames</text>
<rect class="p" x="150" y="280" width="200" height="50" rx="6"/><text class="t h" x="250" y="302" text-anchor="middle">motion residual</text><text class="m" x="250" y="319" text-anchor="middle">pixels only, outside every box</text>
<rect class="v" x="150" y="350" width="200" height="50" rx="6"/><text class="t h" x="250" y="372" text-anchor="middle">Spark: animal or not?</text><text class="m" x="250" y="389" text-anchor="middle">3 moments per spot → SAM box</text>
<rect class="p" x="400" y="170" width="120" height="56" rx="6"/><text class="t h" x="460" y="194" text-anchor="middle">merge + stitch</text><text class="m" x="460" y="211" text-anchor="middle">IoU 0.5 / gap ≤10</text>
<rect class="v" x="560" y="20" width="170" height="62" rx="6"/><text class="t h" x="645" y="43" text-anchor="middle">A1 track audit</text><text class="m" x="645" y="60" text-anchor="middle">3 moments per track:</text><text class="m" x="645" y="73" text-anchor="middle">target? species? conf.</text>
<rect class="v" x="560" y="110" width="170" height="62" rx="6"/><text class="t h" x="645" y="133" text-anchor="middle">A2 second look</text><text class="m" x="645" y="150" text-anchor="middle">motion / renamed tracks:</text><text class="m" x="645" y="163" text-anchor="middle">no label, no earlier names</text>
<rect class="v" x="560" y="200" width="170" height="62" rx="6"/><text class="t h" x="645" y="223" text-anchor="middle">A3 same animal?</text><text class="m" x="645" y="240" text-anchor="middle">nested masks ≥80%,</text><text class="m" x="645" y="253" text-anchor="middle">both outlines drawn</text>
<rect class="v" x="560" y="290" width="170" height="62" rx="6"/><text class="t h" x="645" y="313" text-anchor="middle">A4 peak-frame check</text><text class="m" x="645" y="330" text-anchor="middle">every box in t*, with the</text><text class="m" x="645" y="343" text-anchor="middle">track before and after</text>
<rect class="p" x="770" y="150" width="140" height="96" rx="6"/><text class="t h" x="840" y="176" text-anchor="middle">MaxN per label</text><text class="m" x="840" y="194" text-anchor="middle">first arrival</text><text class="m" x="840" y="208" text-anchor="middle">evidence frame</text><text class="m" x="840" y="222" text-anchor="middle">human queue</text><text class="m" x="840" y="236" text-anchor="middle">CSV, review screen</text>
<path class="l" d="M110,190 L148,51"/><path class="l" d="M110,198 L148,141"/><path class="l" d="M250,172 L250,198"/><path class="l" d="M110,212 L148,305"/><path class="l" d="M250,330 L250,348"/>
<path class="l" d="M350,51 L398,186"/><path class="l" d="M350,225 L398,200"/><path class="l" d="M350,375 L398,214"/>
<path class="l" d="M520,190 L558,51"/><path class="l" d="M645,82 L645,108"/><path class="l" d="M645,172 L645,198"/><path class="l" d="M645,262 L645,288"/><path class="l" d="M730,321 L768,222"/>
<text class="m" x="400" y="398">blue: SAM 3.1 · orange: Muse Spark · grey: no model</text>
</svg>
<figcaption>**Figure 2.** Pipeline. Blue boxes call SAM 3.1, orange boxes call Muse Spark, grey boxes use no model.
Every Spark decision that can change a count is made on a saved sheet of crops that a reviewer can open.</figcaption>
</figure>

## Models and access

Both models were called through Meta's hosted API: SAM 3.1 (`sam-3.1`) for video concept segmentation with text or
box prompts, returning per-frame boxes, one-bit masks and confidences; Muse Spark (`muse-spark-1.3`) through an
OpenAI-compatible chat endpoint with images. SAM 3.1 is billed per processed frame ($0.20 per 1,000 frames, minimum
50 frames per call); Spark per token, called with `reasoning_effort="low"` and `max_tokens=6000` (2,000 for the count-only baseline of §6.2). Neither model
was fine-tuned. Every call is cached by a hash of its exact input (clip bytes and prompt for SAM; images and text for
Spark), so that any run can be replayed offline at zero cost and a replay reproduces the stored decisions exactly.
Spending is capped twice: an environment variable caps the cumulative total of the project's spend ledger, and a
per-run option caps the estimated cost of one run.

## Word-prompted tracking

The clip is first tracked with each requested noun on the whole frame. Two variants address measured weaknesses
(§7.4). A **reversed pass** runs the same word on the time-reversed clip and maps the detections back, because word
tracking begins only once an animal is clearly visible and then runs forward. **Zoom passes** crop a region of the
frame, upscale it and run the word there, for animals that are small or faint at full resolution: a 2/3-size block (2×2 of the 3×3 cells)
upscaled 1.5× around a region the VLM points to, and, if that finds nothing, the single 3×3 cell upscaled 3× with
every candidate word, keeping the word that tracks longest. Detections from crops are mapped back to frame
coordinates and marked "cut" when they touch the crop border.

## Discovery: naming what was not asked for

Six frames of the clip are tiled into a contact sheet and Spark is asked for "every OTHER kind of living thing that
the request did not ask about", with three plain-noun search words per item, an expected count, the grid cells where
it appears, and indirect signs (sediment puffs, moving shadows). The prompt states the segmenter's vocabulary
constraint explicitly: plain everyday nouns work; species names, colours and words like "animal" return nothing.
For each proposed item (the prompt allows four; the pipeline keeps the first three), a **word ladder** tries Spark's own short name first and then its
search words on the full clip, stopping at the first word that tracks; the track keeps Spark's name ("hagfish") while
the word ("eel") is only SAM's handle. If the word tracks fewer animals than Spark expected, the zoom passes above
run in the cells Spark named; if an indirect sign names a suspected animal, its cell is searched with that word.

## Motion residual: looking where no word works

A BRUV camera is still, so the background barely changes. We compute a per-clip median frame in CIELAB at half
resolution, mark pixels whose colour distance from it exceeds a robust threshold (median + 6 × MAD, at least 8)
and that also changed between frames t − 2 and t + 2 by more than 0.8 times that threshold, keep blobs of 12–2,500
pixels at analysis scale, link blobs across frames into short paths, and keep paths that live at least 6 frames, have a minimum area, and lie
mostly outside every box any word pass produced (boxes dilated by ±3 frames). Up to eight such spots, longest-lived
and largest first, are shown to Spark as one sheet: each spot at three moments (early, at its median-size frame, late)
at the same zoom. Spark answers per spot whether it is an animal, with a one-word name and a confidence; it is told
that a sediment cloud changes shape across crops while an animal keeps its shape. Up to five spots it calls animals
(confidence ≥ 0.6) become **box prompts** for SAM 3.1, with no word at all; the box is grown by 40%, snapped to an
8-pixel grid and kept two pixels inside the frame (a box touching the frame edge is rejected by the API). Motion
alone never counts anything: it only says where to look.

## Merging and stitching

All passes are merged in priority order (requested and discovered words first, then zoom, reversed and motion
passes). A lower-priority detection that overlaps a kept one of the same label in the same frame is dropped, and its
track is aliased to the kept track if that happens on at least half its frames and the two never co-exist. The
overlap test is plain IoU ≥ 0.5 only for zoom detections that do not touch their crop border; every other detection
(full-frame, reversed, motion, or a crop-cut partial) overlaps when max(IoU, containment − 0.2) ≥ 0.5, where
containment is the intersection over the smaller box. Containment must therefore reach 0.7, and a partial animal
inside a full box is recognised as the same animal. Before merging, a
motion track that lies on an existing word track (IoU ≥ 0.3) in three or more frames takes that track's label and
loses the overlapping frames, so one animal is not counted under a word and a motion guess. A box drawn around two
animals that other passes boxed separately is removed. Fragmented tracks of the same label are re-joined when one
starts within 10 frames of the other's end, the two never co-occur, and the first box of the later one is near the
last box of the earlier one.

## Audits

All audit sheets share one rule learned the hard way (§7.1): **an object is always shown at three moments at the
same zoom**, because across moments an animal keeps its body shape while weed sways in place and sediment spreads.
Each Spark answer is a JSON list keyed by tile id; a reply that fails its shape check is never cached and is asked
once more.

**A1 Track audit.** Every track is shown at three moments of its life, up to 12 per sheet: the frame of its largest
box in the middle, and frames about a third of the track's length before and after it (shifted inward at the ends
of the track so that the three crops are always three different moments). The prompt carries the detector's word and
a short context string, the names the discovery step proposed for this clip (on the luderick runs, where discovery
is off, this string is effectively empty). Spark returns per track `is_target`, a species name, a confidence and a
reason. Confidence ≥ 0.7 with a named species sets the label; a confident rejection (`is_target` false, ≥ 0.7)
removes the track; every other word-prompted or discovered track keeps the label "⟨word⟩ (unidentified)" and is
counted, including an unconfident rejection. Motion-seeded tracks follow a stricter rule (§4.7). §4.7 lists which tracks are queued. For a discovered track, the question is asked about the animal Spark
named ("hagfish"), not about SAM's word ("eel").

**A2 Second, unprimed look.** Tracks seeded from motion rest on two weak signals (it moved; one sheet looked alive),
and a discovered track that A1 renames to another discovered animal rests on A1 alone. Before such a track counts,
Spark sees it again at three *other* moments (1/8, 1/2 and 7/8 along its path), with no label and no names from
earlier steps, and must answer "animal" with confidence ≥ 0.5; species confidence remains A1's job. This step was
added after the anchoring failure in §7.5.

**A3 Same animal?** Two counted detections whose masks nest (one ≥ 80% inside the other) are found
from the decoded masks; each pair is shown once, in the frame where it nests most, with both outlines drawn (red and
cyan). Pairs of the same segmenter word and pairs of two different words (for example a renamed track and a track of
another word) go on separate sheets, the second kind only in the final version (V6). Spark answers whether the cyan outline marks the same single animal or a part of it. Masks find candidates;
the judgement is needed because one mask can cover two real animals (a case we observed with two overlapping
nautiluses, where a zoom pass found the rear one alone). For a duplicate, the smaller-mask track is removed from every
frame where it nests.

**A4 Peak-frame check.** For each label, every box in its MaxN frame $t^\star$ is shown with the same track three
frames before and after, "this frame" always in the middle. Spark answers whether the middle crop shows "a whole or
partial ⟨name⟩"; the prompt asks for "true" when a crop is too blurry to tell, a deliberate bias toward keeping
boxes. For a label whose tracks all come from the requested word, ⟨name⟩ is that word ("fish"), not the species A1
proposed; for a discovered animal it is the animal's name ("hagfish"). Asking about the species removed real fish of
another species (§7.5), which led to this rule in the final version. A rejected box
removes that track for ±1 s, the MaxN curve is recomputed, and the new peak is checked, for up to three rounds. This audit exists because a per-track audit can
pass every track while the peak frame is wrong: in an early run on nautilus clip s004, most "shrimp" boxes in the peak
frame sat on hagfish bodies although each track had passed A1.

**Relabelling.** A discovered or motion track that A1 confidently says is *not* its word but names another animal
the discovery step had already named on its own (matched on the head noun, so that "small red crab on seabed"
matches "crab", never "seabed") takes that name, subject to A2.

## Human queue and outputs

A track is queued when it has no verdict, when its A1 confidence is below 0.7, when A1 rejected it (with any
confidence, so that a person can restore a wrongly removed track), or when A2 did not confirm it. Whether a queued
track counts depends on where it came from:

* **Word-prompted and discovered tracks** are removed only by a confident rejection (A1 `is_target` false, ≥ 0.7),
  which stays restorable from the queue. Every other queued track, *including an unconfident rejection*, is counted as
  "⟨word⟩ (unidentified)" until a person decides. The segmenter responded to a noun, and we prefer a visible,
  queued over-count to a silent miss. The cost is visible in s002 (§6.3), where a "fish" track A1 called "red crab"
  at 0.5 is counted as fish.
* **Motion-seeded tracks** count only when A1 accepts them with confidence ≥ 0.7 *and* A2 agrees; otherwise they are
  queued and not counted. Such a track rests on movement plus one look at a small crop, and in development a motion box
  that had drifted onto net mesh was audited as "obscured shrimp" at 0.4.

Renamed tracks counted under their new name leave the queue. A track
that A1 confidently accepts as the target without naming a species (species "unknown"; 6 of 27 luderick tracks) is
counted as "(unidentified)" but not queued:
the queue is for decisions that change a count, and species naming of such tracks is left to the per-label review.
The queue therefore mixes two kinds of item: tracks counted on weak evidence, which a reviewer should confirm, and
removed tracks, which a reviewer may restore. On luderick, 7 of the 9 queued tracks are of the first kind and 2 of
the second.

The outputs are per-label MaxN and first arrival, an evidence frame per label with all
counted masks, an annotated video, a CSV, and a review screen that shows each queued track at three moments. Prompts
are reproduced verbatim in Appendix A; thresholds are listed in Appendix B.

While the queue is open, the review screen and the CSV give MaxN as a range. The low end leaves out every queued
track no person has reviewed, so only confident verdicts and human edits count; the high end is the count as
reported, with queued "(unidentified)" tracks counted. Each review narrows the range and an empty queue leaves one
number. Removed tracks are in neither end, so a reviewer who restores one can raise the count above the high end. In
the demonstration runs the range is a single number for every label except the two "(unidentified)" rows (s002 fish
0–2, s004 shrimp 0–3).

# Experimental setup

**Counting data (luderick).** Six clips from the luderick seagrass dataset (Ditria et al., 2021; PANGAEA
doi:10.1594/PANGAEA.926930, CC BY 4.0; seagrass in south-east Queensland estuaries, 1920×1080), 665 frames at 5 fps, of which 319 carry human
boxes (543 boxes: 527 luderick, 16 bream; we score both as "fish"). The annotations are on frames extracted at
5 fps; we re-encode each video at 5 fps so that clip frame *i* is annotation frame *i* + 1, and score only annotated
frames. The annotations were made for training detectors on luderick, so other fish and partially visible fish are
not always boxed. For this task the pipeline runs with the request "fish" and without discovery or
zoom, so it measures the effect of the audits on a single-category count.

**Discovery data (nautilus).** The first 12 s (60 frames at 5 fps, 1920×1080) of each of the four supplementary
videos S1–S4 of Barord et al. (2014) (CC BY), recorded overnight by BRUVs at 300–400 m with bait, some next to a trap.
Barord et al. counted nautiluses by photo-identification, not MaxN; MaxN is our metric applied to their footage.
The request is "fish" only. Before looking at any pipeline output, one of us (not a marine biologist) listed every
non-fish animal visible in frames 0, 20, 40 and 59 of each clip at taxon level: 7 taxa over the four clips (nautilus
in all four; a red crustacean in s002; shrimp and a hagfish in s004). This is a non-expert, taxon-level ground
truth; it cannot score counts of individuals.

**Held-out discovery data.** Five videos from other studies, never used in development and chosen by a rule written
before any run (`report/paper/discovery_heldout_protocol.md`, committed first): three baited-camera clips from a
carcass study at 95 m in Saanich Inlet, British Columbia (DH1–DH3; Anderson & Bell, 2014), one from a pig-carcass
study in the Salish Sea (DH4; Anderson & Bell, 2016), both CC BY 4.0, and one fish-only BRUV clip from New Zealand
(DH5; Zintzen et al., 2012, CC BY 2.5). Each clip is the 12 s centred on the file's midpoint at 5 fps. DH1–DH4 were
selected because their source text names a non-fish animal, so they measure finding such animals, not how often
they occur; DH5 measures false discoveries. Before the run, two people marked independently, at a coarse group level
("crab-like", "shrimp-like"), the non-fish animal shapes they could see in frames 0, 20, 40 and 59: Jiyul Ahn (not a
marine biologist), by circling shapes on the sheets, and Claude, the AI assistant used to write the code, in a
committed file. The bait carcasses are not animals to find. The two lists agree on every mobile animal: crab-like in
DH1, DH2 and DH3, shrimp/lobster-like crustaceans in DH3, none in DH4 and DH5 (four animals-in-clip). Sessile
animals (an anemone-like animal in DH2, an anemone or sea star in DH3) are scored separately. The command is the
development discovery command, run once. The protocol fixes the metrics: discovery recall (reference animals that
end in a counted, non-queued row of the right group), the same for names Spark proposes, false discoveries (counted
non-fish rows whose evidence crop shows no animal, judged by Jiyul Ahn from the crop alone with the label hidden),
queue size and cost.

**Vocabulary probes.** One SAM 3.1 call for "animal" on each of the 39 clips above (6 development and 24 held-out
luderick, 4 nautilus, 5 held-out discovery) and one for "luderick" on the six development clips. The clip list and
the reported quantities (frames with a box, most boxes in one frame, and overlap with the pipeline's counted non-fish
animals) were committed in `report/paper/scripts/animal_probe.py` before the calls.

**Metrics.** For counting we match predicted to human boxes per annotated frame, greedily in the order of the human
boxes, at IoU ≥ 0.3 (sensitivity at 0.5 and 0.7 in §7.2), and report recall (with a 95% percentile bootstrap over
clips, since boxes within a track are not independent), precision, MaxN computed over the annotated frames only (for every system, so they are comparable),
the number of clips with exact MaxN and with |error| ≤ 1, and the human queue as a fraction of tracks. MaxN depends
only on how many boxes a system keeps per annotated frame, not on their labels or on the matching threshold. A queued
track counted as "(unidentified)" is a box the system outputs, so the headline numbers assume a reviewer who accepts
the queue; we also report the opposite bound, a reviewer who rejects every queued track. Replacing the greedy matching by a maximum
bipartite matching changes one box at IoU 0.3 (recall 97.4% → 97.6% for SAM alone and for the audited pipeline alike)
and none at 0.5 or 0.7. For discovery we report,
per taxon, whether Spark named it and whether it reached the final count, and whether any label outside the person's
list was counted. Queued "(unidentified)" labels are excluded from that last measure and reported separately, and a
taxon is matched leniently (s002's "small red crab" and the "small blue shrimp at bait" Spark proposed both match
the person's "red crustacean").

**Baselines.** For counting: *SAM "fish" alone*, the raw SAM 3.1 word track for "fish" on the whole frame; *SAM
confidence cut-offs* (0.5–0.8) on the same track; *merge and stitch without audits*, the full pipeline with A1–A4
disabled, replayed from cache; and *merge plus a minimum track length* of k frames (k = 2–8), a model-free rule that
removes short tracks. The length rule was suggested by an independent reviewer of our first draft, after the results
were known; we report both its best k chosen with the test labels, which favours the baseline, and k chosen
leave-one-clip-out. For discovery: *SAM "fish"
alone*; *discovery without audits*, Spark's naming, the word ladder and zoom with A1–A4 disabled; and the same *plus
the motion residual* (Spark's animal-or-not look on moving spots, then box prompts), still without A1–A4. Both
no-audit variants are replays of the cached calls of the final runs, so they see exactly the same model replies up
to the point where the audits would start. Without audits there are no species labels, so these baselines count
under SAM's word ("eel", "shrimp"). Further ablations of discovery components come from the development history
(§7.3).

**Protocol.** Results are from v16 code (luderick run tag eval6) unless marked V6. The final code (V6) differs from
v16 in two places: the A4 question for word-prompted tracks (§4.6) and A3 pairs across two different words (§4.6). It
reproduces every v16 count exactly. Luderick run eval7 was made after the first change and before the second, which
cannot act on a single-word task; the four discovery runs were replayed offline under the final code (all calls hit
the v16 cache, and no cross-word pair was found). Lower-case v-numbers (v13–v16) name code releases; V1–V6 name the audit variants of §7.1, of which V5 is
the v16 audit and V6 the final code. All luderick variants in §7.1 are
saved runs of earlier versions of the same code, re-scored with one scorer. Every number in this paper is produced by
a script in the repository from saved runs and cached model replies (§10 says which of them a fresh clone can
reproduce), except where a sentence says it is a development
observation. **The six luderick and four nautilus clips are development data.** The design was iterated on them:
the faint fish in frame 35 of 20190618_9 and the s004 peak frame were used as regression checks for every change,
and the final layout (V5) was chosen knowing the result of V4. For counting we added, after the second review, 24
held-out luderick clips scored once with frozen code under a protocol committed before the run (§6.2), and for
discovery five held-out videos from other studies, run once in the same way (§6.3). Tables 1, 2 and 3 are development
numbers; Tables 1c and 3b are held-out.

# Results

## Counting against human boxes

<div class="tablecap">**Table 1.** Luderick, six development clips, IoU ≥ 0.3. MaxN is over annotated frames; "9→10" is human
MaxN → system MaxN. *Min length 4*: merge and stitch, then drop tracks shorter than four frames (no model call).
*Audited*: the final pipeline (saved run eval6: v16 code, sheet layout V5; the final V6 code reproduces every count, §5), queued "(unidentified)" tracks counted (a reviewer who accepts the queue). *Queue
rejected*: the same run with every queued track removed.</div>

| clip | ann. frames | SAM "fish" alone R / P / MaxN | min length 4 R / P / MaxN | audited R / P / MaxN | queue rejected R / P / MaxN | queued |
|--------|----:|--------------|--------------|--------------|--------------|-----:|
| 20190618_9 | 44 | 98% / 72% / 9→10 | 98% / 72% / 9→10 | 98% / 72% / 9→10 | 75% / 72% / 9→8 | 4 of 14 |
| 20190709_14 | 126 | 100% / 72% / 2→2 | 100% / 72% / 2→2 | 100% / 72% / 2→2 | 95% / 89% / 2→2 | 1 of 3 |
| 20190618_3 | 58 | 100% / 98% / 2→3 | 100% / 100% / 2→2 | 100% / 100% / 2→2 | 100% / 100% / 2→2 | 1 of 3 |
| 20190710_4 | 40 | 82% / 100% / 2→1 | 82% / 100% / 2→1 | 82% / 100% / 2→1 | 82% / 100% / 2→1 | 0 of 1 |
| 20190709_13 | 40 | 100% / 100% / 2→2 | 100% / 100% / 2→2 | 100% / 100% / 2→2 | 100% / 100% / 2→2 | 0 of 3 |
| 20190709_4 | 11 | 100% / 71% / 2→3 | 100% / 77% / 2→2 | 100% / 77% / 2→2 | 0% / — / 2→0 | 3 of 3 |
| **all** | **319** | **97.4% / 78.7%**, exact 2/6, Σ\|err\| 4 | **97.4% / 79.2%**, exact 4/6, Σ\|err\| 2 | **97.4% / 79.2%**, exact 4/6, Σ\|err\| 2 | **84.2% / 85.3%**, exact 3/6, Σ\|err\| 4 | **9 of 27** |

**The audits remove the over-counts SAM makes, and so does a length rule.** On 20190618_3 and 20190709_4 SAM alone
counts 3 where people counted 2 (here and below, an over-count is a MaxN above the human one, not necessarily a
false detection; see the precision caveat below). In both, A1 confidently rejected one track, and in both that track was two or three
frames long and contained only unmatched boxes (recall unchanged, precision 98→100% and 71→77%). Recall stays at the
segmenter's 97.4% (529 of 543 boxes): of the 529 matched boxes, the audits removed none. The boxes are not
independent (they sit in 27 tracks on six clips), so we give a percentile bootstrap over clips rather than a binomial
interval: 92.4–100% for SAM alone, the length rule and the audited pipeline alike, and 72.1–96.4% if the queue is
rejected. With six clips these intervals are wide, and none of the counting differences in Table 1 is outside them.
Merge and stitch alone change nothing on this task (identical to SAM alone), and SAM's own confidence is no help
either: every cut-off from 0.5 to 0.7 leaves the output unchanged, and 0.8 drops recall to 35.7%. But dropping
tracks shorter than four frames, with no model call, removes exactly the same two tracks and gives exactly the same
recall, precision and MaxN (Table 1). The rule is sensitive to its threshold, which we chose with the test labels:
three frames fixes only one of the two clips (exact 3/6), and five or more frames start to remove real fish (recall
95.8% at five, 94.8% at six). Choosing k fairly, leave-one-clip-out (the k that minimises the MaxN error on the
other five clips), picks k = 4 five times and k = 3 once, when 20190709_4 is left out, and that clip then keeps its
over-count: exact 3/6, Σ|err| 3, recall 97.4%, against 4/6 and 2 for the audits. The difference is one clip. On this
single-category task, then, the audits reached the result of the best length threshold without having one tuned, and
did not clearly go beyond it. We do not claim that the audits improve MaxN
on luderick over a well-chosen heuristic; their distinct contributions are on discovery (§6.3, §7.3), where a
length rule has nothing to say about names, duplicates of crowded animals, or a motion box on a net.

**The headline recall assumes the queue is accepted.** Nine of 27 tracks are queued. If a reviewer rejected all of
them, recall would fall to 84.2% (exact MaxN 3/6, Σ|err| 4), and to 0% on 20190709_4, whose two real fish are both
queued at confidence 0.6 and 0.65. Matching each queued track to the human boxes shows why the queue cannot simply
be dropped (Table 1b): the queue holds real fish that Spark was unsure about (p0:9 in 20190618_9, confidence 0.55,
matches all 44 of its boxes in annotated frames), tracks that match nothing (p0:11, 0 of 12), and the two short
tracks A1 removed (no boxes in annotated frames). The size of the queue is also noisy (§7.1). Between the two
cases lies the MaxN range of §4.7; it contains the human MaxN on 5 of 6 clips. The exception, 20190710_4 (1 against
2), is a fish that neither end counts.

<div class="tablecap">**Table 1b.** Queued luderick tracks: boxes in annotated frames that match a human box, and
the A1 verdict.</div>

| clip | track | length | matched / boxes | A1 verdict |
|---|---|--:|--:|---|
| 20190618_9 | p0:9 | 60 | 44 / 44 | fish, species unknown, 0.55 |
| 20190618_9 | p0:2 | 36 | 2 / 7 | fish, unknown, 0.5 |
| 20190618_9 | p0:14 | 4 | 2 / 4 | fish, unknown, 0.5 |
| 20190618_9 | p0:11 | 12 | 0 / 12 | fish, unknown, 0.4 |
| 20190709_14 | p0:1 | 56 | 7 / 43 | fish, unknown, 0.6 |
| 20190709_4 | p0:0 | 59 | 10 / 11 | fish, unknown, 0.65 |
| 20190709_4 | p0:1 | 42 | 7 / 11 | fish, unknown, 0.6 |
| 20190618_3 | p0:2 | 2 | — | not a fish, 0.95 (removed) |
| 20190709_4 | p0:2 | 3 | — | not a fish, 0.9 (removed) |

The two MaxN errors that remain are of different kinds. On 20190618_9 (9→10), the frame that sets the count holds two
real fish without a human box, one cut by the left edge; the "error" is likely in the reference. On 20190710_4 (2→1), a dark
fish in murky seagrass is never detected by SAM, so no audit can add it; audits can only remove.

Precision is a lower bound. Unmatched boxes are not necessarily false: the annotations target luderick and omit some
real fish (as in the 9→10 frame above). During development we inspected by eye 6 of 12 tracks scored as false
positives in an earlier run and all 6 were unboxed fish; this is a development observation that the saved runs do
not let us reproduce. A precision change from 78.7% to 79.2% should therefore not be read as the size of the audits'
effect on false detections.

For context only: on footage from the same estuary, a Mask R-CNN trained on about 6,000 luderick annotations scored
F1 86.8% on per-video MaxN over 31 test videos, against 85.3% for marine experts and 79.0% for citizen scientists
(Ditria et al., 2020a, Table 1). The test videos, the split and the metric differ from ours and our system is not
trained on luderick, so the numbers cannot be compared. They do show that a supervised single-species detector
already matches experts at this site, which is one more reason we do not present luderick counting as this system's
contribution.

## Held-out clips

After the second review we ran the frozen final code (V6) once on every annotated video of our archive copy that
development had not used: 24 clips, 6–62 frames, 445 annotated frames, 523 boxes (496 luderick, 27 bream), human
MaxN 1–2. The protocol (clips by rule, methods, metrics, one run) was committed before the run
(`report/paper/heldout_protocol.md`); the length rule keeps the k = 4 chosen on the development clips. One change
followed the protocol commit, 26 s later and before any held-out call: the evaluator was made to fetch SAM's "fish"
reply when it was not cached (these clips had none; commit 9100f9e); the pipeline code was not touched. These clips
come from the same estuary and cameras and are shorter and sparser than the development clips, so they test
transfer within one site, not to new habitats.

<div class="tablecap">**Table 1c.** Held-out luderick clips (24), IoU ≥ 0.3, frozen V6. Script:
`report/paper/scripts/rescore_heldout.py`; Spark rows `spark_count_rescore.py`. Spark returns a count without
boxes, so it has no recall or precision; asking it for boxes would make it a detector, which the protocol did not test. † Exploratory, not in the protocol: MaxN over the low
median of five consecutive annotated frames (§6.2).</div>

| system | recall | precision | MaxN exact | within ±1 | Σ\|err\| |
|---|--:|--:|--:|--:|--:|
| SAM "fish" alone | 98.9% | 76.1% | 19/24 | 21/24 | 14 |
| merge + min length 4 | 98.9% | 76.5% | 19/24 | 21/24 | 13 |
| audited, queue accepted | 98.9% | 77.6% | 20/24 | 21/24 | 12 |
| audited, queue rejected | 95.6% | 88.5% | 21/24 | 24/24 | 3 |
| Spark alone, per-frame count | — | — | 8/24 | 16/24 | 33 |
| Spark alone, 5-frame median† | — | — | 15/24 | 22/24 | 17 |

With the queue accepted, the audits fix one over-count the length rule cannot (20190618_6, 1→2 becomes 1→1: A1
rejected a 6-frame track as "empty blue water, no fish" at 0.85, too long for k = 4) and otherwise leave the segmenter's output as it was: three clips keep
large over-counts (20190709_17 2→7, 20190709_9 1→5, 20190709_11 2→4). In the first two most tracks are queued
(5 of 8, 4 of 5); in 20190709_11 only 2 of 6 are. The queue holds 15 of 49 tracks. Rejecting it brings every clip
within ±1 (Σ|err| 3) at a recall cost of 3.3 points overall, but the cost falls on real fish: recall drops from 100%
to 52% on 20190709_15 and from 79% to 50% on 20190710_9, whose MaxN becomes an under-count (2→1).
We looked at the peak frame of the worst clip by eye: all seven boxes in 20190709_17 frame 15 are fish-shaped,
three clearly fish and four faint ones, against two human boxes, so much of the "over-count" is likely unboxed fish
rather than false detections (consistent with the precision caveat of §6.1). The held-out
result therefore repeats the development finding in a weaker form: the audits do not beat the segmenter or a length
rule on box metrics, and their useful output on this task is the queue, which contains most of the tracks behind
the clip-level over-counts, but also real fish Spark was unsure of; it narrows a person's work rather than replacing it.
Read as the range of §4.7, from queue rejected to queue accepted, the held-out MaxN is a single number on 19 of 24
clips and contains the human MaxN on 22 (mean width 0.46). Both misses lie above the human count: 20190709_11 (3–4
against 2) and 20190709_17 (3–7 against 2), the clip whose peak frame shows unboxed fish. The widest ranges (3–7,
1–5) are on the two clips with the largest over-counts, so the width points a reviewer to them. The range was defined
after these results were seen; it summarises the two protocol rows above and is not a protocol measure.

**The VLM alone gives counts that cannot be checked.** The second review asked whether Spark could replace the
segmenter. Under a protocol committed before any call (`report/paper/spark_count_protocol.md`), Spark counted the
fish in every annotated frame of both sets, one call per frame with the frame alone, and its MaxN is the largest of
those counts. It ran with the audits' model and reasoning effort, but with the frame downscaled to 1280 px (SAM sees
1920 px), `max_tokens=2000` (audits: 6000) and one prompt, which asks for every fish "including fish that are partly
visible, cut by the frame edge, or faint" (`report/paper/scripts/spark_count.py`). On the six development clips its
MaxN is within ±1 everywhere but exact on only 1 of 6 (Σ|err| 5, all above; SAM alone: 2 of 6, Σ|err| 4). On the
held-out clips it is exact on 8 of 24, within ±1 on 16 and Σ|err| 33, never below the human count (Table 1c). Per
frame the picture is closer: Spark's count equals the number of human boxes in 217 of 319 development frames (68%)
and 311 of 445 held-out frames (70%), is above it in 94 and 133 and below it in 8 and 1; the per-frame mean absolute
error, the protocol's secondary measure, is 0.40 and 0.53. Part of the clip-level gap is the statistic itself: the
maximum of many independent noisy counts is biased upward, while a tracker's counts are coherent in time. As an
exploratory check that was not in the protocol, MaxN over the low median of five consecutive annotated frames is exact
on 4 of 6 and 15 of 24 clips (held-out within ±1 22 of 24, Σ|err| 17; `report/paper/scripts/spark_count_rescore.py`,
which re-scores everything here from the bundled replies), still behind SAM alone on the held-out set.

Whether the remaining excess is false counting cannot be decided against these boxes. Spark's largest excesses fall
on the clips where SAM also exceeds the boxes (20190709_17: Spark 8, SAM 8, human 2; 20190709_9: 6, 5, 1), where we
have already seen unboxed fish. On 11 of the 19 held-out clips where SAM's MaxN equals the human count, Spark's is
higher, by up to 3. We looked by eye at the frame where Spark's count most exceeds the boxes on four of them (Figure 3): each shows, besides
the boxed fish, two or three faint fish-like shapes without a box. On such clips the
agreement of SAM and the boxes may be agreement in leaving faint fish out, and the prompt asked Spark to count
exactly those fish. Because Spark's reply is a number without locations, we cannot tell whether those shapes are what
it counted; a person cannot check the number, and nothing links it across frames into a MaxN with per-number
evidence. That, more than its error against these boxes, is why the pipeline keeps the division of labour: the
segmenter boxes, and the VLM names and judges boxes it is shown. One call returned an empty reply (all 2,000 tokens
spent on reasoning). The script committed with the protocol stopped on such a reply; we changed it to make the one
further call the protocol allows (and to send calls in parallel) and re-ran it with every earlier reply served from
the cache (commit eeb952b). No frame is missing. The 765 calls cost $2.47.

![**Figure 3.** The frame where Spark's count (Spark alone) most exceeds the human boxes, on four held-out clips where SAM's MaxN equals the human
count. Green: dataset boxes. Dashed yellow: fish-like shapes without a box, marked by us from eye inspection
(non-expert). Spark's reply has no locations, so these are not known to be what it counted. Script
`report/paper/scripts/fig_spark_over.py`.](figures/spark_over.jpg)

**Is the auditor's confidence informative?** Pooling the 74 luderick tracks A1 judged that have boxes in annotated
frames (27 development, 47 held-out), the share of tracks whose boxes mostly match a human box rises with A1's
confidence: 0 of 7 below 0.5, 5 of 11 (45%) at 0.5–0.7, 20 of 26 (77%) at 0.7–0.9 and 25 of 26 (96%) at 0.9 or
above (Brier score 0.13). The 0.7 threshold therefore sends the band where real and spurious tracks mix to a person:
the queue holds 22 tracks, of which 6 match, against 45 of 52 outside it. Because the boxes omit some real fish, these
shares are lower bounds. Script: `report/paper/scripts/calibration.py`.

## Finding what was not asked for

<div class="tablecap">**Table 2.** Nautilus development clips, request "fish". Person = non-expert, taxon-level list from four
frames per clip, made before looking at outputs.</div>

| clip | person listed (not fish) | final count (MaxN) | how it was found |
|-----|----------|-----------|------------------------------|
| s001 (night, wire trap) | nautilus: 1 in trap, 3+ outside | nautilus 2 (+1 queued) | motion residual only; every word 0 frames |
| s002 | nautilus 1; red crustaceans 2 | nautilus 1; small red crab 1 (+2 "fish (unidentified)" queued) | "nautilus"; crab via "shrimp" in a 3× cell, renamed by A1 |
| s003 | nautilus 3–4 | nautilus 3 | "nautilus" forward, reversed and zoomed |
| s004 | nautilus 1; shrimp 10+; hagfish 1 | nautilus 1; shrimp 15 (A1: "caridean shrimp" 12, "unidentified" 3); hagfish 1 | hagfish via "eel", renamed; "shrimp"; 2 shrimp via motion |

How each taxon was reached, from the run logs. **s001**: "nautilus", "shell" and "snail" track 0 frames on the full
frame, two blocks and two 3× cells of this night clip; the motion residual finds moving spots that Spark calls
"nautilus", and box prompts on them track 56 and 60 of 60 frames (A1 0.95 and 0.9, A2 yes). A third motion track
(A1 0.55) is queued. **s002**: "nautilus" tracks 48 frames. "crab" tracks 0 frames on the full frame; in the 3× cell
"crab" tracks 5 frames and "shrimp" 12, and A1 calls the "shrimp" track "small red crab, not shrimp" (0.7), which
matches Spark's discovery name, so the track is relabelled; A2 agrees. **s003**: "nautilus" tracks 33 frames forward,
60 reversed and 45 and 44 in two zoom blocks. Spark also proposed a "large striped shrimp" that no word tracked; a
motion box audited under that name was rejected by A2 (§7.5). **s004**: "hagfish" tracks 0 frames and "eel" 24,
counted as hagfish; "shrimp" tracks 40 frames forward and 60 reversed; two shrimp at the bottom edge are reached only
through motion box prompts (30 and 55 frames after merging).

<div class="tablecap">**Table 3.** Discovery summary over the four development clips (7 taxa). The no-audit baselines replay the
final runs' cached calls with A1–A4 disabled; a track counts under SAM's word, or, for a motion box prompt (which
has no word), under the one-word name Spark gave the moving spot.</div>

| measure | SAM "fish" alone | discovery, no audits | + motion, no audits | audited pipeline |
|---|--:|--:|--:|--:|
| taxa in the final count | 0 of 7 | 6 of 7 | 7 of 7 | **7 of 7** |
| ... of which under a wrong name | — | 2 ("eel" for hagfish, "shrimp" for crab) | 2 | **0** |
| non-fish labels counted that match nothing on the person's list | 0 | 0 | 1 (s003 "shrimp" 2) | **0** |
| s001 nautilus (person: 4 or more) | 0 | 0 | 3 | 2 (+1 queued) |
| s003 nautilus (person: 3–4) | 0 | 3 | 4 | 3 |
| s004 shrimp (person: 10 or more) | 0 | 15 | 18 | 15 (12 + 3 unidentified, one frame) |
| "fish" counted (the person listed non-fish animals only) | s002: 2 | s002: 2 | s002: 2; s004: 1 (motion, "small fish swimming away") | s002: 2, both queued; s004: 0 |

**The naming step finds the taxa; the audits fix names and counts.** Spark proposed nine items over the four clips.
Eight correspond to animals in the person's list; one, s003's "large striped shrimp", corresponds to nothing the
person found. SAM prompted with "fish" found none of the seven taxa (in s002 it boxed two objects as low-confidence
"fish", at least one of them a crustacean; see below). Spark's naming plus SAM's word ladder and zoom, with no audit at all, already counts six of
the seven taxa, and adding the motion residual (Figure 4), still without audits, reaches seven of seven (Table 3). The taxon
score of the full pipeline is therefore owed to discovery, not to A1–A4. What the audits change is visible in the
other rows. Without them the hagfish is counted as "eel" and the crab as "shrimp", because SAM's handle is the only
label; with them both carry the animal Spark named. With the motion residual but no audits, the s003 trap mesh is counted as two "shrimp" (a
false taxon), and A2 removes it. In s004 the shrimp MaxN, counted over both shrimp labels
in the same frame, drops from 18 to 15: A3 found six nested pairs that were one shrimp counted twice, and A4 removed a
box on the trap's pipe; these act in different frames, so the peak falls by three, not seven. A1 also splits those 15 into "caridean shrimp" (MaxN 12) and "shrimp (unidentified)" (3),
which peak together in frame 54; a per-label output, like the demo's, shows 12, but that drop is the label
fragmentation of §7.5, not a correction. The person's "10 or more" from four frames cannot say whether 15 is right, so
we report the change without scoring it. The audits also cost one animal: in s001, the third motion nautilus has A1
confidence 0.55 and waits in the queue, so the audited count (2) is further from the person's "4 or more" than the
unaudited one (3).

**A fixed noun list instead of the VLM's names.** The second review asked whether a list of common nouns would do
as well as Spark's naming at no VLM cost. We prompted SAM 3.1 on the full frame of each clip with 16 basic-level
nouns for animals seen on baited cameras (fish, shark, ray, eel, crab, shrimp, lobster, octopus, squid, snail, shell,
starfish, jellyfish, sea urchin, sea cucumber, worm), written before the calls and without "nautilus", and again with
"nautilus" added as the survey's known target ($0.55, 46 new calls; `report/paper/scripts/fixed_vocab.py`). A word
track counts as finding a taxon when it overlaps a track the audited run counted under that taxon (IoU ≥ 0.3 in at
least three frames). The generic list finds 5 of the 7 taxa, but only one (s004 shrimp) under a right word: the s002
crab is found as "octopus", the nautiluses as "snail" and "shell", the hagfish as "eel", and the s003 nautilus not at
all. Adding "nautilus" reaches 6 of 7, as many as Spark's naming without audits (Table 3), with four taxa under a
right word. The comparison favours the pipeline in two ways: the fixed list ran on the full frame only, while the
pipeline's words also get reversed passes and zoom passes (1.5× block, 3× cell) (the s002 crab is reached by the pipeline only in a 3×
cell), and a taxon counts as found only when a list track overlaps a track the audited run counted, so the list can
never be credited with an animal the pipeline missed. On these clips a fixed list is thus at least as good at finding
taxa as Spark's naming without audits. On s001 "octopus" tracks a spot for 57 frames that matches no counted animal; the baseline cannot say
whether it is the uncounted nautilus inside the trap or nothing. A fixed list thus recovers most taxa on these clips
if it happens to contain the target, but it names them by whichever word fired; what the VLM adds is the name, and a
list it did not need to be given.

**The two queued "fish" in s002.** The audited output for s002 also lists "fish (unidentified): 2", from two
low-confidence "fish" tracks that sit in the queue; the person listed no fish. One (A1: "red crab", 0.5) co-exists
with the counted crab for 42 frames without overlapping it, so it is probably the second red crustacean the person
saw, missed as a crab and left under the requested word. The other (A1: "dark elongated shape", 0.4, at the top
edge) is unidentified. Both are counted until a reviewer decides (§4.7: a word track is removed only by a confident
rejection, and the first was rejected at 0.5), so the s002 output overstates "fish" by at least one unless the queue is
worked. The person's list does not cover fish, so Table 3 reports "fish" counts separately instead of scoring them;
the s004 "fish" of the motion-only baseline is a moving spot that A1 rejects in the audited run (0.6, "box tracks
shadow").

Counts of individuals are not scored: four frames per clip are not enough for a person to count ten or more moving
shrimp. In s001 the taxon is counted but the number (2) is below what a person sees (4 or more).

![**Figure 4.** Motion-residual sheet, s004. Each group is one moving spot no box covered, shown early / middle / late
at the same zoom. Spark calls the shrimp animals and the sediment puffs not; the shrimp then go to SAM 3.1 as box
prompts with no word.](figures/motion_s004.jpg){.half}

**Held-out clips.** Table 3b is the one run on the five held-out videos (§5), with the request "fish" and the
code frozen at the protocol commit.

<div class="tablecap">**Table 3b.** Held-out discovery, one run. Reference = the non-fish animals both people marked
before the run (sessile animals in brackets, scored separately). Queue = tracks sent to a person.</div>

| clip | reference (not fish) | Spark named | counted (MaxN) | queue | cost |
|-----|----------|----------|-----------|--:|--:|
| DH1 (carcass, 95 m) | crab-like | crab | crab 1 | 1 | $0.10 |
| DH2 (carcass, 95 m) | crab-like [anemone-like] | sea anemone, crab, eel | crab 1; [sea anemone 1] | 5 | $0.30 |
| DH3 (carcass, 95 m) | crab-like; shrimp/lobster-like [radial animal] | spider crab, squat lobster shrimp, sunflower sea star | spider crab 3; squat lobster shrimp sent to the queue | 6 | $0.40 |
| DH4 (pig carcass) | none | — | none | 0 | $0.02 |
| DH5 (fish-only BRUV) | none | small shrimp | no non-fish animal | 14 | $0.24 |
| **total** | **4 animals** | **4 of 4** | **3 of 4 counted, 1 queued; 0 false** | 26 | $1.06 |

Spark names all four reference animals and the pipeline counts three. The fourth, DH3's shrimp-like crustaceans, is
reached the way s004's bottom-edge shrimp were: "shrimp", "prawn" and "lobster" track 0 frames, the motion residual
finds an "upright orange shrimp", and a box prompt tracks it in all 60 frames. A1 names it "squat lobster shrimp" at
confidence 0.5, below the 0.7 a motion track needs to count, so it goes to the person queue with its name and
evidence instead of into the count (§4.7). Every counted non-fish row shows an animal: shown the evidence crops with
the labels hidden (`report/paper/data/discovery_heldout/crops_sheet.jpg`), Jiyul Ahn called all four of them
animals; DH2's crab box also covers the carcass it sits on, which does not change the count. On the two clips without
a non-fish animal nothing non-fish was counted. DH4 produced no track. In DH5 the counted rows are "fish
(unidentified)" (MaxN 8) and "pink cusk-eel" (1), a fish whose name matches the species caption burned into that
video; Spark's "small shrimp" there, like its "eel" in DH2 and s003's "large striped shrimp", was tracked by no word
and counted nowhere. Of the sessile animals, DH2's is counted as "sea anemone"; DH3's is named "sunflower sea star",
and "starfish", "star" and "urchin" track 0 frames. The per-clip rows, evidence crops and judgement are in
`report/paper/data/discovery_heldout/`.

## Cost and time

All model calls made during development and evaluation, including discarded experiments, cost $3.04 (450 calls: 148
SAM, 302 Spark; mean Spark call $0.0044, median 653 input and 684 output tokens). The repeated-call experiment of
§7.1 added 73 Spark calls ($0.43, one call lost to an interrupted script), the held-out runs 80 calls ($0.42) and the fixed-vocabulary baseline of §6.3 46
SAM calls ($0.55), the Spark-alone counting baseline 765 Spark calls ($2.47), the vocabulary probes of §7.4 45 SAM
calls ($0.62) and the held-out discovery runs 106 calls ($1.06), for a ledger total of $8.30 over 1,516 calls; `report/paper/scripts/ledger_summary.py` produces every number in this paragraph from the
spend ledger (a copy is in the scoring bundle). From the call counts of the final
runs, a fresh discovery run on a 12-s clip makes 21–30 calls and costs an estimated $0.22–0.27, dominated by SAM
passes (15–19 per clip, each billed for the clip's 60 frames, $0.012 per pass). The spend ledger does not separate
the luderick counting runs from development calls; by the price list, one SAM pass over their 665 frames costs
$0.13, and the audits add a few Spark calls per clip. A cached replay of a discovery clip, including rendering the annotated video, takes 13–24 s
on a CPU server; live runs took up to 98 s, bounded by API latency. These are measurements on clips of 12 to 53 s;
we have not run an hour-long deployment, and SAM 3.1 accepts at most 10 minutes per file, so long videos would be
processed in segments.

# Analysis

## Ablation: the layout of the evidence changes what the audit sees

We re-scored the saved luderick runs of six audit variants (Table 4). V1–V4 differ only in the audit sheets; V5
restores the V2 layout and adds steps that are inactive on this task, and V6 changes only A4's question, so V5 and
V6 share one sheet design and the same counts. Figure 5 shows the five sheet designs (V1–V5). Each
variant was run once, so a single run cannot separate a layout effect from run-to-run variation; for the central
case we therefore repeated the judgement on the saved sheets (below).

<div class="tablecap">**Table 4.** Luderick, IoU ≥ 0.3, same SAM tracks in all rows.</div>

| variant | audit evidence | recall | precision | exact MaxN | Σ\|err\| | queued |
|------|----------------------------------|-----:|-----:|-----:|----:|----:|
| SAM alone | — | 97.4% | 78.7% | 2/6 | 4 | — |
| min length 4 | no audit; tracks under 4 frames dropped (threshold chosen on these labels) | 97.4% | 79.2% | 4/6 | 2 | — |
| V1 | one crop per track (its largest box); one crop per peak box | 95.9% | 79.3% | 3/6 | 3 | 13/27 |
| V2 | three moments per track; peak box with the track before/after, judged frame in the middle | 97.4% | 79.2% | 4/6 | 2 | 7/27 |
| V3 | V2 with 2-px borders and captions in the prompt | 97.4% | 79.2% | 4/6 | 2 | 10/27 |
| V4 | V2, but when a track starts or ends at the judged frame, that frame moves to the strip's edge (no repeated crop) | 96.3% | 79.0% | **5/6** | **1** | 9/27 |
| V5 | V2 layout restored; A2 and relabelling added (inactive on this task) | 97.4% | 79.2% | 4/6 | 2 | 9/27 |
| V6 (final) | V5, but A4 asks about the requested category ("fish"), not A1's species; A3 also checks pairs across words (none here) | 97.4% | 79.2% | 4/6 | 2 | 9/27 |

![**Figure 5.** The same SAM tracks audited with five sheet designs (V1–V5; V6 uses the V5 sheets). Recall is drawn as dots because its axis does
not start at zero. V4 has the best MaxN score and the worst recall of the three-moment designs; see text.](figures/ablation.png){.half}

**One crop is not enough.** With a single crop per track (V1), A1 called a faint fish behind seagrass "only seagrass
and water" and a 36-frame track left the count; A4 did the same to another faint fish in frame 35 of 20190618_9.
Recall fell from 97.4% to 95.9%. With three moments (V2) the same fish are kept: the body that is a smudge in one
crop is a moving fish across three.

**Position within the strip matters, not only content.** V4 changed one detail of A4: when a track starts in the
judged frame, the strip showed that frame first and two later frames, instead of repeating it on the left. The faint
fish in frame 35 of 20190618_9, whose track starts there, was again called "seagrass, no fish" and recall fell to
96.3% (Figure 6). Restoring the middle position (V5) restored 97.4%.

To check that this is not one unlucky call, we sent the saved A4 sheets for frame 35 byte for byte, 24 more times each without the
cache: the V4 sheet and the V5 sheet, each with the prompt of the code version that produced it (both verified to hit
the original cache entries), and the V5 sheet with V6's question (original call from run eval7), 72 calls in all.
Together with the three original calls:

<div class="tablecap">**Table 4b.** Spark's answer for the faint fish (tile D7) on the saved frame-35 sheet, 25 calls per
layout. Data: `report/paper/data/repeat_peak_f35.json`; tally: `report/paper/scripts/repeat_peak_score.py`.</div>

| layout | called not a fish ("seagrass", "empty water") | called "other fish" (not the label) | kept |
|---|--:|--:|--:|
| V4: judged frame at the strip's edge | 11 of 25 | 0 of 25 | 14 of 25 |
| V5: judged frame in the middle | 0 of 25 | 4 of 25 | 21 of 25 |
| V6: middle, question names the category ("fish") | 0 of 25 | 4 of 25 | 21 of 25 |

With the frame at the edge, Spark failed to see an animal in 11 of 25 calls; in the middle, never (Fisher exact test,
two-sided p = 0.0002). These 25 + 25 include the two original calls that prompted the experiment; on the 24 + 24
repeats alone the split is 10 of 24 vs. 0 of 24 (p = 0.0006). On this sheet, then, the position of the frame changes
whether the faint body is seen as a fish at all; one tile in one frame cannot say how general the effect is. Whether
the track survives differs less (removed in 11 of 25 vs. 4 of 25, p = 0.06), because in the middle layout Spark
sometimes recognised a fish but answered that it was "other fish" than the label being checked, which also removes it
(§7.5). Asking about the requested category (V6) did not remove that answer (4 of 25; see §7.5). The single runs of Table 4 thus each show one draw: V4's 96.3% is
the outcome in 11 of 25 calls, and V5's and V6's 97.4% in 21 of 25 each. The direction agrees with reports that multi-image VLMs weigh inputs
differently by position (Tian et al., 2025); their setting is separate images, ours is crops within one composite
sheet, so we call the effect similar rather than the same.

**A better MaxN for the wrong reason.** V4 has the best MaxN score of all variants (exact on 5 of 6 clips). The
improvement is on 20190618_9, where the human MaxN (9) is itself likely too low (the frame that sets the system's 10
holds two real fish without a box): by
wrongly rejecting a real fish, V4 moves the peak count from 10 to 9 and "matches" the human number. A MaxN-only
evaluation would have selected the variant that discards real animals. We therefore treat recall on human boxes as the
constraint and MaxN agreement as the objective, and we checked every sheet or prompt change against the frame-35 case
and against the s004 peak frame before accepting it, which is also why these clips are not a held-out test (§5).

**The queue moves while the counts do not.** V2, V3 and V5 count exactly the same boxes, yet send 7, 10 and 9 of the
27 tracks to a person. The differences come from confidences near the 0.7 threshold changing with cosmetic sheet
changes (borders, captions) and between runs. The queue size is therefore a noisy quantity at this sample size; we
report the final run's 9 of 27 and the observed range of 7 to 10.

![**Figure 6.** A4 sheet for the peak frame of 20190618_9 (V5). Each tile shows "this frame" in the middle with the
same track before and after. The faint fish that V1 and V4 rejected is kept when its frame sits in the middle of the
strip.](figures/verify_luderick_f35.jpg){.half}

## Sensitivity to the matching threshold

<div class="tablecap">**Table 5.** Recall / precision of SAM alone and of the final pipeline at three IoU thresholds.
MaxN columns do not depend on matching.</div>

| IoU | SAM alone | audited pipeline |
|---|---|---|
| 0.3 | 97.4% / 78.7% | 97.4% / 79.2% |
| 0.5 | 96.7% / 78.1% | 96.7% / 78.6% |
| 0.7 | 85.5% / 69.0% | 85.5% / 69.5% |

The conclusions hold at IoU 0.5 (Table 5). At 0.7 both systems lose about 12 points of recall together, which reflects box
geometry (SAM's mask-derived boxes vs. hand-drawn boxes on partly hidden fish) rather than detection; the audits
neither help nor hurt localisation, as expected since they only keep or remove whole tracks.

## Where the counts come from

Across the four discovery clips the pipeline produced 44 tracks after merging: 32 from discovered words and their
zoom or reversed passes, 10 from motion box prompts and 2 from the requested word (s002's two "fish" tracks, both
queued). Seven tracks were not counted (a confident A1 rejection, a low-confidence motion track, or an A2 "no");
A3 judged 9 nested pairs (8 in s004, 1 in s003), of which 6 were the same animal counted twice (all in s004, where
shrimp crowd; Figure 8) and 3 were kept apart; A4 checked 11 peak frames and rejected 3 boxes: a box on the trap's blue pipe (correct, checked by
eye), an 11 × 15-pixel box in empty water (not checked), and the only box of the real nautilus in s002's frame 0,
called "anemone tentacles" (wrong; the MaxN survived because a later frame became the peak, but the removal window
erased the first arrival, reported at 1.2 s instead of 0 s). Of the 10 motion
tracks, 4 were counted (s001 two nautiluses, s004 two shrimp). What discovery and the audits each contribute is
separated in Table 3 and §6.3 (no taxon without discovery; names, the s003 false taxon and the s004 duplicates fixed
by the audits). Two further components show only in this accounting and the development history:

* **Without the motion residual** the s001 nautiluses are never found: every word, block and 3× cell returned 0
  frames on this night clip, so the taxon count would be 6 of 7, and s004 would lose two shrimp at the frame edge.
* **Without the second look (v13)**, s003 counted a "large striped shrimp" that does not exist (1 false taxon); with
  it (v14 onward), 0.

## What the segmenter responds to

<div class="tablecap">**Table 6.** Prompt probes on SAM 3.1 (frames tracked, or detections per frame, as stated).
These are observations on our clips, not general claims about the model.</div>

| probe | result | consequence for the design |
|-------------|-------------|-----------|
| "animal" vs. "fish", all 39 clips | "animal": no box on 29 clips; on the 30 luderick clips at most 1 per frame where "fish" gave up to 10; it overlapped 3 of the 11 non-fish animals the pipeline counted (s002 nautilus and crab, DH2 crab). Data: `data/animal_probe/` | the VLM translates requests into basic-level nouns |
| "luderick" (the species' name), six development clips | 0 detections on all six ("fish": a peak of 1 to 10 boxes per frame, by clip) | species come from the audit; SAM gets the plain noun |
| "hagfish" vs. "eel", s004 | 0 vs. 24 frames | word ladder; Spark's name is kept as the label |
| "shell" vs. "nautilus", s002–s003 (development spikes) | "shell" tracked the s002 nautilus (47 frames) but returned nothing on an s003 crop where "nautilus" tracked (development observation); in the final runs "nautilus" tracked 16–48 frames on three clips, and on s001 every word, "shell" included, returned 0 | the VLM's own short name is tried first |
| forward vs. reversed, same word | nautilus 16 → 60 (s004), 33 → 60 (s003); shrimp 40 → 60 (s004) | every word that works is re-run on the reversed clip |
| full frame vs. 3× cell, s002 crustacean | "crab" 0 → 5, "shrimp" 0 → 12 frames | closer look in the cell the VLM names |
| box prompt with no word, s004 bottom-edge shrimp | 57 of 60 frames in the first test (55 in the pipeline); no word, tile or reversed pass ever tracked it | motion residual → box prompt |
| box touching the frame edge | HTTP 400 ("lies outside the frame") | boxes kept two pixels inside |

The pattern in Table 6 agrees with SAM 3's stated design, which constrains text to "simple noun phrases" for "atomic visual
concepts" and notes weak zero-shot generalisation to fine-grained concepts in niche domains (Carion et al., 2026), and
with benchmark findings for open-vocabulary detectors (Yao et al., 2024; Nebbia and Kovashka, 2024; Parisot et al.,
2023). We found no prior measurement of a hypernym returning nothing or of a rare-species name failing where a
basic-level neighbour works for SAM-class models. SAM 3's ontology does include an "animal" category (Carion et al.,
2026, App. D.2), so we state the result as counts on these 39 clips, not as a property of the model.
The asymmetry between word and box prompts is consistent with Lian and Li (2024) for SAM 2 underwater.

## Failure modes of the VLM auditor

**Name anchoring.** In s003, a motion box had drifted onto the legs of the trap's net. A1, whose context string
listed the discovery step's (wrong) guess "large striped shrimp", passed the track as that animal with confidence
0.75. Shown the same track at other moments with no label and no names, Spark answered "looks like trap mesh, not
animal" (Figure 7). The mechanism is the anchoring and misleading-cue effect reported for LLMs and MLLMs (Jones and
Steinhardt, 2022; Dang et al., 2024; Lou and Sun, 2024); the consequence here is a false taxon in a count. Lou and Sun
(2024) report that instructing a model to ignore an anchor does not remove the effect; we removed the anchor instead,
which is the independence step of Chain-of-Verification (Dhuliawala et al., 2023).

**Vocabulary priming.** The motion prompt offered example nouns (shrimp, crab, fish, eel, worm, starfish, snail,
octopus). In s001 Spark described a spot as a "striped nautilus shell" and named it "snail", a word from the list.
We now let a name that the discovery step already gave win when Spark's own description uses it, and A1 relabels
such tracks; the general lesson is that example lists in prompts act as answer options.

**Layout and context sensitivity.** Beyond the strip-position effect in §7.1, the same pair of nested masks (s004,
frame 27) was judged "same animal" on one sheet and "different" on another, depending on which other pairs shared
the sheet. Decisions that set a count are therefore made on small sheets with three-moment crops, and doubtful cases
go to the queue rather than to a vote.

**Nondeterminism and threshold noise.** Identical counts with queues of 7, 10 and 9 tracks (§7.1) show confidence
values moving across the 0.7 threshold between cosmetic variants and runs, and the identical frame-35 sheet received
different verdicts across 25 calls (Table 4b), consistent with reports of nondeterministic outputs at fixed
settings (Atil et al., 2024; He, 2025). Caching makes any given run exactly
reproducible, but a fresh run can differ by a track.

**Wrong rejections in the peak check.** A4 can remove a real animal. In s002 it rejected the only nautilus box in
frame 0 as "anemone tentacles"; the nautilus still counts because a later frame, where it is clearer, became the
peak, but the ±1 s removal window moved its reported first arrival from 0 s to 1.2 s (frame 6 instead of 0), and a
label with a single short appearance would have been lost. And because the A4 question names the label,
a real fish of another species can be rejected for not being that species: on the frame-35 sheet Spark
answered "other fish" for a fish under the label "striped seabream" in 4 of 25 calls (Table 4b). Under the current rule such a track
is removed from the peak frame and is not moved to another label, so a per-species check silently lowers the total.
The final version (V6) asks A4 about the requested category for word-prompted tracks and leaves the species to A1;
every saved count is unchanged, but on the same sheet the fish was still called "other fish" in 4 of 25 calls
(Table 4b). The question's examples of a different animal read "an eel, hagfish or fish", which names the category itself; with
only that phrase changed to "an eel or hagfish", the fish was kept in 25 of 25 calls on the same sheet (4 of 25 vs.
0 of 25, p = 0.11; `report/paper/scripts/repeat_peak_fixexample.py`, written before the calls).

**Malformed output.** During development Spark twice returned replies that were not valid JSON (for example
`{ polo":1 }:`); because one was cached, every replay failed. A reply that fails its schema check is now never
cached and is asked once more. Since bad replies are no longer stored, the frequency cannot be recomputed from the
cache; we report this as an engineering observation.

**Species names are proposals.** On the luderick clips, A1 labelled 4 tracks "luderick", 8 "striped seabream" (a
different species), 13 remained "fish (unidentified)" and 2 were rejected. Evaluation against boxes ignores labels,
but a per-species MaxN reported to a user would split one species into two names (in 20190618_9: "striped seabream" 7
and "fish (unidentified)" 3). Species-level labels from a general VLM need the human review the queue provides, and
a taxonomic list for the survey region would be a natural constraint to add.

<figure>
<img class="half" src="figures/audit_s003_mesh.jpg" alt="A1 sheet, s003">
<img class="half" src="figures/confirm_s003.jpg" alt="Second look, s003">
<figcaption>**Figure 7.** Name anchoring, s003. Top: A1 sheet; the right group (T6) is a motion box on the trap's net legs that
A1 passed as "large striped shrimp" (0.75), a name listed in its context. Bottom: the second look at other moments,
no label, no names: "looks like trap mesh, not animal". The track is not counted.</figcaption>
</figure>

![**Figure 8.** A3 sheet, s004: nested masks drawn red and cyan; Spark judged six of eight pairs to be one shrimp
counted twice (for example body only vs. body with legs).](figures/pairs_s004.jpg){.half}

# Scope

Counting was measured on 30 luderick clips from one estuary, discovery on nine 12-s clips from four studies in three
seas; every number above is for these clips. Counts are what a reviewer confirms from the queue and the evidence
frames, and species names are the VLM's proposals (§7.5). SAM 3.1 accepts at most 10 minutes per file, so an
hour-long deployment would be processed in segments, which we have not run.

# Ethics and broader impact

The intended use is to reduce the hours ecologists spend watching survey footage, while keeping every number
traceable to a frame and every doubtful track in front of a person. The main risk is misplaced trust: an automated
MaxN can be wrong for reasons that are invisible in a table (a wrongly rejected faint animal, a split species name),
and survey counts feed management decisions. We mitigate this by reporting the queue as part of the output and by
publishing failure cases alongside successes. The footage contains no people. We used only openly published research
footage under CC BY licences (Data statement). The discovery reference lists were made by people who are not marine
biologists, as stated where they are used.

# Reproducibility

The repository (github.com/kitavkdl/reefcensus, MIT licence; the submitted version is tagged) contains the code, the prompts, the four final discovery runs with every sheet Spark
judged (`demo/runs`), and a scoring bundle in `report/paper/data/`: the human boxes of the six luderick clips (from
Ditria et al., 2021, CC BY 4.0), SAM 3.1's reply for "fish" on each clip, the `result.json` of every scored luderick
run (V1–V6 and the merge-only baseline), the held-out runs (§6.2), the no-audit discovery runs, the held-out discovery runs with both reference lists, the
circled sheets and the label-free judgement (`data/discovery_heldout`), the two frame-35 sheets, the replies of the
repeated calls, the per-frame replies of the Spark-alone baseline (`data/spark_count`), the fixed-vocabulary tracks
(`data/fixed_vocab`) and a copy of the cost ledger. From a fresh clone, with no data download and no API key (Python 3 with NumPy, OpenCV and, for the figure,
matplotlib),

```
python3 report/paper/scripts/rescore.py              # Tables 1, 1b, 4, 5: baselines, queue bounds, intervals
python3 report/paper/scripts/rescore_heldout.py      # Table 1c: held-out clips, MaxN range
python3 report/paper/scripts/spark_count_rescore.py  # Table 1c Spark rows, per-frame agreement and MAE
python3 report/paper/scripts/score_discovery_heldout.py  # Table 3b: held-out discovery rows, queue, cost
python3 report/paper/scripts/ledger_summary.py       # cost paragraph (§6.4)
python3 report/paper/scripts/fig_ablation.py         # Figure 5
```

reproduces the counting and cost numbers of §6.1, §6.2, §6.4 and §7.1–7.2 and Table 3b; we checked this in a clone with the live
run files and video paths absent. Re-running the pipeline itself needs the source videos (luderick from PANGAEA, nautilus from the PLOS ONE
supplement) and either the model-reply cache of our runs (`cache/`, 12 MB, in the repository) for a
free, exact replay, or an API key and a spend cap for a live run, which can differ by a track (§7.5):

```
python3 fishcount/evaluate.py                                  # SAM "fish" alone vs. luderick boxes
python3 fishcount/evaluate_pipeline.py --tag eval6             # final pipeline vs. the same boxes
python3 fishcount/pipeline.py <clip> --no-scout --prompts fish --discover --zoom   # discovery run (Table 2)
python3 report/paper/scripts/discovery_noaudit.py              # Table 3: no-audit discovery replays (needs cache)
python3 report/paper/scripts/repeat_peak.py --check            # Table 4b: saved sheets hit the original cache
```

The repeated calls of Table 4b are live calls; their replies are stored in `report/paper/data/repeat_peak_f35.json`. All
calls used the model IDs fixed in `fishcount/api.py` (`sam-3.1`, `muse-spark-1.3`), and the ledger records the time
of every paid call (October–November 2026).
Hyperparameters are listed in Appendix B.

# Data statement

* **Luderick:** Ditria, E.M., Connolly, R.M., Jinks, E.L., Lopez-Marcano, S. (2021). Annotated video footage for
  automated identification and counting of fish in unconstrained marine environments. PANGAEA,
  doi:10.1594/PANGAEA.926930. CC BY 4.0. Data report: *Frontiers in Marine Science* 8:629485.
* **Nautilus:** supplementary videos S1–S4 of Barord et al. (2014), *PLoS ONE* 9(6):e100799, CC BY.
* **Held-out discovery:** Wikimedia Commons copies of PLOS ONE supplementary videos: S4, S1 and S3 of Anderson & Bell
  (2014) (DH1–DH3) and S2 of Anderson & Bell (2016) (DH4), CC BY 4.0; Video S1 of Zintzen et al. (2012) (DH5),
  CC BY 2.5. URLs and SHA-256 hashes are in `report/paper/data/discovery_heldout/clips.json`.

# References

Anderson, G.S., Bell, L.S. (2014). Deep coastal marine taphonomy: investigation into carcass decomposition in the
Saanich Inlet, British Columbia using a baited camera. *PLoS ONE* 9(10): e110710. doi:10.1371/journal.pone.0110710.

Anderson, G.S., Bell, L.S. (2016). Impact of marine submergence and season on faunal colonization and decomposition
of pig carcasses in the Salish Sea. *PLoS ONE* 11(3): e0149107. doi:10.1371/journal.pone.0149107.

Atil, B., Aykent, S., Chittams, A., Fu, L., Passonneau, R.J., Radcliffe, E., et al. (2024). Non-determinism of
"deterministic" LLM settings. arXiv:2408.04667.

Barord, G.J., Dooley, F., Dunstan, A., Ilano, A., Keister, K.N., Neumeister, H., Preuss, T., Schoepfer, S., Ward,
P.D. (2014). Comparative population assessments of *Nautilus* sp. in the Philippines, Australia, Fiji, and American
Samoa using baited remote underwater video systems. *PLoS ONE* 9(6): e100799. doi:10.1371/journal.pone.0100799.

Beery, S., Morris, D., Yang, S. (2019). Efficient pipeline for camera trap image review. arXiv:1907.06772.

Beijbom, O., Edmunds, P.J., Roelfsema, C., Smith, J., Kline, D.I., Neal, B.P., et al. (2015). Towards automated
annotation of benthic survey images: variability of human experts and operational modes of automation. *PLoS ONE*
10(7): e0130312. doi:10.1371/journal.pone.0130312.

Carion, N., Gustafson, L., Hu, Y.-T., Debnath, S., Hu, R., Surís, D., et al. (2026). SAM 3: Segment anything with
concepts. *ICLR 2026*. arXiv:2511.16719.

Chen, D., Chen, R., Zhang, S., Liu, Y., Wang, Y., Zhou, H., et al. (2024). MLLM-as-a-Judge: assessing multimodal
LLM-as-a-judge with vision-language benchmark. *ICML 2024*. arXiv:2402.04788.

Cheng, T., Song, L., Ge, Y., Liu, W., Wang, X., Shan, Y. (2024). YOLO-World: real-time open-vocabulary object
detection. *CVPR 2024*. arXiv:2401.17270.

Connolly, R.M., Fairclough, D.V., Jinks, E.L., Ditria, E.M., Jackson, G., Lopez-Marcano, S., Olds, A.D., Jinks,
K.I. (2021). Improved accuracy for automated counting of a fish in baited underwater videos for stock assessment.
*Frontiers in Marine Science* 8: 658135. doi:10.3389/fmars.2021.658135.

Dang, Y., Gao, M., Yan, Y., Zou, X., Gu, Y., Li, J., et al. (2024). Exploring response uncertainty in MLLMs: an
empirical evaluation under misleading scenarios. arXiv:2411.02708.

Dhuliawala, S., Komeili, M., Xu, J., Raileanu, R., Li, X., Celikyilmaz, A., Weston, J. (2023). Chain-of-verification
reduces hallucination in large language models. arXiv:2309.11495.

Ditria, E.M., Lopez-Marcano, S., Sievers, M., Jinks, E.L., Brown, C.J., Connolly, R.M. (2020a). Automating the
analysis of fish abundance using object detection: optimizing animal ecology with deep learning. *Frontiers in
Marine Science* 7: 429. doi:10.3389/fmars.2020.00429.

Ditria, E.M., Sievers, M., Lopez-Marcano, S., Jinks, E.L., Connolly, R.M. (2020b). Deep learning for automated
analysis of fish abundance: the benefits of training across multiple habitats. *Environmental Monitoring and
Assessment* 192(11): 698. doi:10.1007/s10661-020-08653-z.

Ditria, E.M., Connolly, R.M., Jinks, E.L., Lopez-Marcano, S. (2021). Annotated video footage for automated
identification and counting of fish in unconstrained seagrass habitats. *Frontiers in Marine Science* 8: 629485.
doi:10.3389/fmars.2021.629485. Dataset: PANGAEA, doi:10.1594/PANGAEA.926930.

Ellis, D.M., DeMartini, E.E. (1995). Evaluation of a video camera technique for indexing abundances of juvenile pink
snapper, *Pristipomoides filamentosus*, and other Hawaiian insular shelf fishes. *Fishery Bulletin* 93(1): 67–77.

Friedman, A., Monk, J., Pizarro, O., Lindsay, D., Oh, E., Thornton, B., Carroll, A., Przeslawski, R., Williams, S.
(2026). Squidle+: a collaborative platform to manage, discover and annotate marine imagery. *Frontiers in Marine
Science* 12: 1677103. doi:10.3389/fmars.2025.1677103.

Giordano, D., Palazzo, S., Spampinato, C. (2016). Fish detection. In: Fisher, R.B., et al. (eds.),
*Fish4Knowledge: Collecting and Analyzing Massive Coral Reef Fish Video Data*. Springer. doi:10.1007/978-3-319-30208-9_9.

Gupta, T., Kembhavi, A. (2023). Visual programming: compositional visual reasoning without training. *CVPR 2023*.
arXiv:2211.11559.

He, H., and Thinking Machines Lab (2025). Defeating nondeterminism in LLM inference. Technical blog post, 10 Sep 2025.
thinkingmachines.ai/blog/defeating-nondeterminism-in-llm-inference.

Hsu, T.-H.T., Gordon, S.E., Ferrari, R., Hoey, A.S., Figueira, W.F. (2025). Optimizing remote underwater video
sampling to quantify relative abundance, richness, and corallivory rates of reef fish. *Coral Reefs* 44(2): 435–449.
doi:10.1007/s00338-024-02613-6.

Huang, J., Chen, X., Mishra, S., Zheng, H.S., Yu, A.W., Song, X., Zhou, D. (2024). Large language models cannot
self-correct reasoning yet. *ICLR 2024*. arXiv:2310.01798.

Jones, E., Steinhardt, J. (2022). Capturing failures of large language models via human cognitive biases.
*NeurIPS 2022*. arXiv:2202.12299.

Katija, K., Orenstein, E., Schlining, B., Lundsten, L., Barnard, K., Sainz, G., et al. (2022). FathomNet: a global
image database for enabling artificial intelligence in the ocean. *Scientific Reports* 12: 15914.
doi:10.1038/s41598-022-19939-2.

Kavasidis, I., Sorrenti, A., Tomarchio, F., Giordano, D., Milazzo, M., Turco, G., Cattano, C., Spampinato, C.
(2025). Training-free fish species population monitoring in unconstrained underwater videos. *Procedia Computer
Science* 257. doi:10.1016/j.procs.2025.03.104.

Khan, F.F., Li, X., Temple, A.J., Elhoseiny, M. (2023). FishNet: a large-scale dataset and benchmark for fish
recognition, detection, and functional trait prediction. *ICCV 2023*, 20439–20449.

Kilfoil, J.P., Campbell, M.D., Heithaus, M.R., Zhang, Y. (2021). The influence of shark behavior and environmental
conditions on baited remote underwater video survey results. *Ecological Modelling* 447: 109507.
doi:10.1016/j.ecolmodel.2021.109507.

Kirillov, A., Mintun, E., Ravi, N., Mao, H., Rolland, C., Gustafson, L., et al. (2023). Segment anything. *ICCV
2023*. arXiv:2304.02643.

Lai, X., Tian, Z., Chen, Y., Li, Y., Yuan, Y., Liu, S., Jia, J. (2024). LISA: reasoning segmentation via large
language model. *CVPR 2024*. arXiv:2308.00692.

Langenkämper, D., Zurowietz, M., Schoening, T., Nattkemper, T.W. (2017). BIIGLE 2.0 — browsing and annotating large
marine image collections. *Frontiers in Marine Science* 4: 83. doi:10.3389/fmars.2017.00083.

Langlois, T., Goetze, J., Bond, T., Monk, J., Abesamis, R.A., Asher, J., et al. (2020). A field and video annotation
guide for baited remote underwater stereo-video surveys of demersal fish assemblages. *Methods in Ecology and
Evolution* 11(11): 1401–1409. doi:10.1111/2041-210X.13470.

Li, S., Ji, Y., Fan, W., Lu, Y., Yang, Y., Yang, W., et al. (2025). Have the VLMs lost confidence? A study of
sycophancy in VLMs. *ICLR 2025*. arXiv:2410.11302.

Li, Y., Du, Y., Zhou, K., Wang, J., Zhao, W.X., Wen, J.-R. (2023). Evaluating object hallucination in large
vision-language models. *EMNLP 2023*. arXiv:2305.10355.

Lian, S., Li, H. (2024). Evaluation of Segment Anything Model 2: the role of SAM2 in the underwater environment.
arXiv:2408.02924.

Liu, S., Zeng, Z., Ren, T., Li, F., Zhang, H., Yang, J., et al. (2024). Grounding DINO: marrying DINO with grounded
pre-training for open-set object detection. *ECCV 2024*, LNCS, 38–55. doi:10.1007/978-3-031-72970-6_3.

Lopez-Marcano, S., Jinks, E.L., Buelow, C.A., Brown, C.J., Wang, D., Kusy, B., Ditria, E.M., Connolly, R.M. (2021).
Automatic detection of fish and tracking of movement for ecology. *Ecology and Evolution* 11(12): 8254–8263.
doi:10.1002/ece3.7656.

Lou, J., Sun, Y. (2024). Anchoring bias in large language models: an experimental study. arXiv:2412.06593.

Marrable, D., Barker, K., Tippaya, S., Wyatt, M., Bainbridge, S., Stowar, M., Larke, J. (2022). Accelerating
species recognition and labelling of fish from underwater video with machine-assisted deep learning. *Frontiers in
Marine Science* 9: 944582. doi:10.3389/fmars.2022.944582.

Meta (2026). SAM 3.1 Object Multiplex release notes. github.com/facebookresearch/sam3, RELEASE_SAM3p1.md, 27 Mar
2026.

Minderer, M., Gritsenko, A., Stone, A., Neumann, M., Weissenborn, D., Dosovitskiy, A., et al. (2022). Simple
open-vocabulary object detection with vision transformers. *ECCV 2022*. arXiv:2205.06230.

Minderer, M., Gritsenko, A., Houlsby, N. (2023). Scaling open-vocabulary object detection. *NeurIPS 2023*.
arXiv:2306.09683.

Nebbia, G., Kovashka, A. (2024). Synonym relations affect object detection learned on vision-language data.
*Findings of NAACL 2024*.

Norouzzadeh, M.S., Nguyen, A., Kosmala, M., Swanson, A., Palmer, M.S., Packer, C., Clune, J. (2018). Automatically
identifying, counting, and describing wild animals in camera-trap images with deep learning. *PNAS* 115(25):
E5716–E5725. doi:10.1073/pnas.1719367115.

Orenstein, E.C., Barnard, K., Lundsten, L., Patterson, G., Woodward, B., Katija, K. (2023). The FathomNet2023
competition dataset. arXiv:2307.08781.

Papadopoulos, D.P., Uijlings, J.R.R., Keller, F., Ferrari, V. (2016). We don't need no bounding-boxes: training
object class detectors using only human verification. *CVPR 2016*. arXiv:1602.08405.

Parisot, S., Yang, Y., McDonagh, S. (2023). Learning to name classes for vision and language models. *CVPR 2023*.
arXiv:2304.01830.

Pezeshkpour, P., Hruschka, E. (2024). Large language models sensitivity to the order of options in multiple-choice
questions. *Findings of NAACL 2024*, 2006–2017.

Priede, I.G., Bagley, P.M., Smith, A., Creasey, S., Merrett, N.R. (1994). Scavenging deep demersal fishes of the
Porcupine Seabight, north-east Atlantic: observations by baited camera, trap and trawl. *Journal of the Marine
Biological Association of the UK* 74(3): 481–498. doi:10.1017/S0025315400047615.

Ravi, N., Gabeur, V., Hu, Y.-T., Hu, R., Ryali, C., Ma, T., et al. (2025). SAM 2: segment anything in images and
videos. *ICLR 2025*. arXiv:2408.00714.

Rohrbach, A., Hendricks, L.A., Burns, K., Darrell, T., Saenko, K. (2018). Object hallucination in image captioning.
*EMNLP 2018*. arXiv:1809.02156.

Rosch, E., Mervis, C.B., Gray, W.D., Johnson, D.M., Boyes-Braem, P. (1976). Basic objects in natural categories.
*Cognitive Psychology* 8(3): 382–439. doi:10.1016/0010-0285(76)90013-X.

Saleh, A., Laradji, I.H., Konovalov, D.A., Bradley, M., Vazquez, D., Sheaves, M. (2020). A realistic fish-habitat
dataset to evaluate algorithms for underwater visual analysis. *Scientific Reports* 10: 14671.
doi:10.1038/s41598-020-71639-x.

Salman, A., Siddiqui, S.A., Shafait, F., Mian, A., Shortis, M.R., Khurshid, K., Ulges, A., Schwanecke, U. (2020).
Automatic fish detection in underwater videos by a deep neural network-based hybrid motion learning system. *ICES
Journal of Marine Science* 77(4): 1295–1307. doi:10.1093/icesjms/fsz025.

Sánchez, J.S., Lisani, J.-L., Catalán, I.A., Álvarez-Ellacuría, A. (2026). A dataset for fish segmentation and
tracking in underwater videos. *Scientific Data* 13: 1181. doi:10.1038/s41597-026-07786-z.

Sawyer, H., Roberts, J., Moore, K. (2025). Basic category usage in vision language models. arXiv:2503.12530.

Schobernd, Z.H., Bacheler, N.M., Conn, P.B. (2014). Examining the utility of alternative video monitoring metrics for
indexing reef fish abundance. *Canadian Journal of Fisheries and Aquatic Sciences* 71(3): 464–471.
doi:10.1139/cjfas-2013-0086.

Sharma, M., Tong, M., Korbak, T., Duvenaud, D., Askell, A., Bowman, S.R., et al. (2024). Towards understanding
sycophancy in language models. *ICLR 2024*. arXiv:2310.13548.

Shtedritski, A., Rupprecht, C., Vedaldi, A. (2023). What does CLIP know about a red circle? Visual prompt
engineering for VLMs. *ICCV 2023*. arXiv:2304.06712.

Surís, D., Menon, S., Vondrick, C. (2023). ViperGPT: visual inference via Python execution for reasoning. *ICCV
2023*. arXiv:2303.08128.

Tabak, M.A., Norouzzadeh, M.S., Wolfson, D.W., et al. (2019). Machine learning to classify animal species in camera
trap images: applications in ecology. *Methods in Ecology and Evolution* 10(4): 585–590. doi:10.1111/2041-210X.13120.

Tian, X., Zou, S., Yang, Z., Zhang, J. (2025). Identifying and mitigating position bias of multi-image
vision-language models. *CVPR 2025*. arXiv:2503.13792.

Varini, F., Gayford, J.H., Jenrette, J., Witt, M.J., Garzon, F., Ferretti, F., et al. (2024). SharkTrack: an
accurate, generalisable software for streamlining shark and ray underwater video analysis. arXiv:2407.20623.
Journal version: *Ecological Informatics* 95: 103713 (2026).

Whitmarsh, S.K., Fairweather, P.G., Huveneers, C. (2017; online 2016). What is Big BRUVver up to? Methods and uses of baited
underwater video. *Reviews in Fish Biology and Fisheries* 27: 53–73. doi:10.1007/s11160-016-9450-1.

Willi, M., Pitman, R.T., Cardoso, A.W., Locke, C., Swanson, A., Boyer, A., Veldthuis, M., Fortson, L. (2019).
Identifying animal species in camera trap images using deep learning and citizen science. *Methods in Ecology and
Evolution* 10(1): 80–91. doi:10.1111/2041-210X.13099.

Xiong, T., Wang, X., Guo, D., Ye, Q., Fan, H., Gu, Q., et al. (2025). LLaVA-Critic: learning to evaluate multimodal
models. *CVPR 2025*. arXiv:2410.02712.

Yang, J., Zhang, H., Li, F., Zou, X., Li, C., Gao, J. (2023). Set-of-Mark prompting unleashes extraordinary visual
grounding in GPT-4V. arXiv:2310.11441.

Yao, Y., Liu, P., Zhao, T., Zhang, Q., Liao, J., Fang, C., et al. (2024). How to evaluate the generalization of
detection? A benchmark for comprehensive open-vocabulary detection. *AAAI 2024*. arXiv:2308.13177.

Zhang, J., Khayatkhoei, M., Chhikara, P., Ilievski, F. (2025). MLLMs know where to look: training-free perception of
small visual details with multimodal LLMs. *ICLR 2025*. arXiv:2502.17422.

Zhang, P., Yan, T., Liu, Y., Lu, H. (2024). Fantastic animals and where to find them: segment any marine animal with
dual SAM. *CVPR 2024*, 2578–2587.

Zhao, H., Tai, J., Wu, Y., Zhang, W., Lan, X., Wang, S., Zhang, T., Yang, W. (2026). UW-VOS: a large-scale dataset
for underwater video object segmentation. arXiv:2603.24006.

Zheng, C., Zhou, H., Meng, F., Zhou, J., Huang, M. (2024a). Large language models are not robust multiple choice
selectors. *ICLR 2024*. arXiv:2309.03882.

Zheng, L., Chiang, W.-L., Sheng, Y., Zhuang, S., Wu, Z., Zhuang, Y., et al. (2023). Judging LLM-as-a-judge with
MT-Bench and Chatbot Arena. *NeurIPS 2023 Datasets and Benchmarks*. arXiv:2306.05685.

Zheng, Z., Liang, H., Hua, B.-S., Wong, Y.H., Ang, P., Chui, A.P.Y., Yeung, S.-K. (2024b). CoralSCOP: segment any
coral image on this planet. *CVPR 2024*, 28170–28180.

Zintzen, V., Anderson, M.J., Roberts, C.D., Harvey, E.S., Stewart, A.L., Struthers, C.D. (2012). Diversity and
composition of demersal fishes along a depth gradient assessed by baited remote underwater stereo-video. *PLoS ONE*
7(10): e48522. doi:10.1371/journal.pone.0048522.

Zurowietz, M., Langenkämper, D., Hosking, B., Ruhl, H.A., Nattkemper, T.W. (2018). MAIA — a machine learning assisted
image annotation method for environmental monitoring and exploration. *PLoS ONE* 13(11): e0207498.
doi:10.1371/journal.pone.0207498.

<div class="appendix">

# Appendix A: prompts {.unnumbered}

The prompts are reproduced from `fishcount/pipeline.py` at the final version; `{…}` marks values filled in at run
time. Comments in the source record the case that motivated each sentence.

**Discovery.**
> You are helping a marine ecologist review underwater survey video. They asked only to count: {targets}. The image
> is a contact sheet of {n} frames from one clip (frame index in each top-left label). Look for every OTHER kind of
> living thing that the request did not ask about, including small, partly hidden or unusual ones. A segmentation
> model will search the video for each thing, but it only understands plain everyday English nouns (like "shell",
> "shrimp", "crab", "jellyfish", "worm", "starfish", "eel"); it returns nothing for species names, colours, or vague
> words like "animal" or "creature". Also report indirect signs that an animal may be present but hard to see: sand
> or sediment puffs, a moving shadow, bubbles, bait being disturbed, a burrow opening. Return ONLY JSON: {schema with
> `what`, `why_notable`, three `search_words`, `frames`, `approx_max_count`, `cells`; and `signs`}. At most 4 others
> (most notable first) and 3 signs.

**A1 Track audit.**
> You are checking detections from an automatic tracker in underwater survey video. Each tile is one tracked object,
> labelled with its track id (e.g. T3), shown at three moments of the clip (early, middle, late; same zoom, the
> orange box marks the object); the detector was asked to find "{label}". Context from an earlier look at the clip:
> {context}. For every tile return ONLY a JSON list: [{"track", "is_target", "species", "confidence", "reason"}].
> is_target = the tile really shows a whole or partial {target} (not seagrass, rock, bubbles, debris, a shadow, or a
> duplicate fragment you cannot tell apart). Use all three crops: an animal keeps its body shape while it moves; weed
> sways in place and sediment changes shape. A hazy or faint {target} seen through water or seagrass is still a
> {target}. Be honest about uncertainty: blurry tiles should get low confidence.

**A2 Second look.**
> Each group (C1, C2, ...) follows one tracked object in underwater survey video at three moments (captions under the
> crops), same zoom; the orange rectangle marks the object. The tracker was started from a moving spot, so it may have
> locked onto something that is not an animal. For every group return ONLY a JSON list: [{"tile", "is_animal",
> "name", "confidence", "reason"}]. is_animal = the rectangle holds the same living animal in the crops (a whole one or
> most of one; small, pale or blurry is fine). Answer false when it holds a part of a trap, net, mesh, rope, cans,
> bait, rock, seagrass, a shadow, sediment or empty water, or only a tentacle, fin or tail of a bigger animal whose
> body is elsewhere. Things fixed to the trap or seabed keep the same place against them in every crop; an animal
> changes place or pose. Be honest: if you cannot see an animal, answer false.

**A3 Same animal.**
> Each tile is a crop from one frame of underwater survey video with two outlines drawn on it: a RED outline and a
> CYAN outline, made by an automatic tracker. [...] same_animal = true when the cyan outline marks the same single
> animal as the red one (or a part of it, for example its body without the legs or its head). false when the cyan
> outline marks a different individual, for example a second animal next to, behind or in front of the first, even if
> the red outline also spills over it.

**A4 Peak-frame check.**
> Each tile is one object that an automatic tracker counted as "{name}" in a single frame of underwater survey video;
> this frame sets the maximum count, so every tile matters. [...] Each tile shows that frame in the middle ("this
> frame", orange box) and the same tracked object about half a second before and after (left, right) at the same
> zoom. [...] is_target = the middle crop mainly shows a whole or partial {name}. Answer false when the box is on a
> different animal (for example part of an eel, hagfish or fish), a net, rope, pipe, rock, sediment or empty water.
> Use the side crops: an animal keeps its body shape while it moves; weed sways in place. If it is too blurry to
> tell, answer true and say "unclear".

**Motion spots.**
> Each group (M1, M2, ...) shows one spot of underwater survey video three times, left to right: early, middle and
> late in the clip, same zoom, following the spot. The orange rectangle marks where something moved and no detector
> has boxed anything yet. [...] Compare the three crops: an animal keeps about the same shape and size (it may turn or
> move); a sand or sediment cloud spreads, thins or changes shape from crop to crop, and a shadow changes with the
> light. Black areas are outside the picture: an animal cut off by the edge of the picture still counts. [...]

# Appendix B: hyperparameters {.unnumbered}

| component | parameter | value |
|------|--------------|--------------|
| ingest | frame rate; max width; max length | 5 fps; 1920 px; 600 s |
| zoom | block (2/3 of frame) upscale; cell (1/3) upscale | 1.5×; 3× |
| discovery | items per clip; words per item; zoom tiles | ≤3; ≤3; ≤3 |
| motion | analysis scale; threshold; temporal check; blob area; min path length; spots shown; boxes prompted; Spark confidence | 0.5; median + 6·MAD (≥ 8, CIELAB); frame t±2 differ by > 0.8 × threshold; 12–2,500 px (analysis scale); 6 frames; ≤8; ≤5; ≥0.6 |
| motion | counted only if | A1 ≥ 0.7 accept and A2 yes (else queued, not counted) |
| motion | box growth; grid; edge margin | +40% (≥ 48 px); 8 px; 2 px |
| merge | overlap to drop (same label); alias if duplicate on | IoU ≥ 0.5 for uncut zoom detections, else max(IoU, containment − 0.2) ≥ 0.5; ≥ 50% of frames |
| merge | motion track absorbed into a word track | IoU ≥ 0.3 in ≥ 3 frames |
| stitch | max gap; min IoU | 10 frames; 0.2 |
| A1 | tracks per sheet; crops; label / reject confidence | 12; largest-box frame ± ⌊length/3⌋; ≥ 0.7 |
| Spark | reasoning effort; max tokens | low; 6000 |
| A2 | crops along path; animal confidence | 1/8, 1/2, 7/8; ≥ 0.5 |
| A3 | nesting (mask containment); pairs per sheet | ≥ 0.8; 16 |
| A4 | side gap; removal window; rounds; tiles per sheet | 3 frames; ±5 frames (±1 s at 5 fps); 3; 12 |
| evaluation | IoU match; MaxN frames | 0.3 (also 0.5, 0.7); annotated frames only |

</div>
