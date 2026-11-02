# CV/ML references for Related Work and Discussion (underwater counting pipeline: SAM 3.1 + VLM auditor)

Compiled 2026-11-02. Every entry below was checked against a page opened during this session (arXiv abs page via HTTP fetch, CVF open access page, ACL Anthology page, Springer page, Crossref record, GitHub, or the Thinking Machines blog). The "verified:" line names the page. Where a venue was NOT read from an opened page but only seen in a search-result listing of the official site, the entry says "venue: listing only". Quotes are verbatim from abstracts or body text; "paraphrase" marks tight paraphrases. Location is given for each claim.

Groups: A segmentation family; B open-vocabulary detection and vocabulary/granularity; C basic-level categories; D VLM as verifier/agent/tool user; E VLM failure modes; F motion/background subtraction and fixed-camera context; G tracking, counting, metrics, annotation; H underwater precedent.

---------------------------------------------------------------------
## A. Segment Anything family

[A1] Kirillov, Mintun, Ravi, Mao, Rolland, Gustafson, Xiao, Whitehead, Berg, Lo, Dollar, Girshick. Segment Anything. ICCV 2023. arXiv:2304.02643.
- verified: arxiv.org/abs/2304.02643 (12 authors, 2023-04-05); openaccess.thecvf.com ICCV2023 Kirillov_Segment_Anything page (conference title ICCV).
- Abstract: "The model is designed and trained to be promptable, so it can transfer zero-shot to new image distributions and tasks." SA-1B: "over 1 billion masks on 11M licensed and privacy respecting images".

[A2] Ravi, Gabeur, Hu, Hu, Ryali, Ma, Khedr, Radle, Rolland, Gustafson, Mintun, Pan, et al. (18 authors). SAM 2: Segment Anything in Images and Videos. ICLR 2025 (oral). arXiv:2408.00714.
- verified: arxiv.org/abs/2408.00714 and arxiv.org/html/2408.00714 (full text grepped). Venue: listing only (proceedings.iclr.cc 2025 PDF and iclr.cc/virtual/2025/oral/31878 seen in search results; Semantic Scholar mislabels the year as 2024).
- SA-V (Sec. 5.2): "The SA-V dataset collected with our data engine comprises 50.9K videos with 642.6K masklets"; abstract of Sec. 1: "35.5M masks across 50.9K videos".
- Limitations (App. C): "The model may fail to segment objects across shot changes and can lose track of or confuse objects in crowded scenes, after long occlusions or in extended videos."
- App. C: "SAM 2 processes each object separately ... without inter-object communication" (motivates SAM 3.1 Object Multiplex).

[A3] Carion, Gustafson, Hu, Debnath, Hu, Suris, Ryali, Alwala, Khedr, Huang, Lei, Ma, et al. (38 authors; last authors Ravi, Saenko, Zhang, Feichtenhofer, Dollar). SAM 3: Segment Anything with Concepts. ICLR 2026. arXiv:2511.16719 (v1 2025-11-20).
- verified: arxiv.org/abs/2511.16719; arxiv.org/html/2511.16719 (full text grepped); proceedings.iclr.cc/paper_files/paper/2026/hash/e0982cbc81401df3430ee1ff780dc7a2-Abstract-Conference.html (opened, lists ICLR 2026 and author list).
- Abstract: concept prompts are "short noun phrases (e.g., 'yellow school bus'), image exemplars, or a combination of both"; "Promptable Concept Segmentation (PCS) ... returns segmentation masks and unique identities for all matching object instances."
- Sec. 1: "To focus on recognizing atomic visual concepts, we constrain text to simple noun phrases (NPs) such as 'red apple' or 'striped cat'." (Directly supports the need for a basic-level noun.)
- App. B Limitations: "SAM 3 struggles to generalize to fine-grained out-of-domain concepts (e.g., aircraft types, medical terms) in a zero-shot manner, especially in niche visual domains"; and "constrained to simple noun phrase prompts".
- Sec. 3: "Our vocabulary includes any simple noun phrase groundable in a visual scene, which makes the task intrinsically ambiguous. There can be multiple interpretations of phrases arising from polysemy ('mouse' device vs. animal)". Also video tracker: detector re-prompts the tracker every N=16 frames with high-confidence detections (App. C.3), and uses "temporal disambiguation" (Sec. 3).
- Data engine (Sec. 4): MLLMs are "AI verifiers that achieve near-human accuracy" for mask verification and exhaustivity verification. This is a published precedent for VLM-as-verifier of SAM outputs.
- Sec. 6 "SAM 3 Agent": "an MLLM that uses SAM 3 as a tool ... The MLLM proposes noun phrase queries to prompt SAM 3 and analyzes the returned masks, iterating until the masks are satisfactory." (Closest published analogue to our noun-proposal + audit loop; evaluated on ReasonSeg and OmniLabel, Table 7, not on counting or ecology.)
- SA-Co benchmark (Sec. 1, HTML as fetched 2026-11-02): "containing 207K unique concepts with exhaustive masks in 120K images and 1.7K videos" (a search snippet quoted 214K/124K, so counts differ between versions; cite the version you use). SA-Co/VEval reports "cgF1 and pHOTA" (Sec. 6).
- Sec. 6 "Object Counting": SAM 3 is compared with MLLMs on CountBench and PixMo-Count; "SAM 3 not only achieves good object counting accuracy, but also provides object segmentation that most MLLMs cannot provide."

[A4] Meta / facebookresearch. SAM 3.1 Object Multiplex release notes. 2026-03-27. github.com/facebookresearch/sam3 (README "Latest updates", RELEASE_SAM3p1.md).
- verified: raw.githubusercontent.com/facebookresearch/sam3/main/README.md and RELEASE_SAM3p1.md opened. Hugging Face card (huggingface.co/facebook/sam3.1) is linked from the README but was NOT opened. No separate Meta blog post was found/opened; cite the GitHub release notes and the SAM 3 paper App. H (Object Multiplex).
- README: "03/27/2026 -- SAM 3.1 Object Multiplex is released. It introduces a shared-memory approach for joint multi-object tracking that is significantly faster without sacrificing accuracy."
- RELEASE_SAM3p1.md: "~7x speedup at 128 objects on a single H100 GPU compared to the SAM 3 November 2025 release"; "Mixed results on SA-Co/VEval video benchmarks, with notable improvement on YT-Temporal-1B (+2.1 cgF1)". So SAM 3.1 is a tracking-efficiency update, not a vocabulary update; the PCS vocabulary limits of SAM 3 apply.

[A5] Ren, Liu, Zeng, Lin, Li, Cao, et al. (17 authors). Grounded SAM: Assembling Open-World Models for Diverse Visual Tasks. arXiv:2401.14159 (2024-01-25). Preprint only.
- verified: arxiv.org/abs/2401.14159.
- Abstract: "uses Grounding DINO as an open-set object detector to combine with the segment anything model (SAM). This integration enables the detection and segmentation of any regions based on arbitrary text inputs."

[A6] Cheng, Oh, Price, Schwing, Lee. Tracking Anything with Decoupled Video Segmentation (DEVA). ICCV 2023. arXiv:2309.03903.
- verified: arxiv.org/abs/2309.03903; openaccess.thecvf.com ICCV2023 Cheng_Tracking_Anything page.
- Abstract: image-level task-specific segmentation plus "class/task-agnostic bi-directional temporal propagation" to avoid video training per task, "especially in large-vocabulary settings".

[A7] Yang, Gao, Li, Gao, Wang, Zheng. Track Anything: Segment Anything Meets Videos. arXiv:2304.11968 (tech report).
- verified: arxiv.org/abs/2304.11968.
- Abstract: "we found that [SAM] performs poorly on consistent segmentation in videos"; proposes SAM plus a tracker with clicks.

---------------------------------------------------------------------
## B. Open-vocabulary detection, vocabulary, granularity, long tail

[B1] Liu, Zeng, Ren, Li, Zhang, Yang, Jiang, Li, Yang, Su, Zhu, Zhang. Grounding DINO: Marrying DINO with Grounded Pre-Training for Open-Set Object Detection. ECCV 2024, LNCS pp. 38-55, doi:10.1007/978-3-031-72970-6_3. arXiv:2303.05499.
- verified: arxiv.org/abs/2303.05499; link.springer.com/chapter/10.1007/978-3-031-72970-6_3 (opened, ECCV, 12 authors). (Springer metadata lists date 2025 for the volume; the proceedings are ECCV 2024.)
- Abstract: "can detect arbitrary objects with human inputs such as category names or referring expressions."

[B2] Minderer, Gritsenko, Stone, Neumann, Weissenborn, Dosovitskiy, Mahendran, Arnab, Dehghani, Shen, Wang, Zhai, et al. Simple Open-Vocabulary Object Detection with Vision Transformers (OWL-ViT). ECCV 2022. arXiv:2205.06230.
- verified: arxiv.org/abs/2205.06230. Venue: listing only (ecva.net eccv_2022 PDF seen in search results).
- Abstract: strong recipe "for transferring image-text models to open-vocabulary object detection", targeted at "the long-tailed and open-vocabulary setting".

[B3] Minderer, Gritsenko, Houlsby. Scaling Open-Vocabulary Object Detection (OWLv2). NeurIPS 2023. arXiv:2306.09683.
- verified: arxiv.org/abs/2306.09683. Venue: listing only (papers.neurips.cc 2023 PDF in search results).
- Abstract: self-training that "uses an existing detector to generate pseudo-box annotations on image-text pairs"; "Major challenges ... are the choice of label space". SAM 3 uses OWLv2 as its main OV-detection baseline (Sec. 1, Fig. 2 caption in the HTML).

[B4] Li, Zhang, Zhang, Yang, Li, Zhong, et al. Grounded Language-Image Pre-training (GLIP). CVPR 2022. arXiv:2112.03857.
- verified: arxiv.org/abs/2112.03857 (comment: "CVPR 2022").
- Abstract: "unifies object detection and phrase grounding for pre-training"; 27M grounding data.

[B5] Zhou, Girdhar, Joulin, Krahenbuhl, Misra. Detecting Twenty-thousand Classes using Image-level Supervision (Detic). ECCV 2022. arXiv:2201.02605.
- verified: arxiv.org/abs/2201.02605 (comment: "ECCV 2022 camera ready").
- Abstract: "expands the vocabulary of detectors to tens of thousands of concepts" by training classifiers on image-classification data.

[B6] Cheng, Song, Ge, Liu, Wang, Shan. YOLO-World: Real-Time Open-Vocabulary Object Detection. CVPR 2024. arXiv:2401.17270.
- verified: arxiv.org/abs/2401.17270; openaccess.thecvf.com CVPR2024 Cheng_YOLO-World page (conference title CVPR).
- Abstract: "reliance on predefined and trained object categories limits their applicability in open scenarios"; adds open-vocabulary detection via region-text contrastive pre-training.

[B7] Gupta, Dollar, Girshick. LVIS: A Dataset for Large Vocabulary Instance Segmentation. CVPR 2019. arXiv:1908.03195.
- verified: arxiv.org/abs/1908.03195; openaccess.thecvf.com CVPR_2019 Gupta_LVIS page.
- Abstract: "over 1000 entry-level object categories"; "Due to the Zipfian distribution of categories in natural images, LVIS naturally has a long tail of categories with few training samples" and "state-of-the-art deep learning methods for object detection perform poorly in the low-sample regime". ("Entry-level" is the vision-community term close to basic-level.)

[B8] Bianchi, Carrara, Messina, Gennaro, Falchi. The devil is in the fine-grained details: Evaluating open-vocabulary object detectors for fine-grained understanding. CVPR 2024 (Highlight). arXiv:2311.17518.
- verified: arxiv.org/abs/2311.17518; openaccess.thecvf.com CVPR2024 Bianchi page.
- Abstract: "most existing solutions, which shine in standard open-vocabulary benchmarks, struggle to accurately capture and distinguish finer object details" (probes colour, pattern, material attributes, not taxonomic granularity).

[B9] Yao, Liu, Zhao, Zhang, Liao, Fang, et al. How to Evaluate the Generalization of Detection? A Benchmark for Comprehensive Open-Vocabulary Detection (OVDEval). AAAI 2024. arXiv:2308.13177.
- verified: arxiv.org/abs/2308.13177 (comment: "Long paper accepted at AAAI 2024").
- Abstract: "existing top OVD models all fail on the new tasks except for simple object types". Supports: OV detectors work for simple object nouns, fail elsewhere.

[B10] Nebbia, Kovashka. Synonym relations affect object detection learned on vision-language data. Findings of NAACL 2024.
- verified: aclanthology.org/2024.findings-naacl.239/ (opened; title, authors, abstract).
- Abstract: "we analyze whether object detectors trained on vision-language data learn effective visual representations for synonyms ... we analyze changes in synonyms used to refer to objects." Closest peer-reviewed study that detection output depends on which word names the object. (The abstract as read does not give numbers; do not quote figures.)

[B11] Parisot, Yang, McDonagh. Learning to Name Classes for Vision and Language Models. CVPR 2023. arXiv:2304.01830.
- verified: arxiv.org/abs/2304.01830 (comment: "Accepted to CVPR 2023").
- Abstract: "high sensitivity to the choice of handcrafted class names that define queries"; can "adjust potentially erroneous, non-descriptive or ambiguous class names"; integrated into detection pipelines. Supports: names that are descriptive ("pink seabream") or ambiguous hurt VL models.

[B12] Huang, Zhang, Jiang, Lu. Open-Vocabulary Object Detection via Language Hierarchy (DetLH). NeurIPS 2024. arXiv:2410.20371.
- verified: arxiv.org/abs/2410.20371 (comment: "NeurIPS 2024 Camera Ready").
- Abstract: "language hierarchical prompt generation that introduces language hierarchy into prompt generation which helps bridge the vocabulary gaps between training and testing" (WordNet hierarchy per the paper body; body not read). Uses hierarchy at training time; does not measure hypernym prompts failing at inference.

[B13] Pratt, Covert, Liu, Farhadi. What does a platypus look like? Generating customized prompts for zero-shot image classification (CuPL). ICCV 2023. arXiv:2209.03320.
- verified: arxiv.org/abs/2209.03320 (comment: "ICCV 2023").
- Abstract: LLM-generated descriptive sentences for each category name improve zero-shot accuracy. Contrast: for SAM-style detectors descriptive phrases are NOT what works (SAM 3 limits itself to simple NPs).

[B14] Menon, Vondrick. Visual Classification via Description from Large Language Models. arXiv:2210.07183 (ICLR 2023 per common citation; venue not read, treat as preprint).
- verified: arxiv.org/abs/2210.07183.
- Abstract: "classification by description": query an LLM for descriptive features rather than only category names.

[B15] Stevens, Wu, Thompson, Campolongo, Song, Carlyn, et al. BioCLIP: A Vision Foundation Model for the Tree of Life. CVPR 2024 (oral). arXiv:2311.18803.
- verified: arxiv.org/abs/2311.18803; openaccess.thecvf.com CVPR2024 Stevens_BioCLIP page.
- Abstract: "learned a hierarchical representation conforming to the tree of life"; shows a taxonomy-aware model for fine-grained biology classification.

[B16] Li, Liu, Li, Zhang, Aneja, Yang, et al. ELEVATER: A Benchmark and Toolkit for Evaluating Language-Augmented Visual Models. NeurIPS 2022 Datasets and Benchmarks. arXiv:2204.08790.
- verified: arxiv.org/abs/2204.08790 (comment: NeurIPS 2022 Datasets and Benchmarks Track).
- Abstract: 20 classification and 35 detection datasets "each ... augmented with external knowledge"; platform for "Computer Vision in the Wild". Useful as the standard cross-domain OV evaluation.

[B17] Kamath, Singh, LeCun, Synnaeve, Misra, Carion. MDETR - Modulated Detection for End-to-End Multi-Modal Understanding. arXiv:2104.12763 (ICCV 2021 per common citation; venue not read). Optional; only cite if the paper discusses grounding lineages (SAM 3 builds on this line).
- verified: arxiv.org/abs/2104.12763 (title/authors only).

---------------------------------------------------------------------
## C. Basic-level categories

[C1] Rosch, Mervis, Gray, Johnson, Boyes-Braem. Basic objects in natural categories. Cognitive Psychology 8(3):382-439, 1976. doi:10.1016/0010-0285(76)90013-X.
- verified: Crossref API record for the DOI (title, journal, five authors, vol 8, pp 382-439, issued 1976-07). The paper text itself was not opened; claims about its content come from [C2].

[C2] Sawyer, Roberts, Moore. Basic Category Usage in Vision Language Models. arXiv:2503.12530 (2025-03-16). Preprint.
- verified: arxiv.org/abs/2503.12530.
- Abstract: "a basic level of categorization that humans use when labeling visual stimuli, a term coined by Rosch in 1976. This level ... has been found to be used most frequently, to have higher information density"; "Llama 3.2 Vision Instruct (11B) and Molmo 7B-D both prefer basic-level categorization consistent with human behavior"; consistent with "the expert basic level shift"; "expert prompting methods demonstrate lower accuracy than non-expert". Only paper found that ties basic-level naming to VLM outputs. It does not test detectors/segmenters (UNVERIFIED that none exists elsewhere; searched twice).

(See also [B7] LVIS "entry-level categories" and [A3] "atomic visual concepts ... simple noun phrases".)

---------------------------------------------------------------------
## D. VLM/LLM as verifier, critic, judge, agent, tool user

[D1] Zheng, Chiang, Sheng, Zhuang, Wu, Zhuang, et al. (13 authors). Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena. NeurIPS 2023 Datasets and Benchmarks. arXiv:2306.05685.
- verified: arxiv.org/abs/2306.05685 (comment: NeurIPS 2023 Datasets and Benchmarks Track).
- Abstract: "We examine the usage and limitations of LLM-as-a-judge, including position, verbosity, and self-enhancement biases, as well as limited reasoning ability".

[D2] Chen, Chen, Zhang, Liu, Wang, Zhou, et al. MLLM-as-a-Judge: Assessing Multimodal LLM-as-a-Judge with Vision-Language Benchmark. ICML 2024 (oral). arXiv:2402.04788.
- verified: arxiv.org/abs/2402.04788 (comment: "ICML 2024 (Oral)").
- Abstract: MLLMs "demonstrate remarkable human-like discernment in Pair Comparison" but there is "a significant divergence from human preferences in Scoring Evaluation and Batch Ranking"; "persistent challenges ... including diverse biases, hallucinatory responses, and inconsistencies in judgment, even in advanced models such as GPT-4V."

[D3] Xiong, Wang, Guo, Ye, Fan, Gu, et al. LLaVA-Critic: Learning to Evaluate Multimodal Models. CVPR 2025. arXiv:2410.02712.
- verified: arxiv.org/abs/2410.02712 (comment: "Accepted by CVPR 2025").
- Abstract: "the first open-source large multimodal model (LMM) designed as a generalist evaluator".

[D4] Madaan, Tandon, Gupta, Hallinan, Gao, Wiegreffe, et al. (16 authors). Self-Refine: Iterative Refinement with Self-Feedback. NeurIPS 2023. arXiv:2303.17651.
- verified: arxiv.org/abs/2303.17651. Venue: listing only (neurips.cc/virtual/2023/poster/71632 seen in search results).
- Abstract: "a single LLM as the generator, refiner, and feedback provider".

[D5] Huang, Chen, Mishra, Zheng, Yu, Song, et al. (7 authors). Large Language Models Cannot Self-Correct Reasoning Yet. ICLR 2024. arXiv:2310.01798.
- verified: arxiv.org/abs/2310.01798 (comment: "ICLR 2024"); (7 authors; first six read from page).
- Abstract: "LLMs struggle to self-correct their responses without external feedback, and at times, their performance even degrades after self-correction." Supports using an external signal (SAM masks, motion evidence, a second unprimed look) rather than pure self-critique.

[D6] Dhuliawala, Komeili, Xu, Raileanu, Li, Celikyilmaz, et al. (7 authors). Chain-of-Verification Reduces Hallucination in Large Language Models. arXiv:2309.11495 (Findings of ACL 2024 per common citation; venue not read, treat as preprint).
- verified: arxiv.org/abs/2309.11495.
- Abstract: the model "answers those questions independently so the answers are not biased by other responses". Direct precedent for our unprimed second look that fixed the anchoring false positive.

[D7] Yin, Fu, Zhao, Xu, Wang, Sui, et al. Woodpecker: Hallucination Correction for Multimodal Large Language Models. Science China Information Sciences, 2024. arXiv:2310.16045.
- verified: arxiv.org/abs/2310.16045 (jref: SCIENCE CHINA Information Sciences, 2024).
- Abstract: training-free, five stages "key concept extraction, question formulation, visual knowledge validation, visual claim generation, and hallucination correction".

[D8] Gupta, Kembhavi. Visual Programming: Compositional Visual Reasoning Without Training (VisProg). CVPR 2023. arXiv:2211.11559.
- verified: arxiv.org/abs/2211.11559; openaccess.thecvf.com CVPR2023 Gupta_Visual_Programming page.
- Abstract: LLM generates programs where "each line ... may invoke one of several off-the-shelf computer vision models, image processing routines, or python functions".

[D9] Suris, Menon, Vondrick. ViperGPT: Visual Inference via Python Execution for Reasoning. ICCV 2023. arXiv:2303.08128.
- verified: arxiv.org/abs/2303.08128; openaccess.thecvf.com ICCV2023 Suris_ViperGPT page.
- Abstract: "leverages code-generation models to compose vision-and-language models into subroutines".

[D10] Lai, Tian, Chen, Li, Yuan, Liu, et al. (7 authors). LISA: Reasoning Segmentation via Large Language Model. CVPR 2024. arXiv:2308.00692.
- verified: arxiv.org/abs/2308.00692; openaccess.thecvf.com CVPR2024 Lai_LISA page.
- Abstract: new task "reasoning segmentation ... output a segmentation mask given a complex and implicit query text"; systems "rely on explicit human instruction or pre-defined categories". (LISA trains the LLM to emit a mask token; ours keeps SAM frozen and uses the VLM only as namer/auditor.)

[D11] Yang, Zhang, Li, Zou, Li, Gao. Set-of-Mark Prompting Unleashes Extraordinary Visual Grounding in GPT-4V. arXiv:2310.11441. Preprint.
- verified: arxiv.org/abs/2310.11441.
- Abstract: use "off-the-shelf interactive segmentation models, such as SEEM/SAM, to partition an image into regions ... and overlay these regions with a set of marks"; the marked image is the VLM input. Direct precedent for SAM-masks-as-marks sheets; ours uses early/middle/late crops.

[D12] Shtedritski, Rupprecht, Vedaldi. What does CLIP know about a red circle? Visual prompt engineering for VLMs. ICCV 2023 (oral). arXiv:2304.06712.
- verified: arxiv.org/abs/2304.06712 (comment: "ICCV 2023 Oral").
- Abstract: "by simply drawing a red circle around an object, we can direct the model's attention to that region, while also maintaining global information." Shows overlays shift VLM behaviour, i.e. sheet layout is part of the prompt.

[D13] Zhang, Khayatkhoei, Chhikara, Ilievski. MLLMs Know Where to Look: Training-free Perception of Small Visual Details with Multimodal LLMs. ICLR 2025. arXiv:2502.17422.
- verified: arxiv.org/abs/2502.17422 (comment: "Published as a conference paper at ICLR 2025").
- Abstract: MLLM performance "is very sensitive to the size of the visual subject of the question" (causal by intervention) and MLLMs "know where to look, even when they provide the wrong answer"; proposes training-free cropping/attention interventions. Supports cropping animals for audit.

---------------------------------------------------------------------
## E. VLM failure modes (hallucination, sycophancy, anchoring, order/context sensitivity, nondeterminism)

[E1] Rohrbach, Hendricks, Burns, Darrell, Saenko. Object Hallucination in Image Captioning. EMNLP 2018. arXiv:1809.02156.
- verified: arxiv.org/abs/1809.02156 (comment: "accepted to EMNLP 2018"). (CHAIR metric.)
- Abstract: models "hallucinating objects that are not actually in a scene"; analyses "when hallucination is likely due to image misclassification or language priors".

[E2] Li, Du, Zhou, Wang, Zhao, Wen. Evaluating Object Hallucination in Large Vision-Language Models (POPE). EMNLP 2023. arXiv:2305.10355.
- verified: arxiv.org/abs/2305.10355 (comment: "Accepted to EMNLP 2023").
- Abstract: "objects that frequently occur in the visual instructions or co-occur with the image objects, are obviously prone to be hallucinated by LVLMs"; "existing evaluation methods might be affected by the input instructions and generation styles". (The first clause concerns instruction data frequency, so it is an analogy for, not a test of, candidate names placed in the audit prompt.)

[E3] Sharma, Tong, Korbak, Duvenaud, Askell, Bowman, et al. (19 authors). Towards Understanding Sycophancy in Language Models. ICLR 2024. arXiv:2310.13548.
- verified: arxiv.org/abs/2310.13548. Venue: listing only (iclr.cc/virtual/2024/poster/17593 seen in search results).
- Abstract: "five state-of-the-art AI assistants consistently exhibit sycophancy"; "when a response matches a user's views, it is more likely to be preferred".

[E4] Li, Ji, Fan, Lu, Yang, Yang, et al. Have the VLMs Lost Confidence? A Study of Sycophancy in VLMs. ICLR 2025. arXiv:2410.11302.
- verified: arxiv.org/abs/2410.11302. Venue: listing only (iclr.cc/virtual/2025/poster/30427 seen in search results).
- Abstract: introduces MM-SY; sycophancy = failing "to adhere to original correct responses, instead blindly agreeing with users' opinions"; "lack of attention to image knowledge in these higher layers may contribute to sycophancy". VLM-specific counterpart of our "adopts the candidate name in the prompt".

[E5] Dang, Gao, Yan, Zou, Gu, Li, et al. Exploring Response Uncertainty in MLLMs: An Empirical Evaluation under Misleading Scenarios. arXiv:2411.02708 (v2/v3 on arXiv; preprint as read).
- verified: arxiv.org/abs/2411.02708.
- Abstract: "twelve state-of-the-art open-source MLLMs overturn a previously correct answer in 65% of cases after receiving a single deceptive cue"; explicit (false-answer hints) and implicit misleading instructions. Strongest quantitative match to "a candidate name in the prompt flips the audit".

[E6] Wang, He, Li, Yang, Xiong, Liu. V-FAT: Benchmarking Visual Fidelity Against Text-bias. arXiv:2601.04897 (2026-01-08). Preprint, recent; treat cautiously.
- verified: arxiv.org/abs/2601.04897 (title, authors; first author Ziteng Wang).
- Abstract: separates "Internal Corpus Bias" from "External Instruction Bias, arising from the alignment-induced tendency toward sycophancy"; 4,026 VQA instances.

[E7] Jones, Steinhardt. Capturing Failures of Large Language Models via Human Cognitive Biases. NeurIPS 2022. arXiv:2202.12299.
- verified: arxiv.org/abs/2202.12299 (comment: "Published at NeurIPS 2022").
- Abstract: Codex "errs predictably based on how the input prompt is framed, adjusts outputs towards anchors, and is biased towards outputs that mimic frequent training examples." (Anchoring on prompt-supplied values, in code generation.)

[E8] Lou, Sun. Anchoring Bias in Large Language Models: An Experimental Study. arXiv:2412.06593 (2024-12-09). Preprint.
- verified: arxiv.org/abs/2412.06593.
- Abstract: "the sensitivity of LLM responses to biased hints"; "simple algorithms such as Chain-of-Thought, Thoughts of Principles, Ignoring Anchor Hints, and Reflection are not sufficient" to mitigate; "one needs to collect hints from comprehensive angles". Supports: telling the model to ignore the candidate does not fix it; removing the candidate (our unprimed look) does.

[E9] Valencia-Clavijo. Anchors in the Machine: Behavioral and Attributional Evidence of Anchoring Bias in LLMs. arXiv:2511.05766 (2025-11-07). Preprint, single author.
- verified: arxiv.org/abs/2511.05766.
- Abstract: "anchors shift entire output distributions"; "Robust anchoring effects in Gemma-2B, Phi-2, and Llama-2-7B"; effects "vary across prompt designs".

[E10] Echterhoff, Liu, Alessa, McAuley, He. Cognitive Bias in Decision-Making with LLMs. arXiv:2403.00811 (Findings of EMNLP 2024 per common citation; venue not read).
- verified: arxiv.org/abs/2403.00811.
- Abstract: BiasBuster, 13,465 prompts covering "prompt-induced, sequential, inherent" biases; self-debiasing by rewriting the prompt.

[E11] Zheng, Zhou, Meng, Zhou, Huang. Large Language Models Are Not Robust Multiple Choice Selectors. ICLR 2024 (Spotlight). arXiv:2309.03882.
- verified: arxiv.org/abs/2309.03882 (comment: "ICLR 2024 Spotlight").
- Abstract: "modern LLMs are vulnerable to option position changes in MCQs due to their inherent 'selection bias'"; debiasing "by permutating option contents".

[E12] Pezeshkpour, Hruschka. Large Language Models Sensitivity to The Order of Options in Multiple-Choice Questions. Findings of NAACL 2024, pp. 2006-2017. arXiv:2308.11483.
- verified: aclanthology.org/2024.findings-naacl.130/ (opened); arxiv.org/abs/2308.11483.
- Abstract: "a considerable performance gap of approximately 13% to 75% in LLMs on different benchmarks, when answer options are reordered".

[E13] Wang, Li, Chen, Cai, Zhu, Lin, Cao, Kong, Liu, Liu, Sui. Large Language Models are not Fair Evaluators. ACL 2024 (long), pp. 9440-9450, doi:10.18653/v1/2024.acl-long.511. arXiv:2305.17926.
- verified: aclanthology.org/2024.acl-long.511/ (opened); arxiv.org/abs/2305.17926.
- Abstract: "the quality ranking of candidate responses can be easily hacked by simply altering their order of appearance in the context"; mitigations include "Balanced Position Calibration, which aggregates results across various orders" and "Human-in-the-Loop Calibration ... seeks human assistance when needed". Direct precedent for permuting sheets and escalating disagreements to a person.

[E14] Tian, Zou, Yang, Zhang. Identifying and Mitigating Position Bias of Multi-image Vision-Language Models. CVPR 2025. arXiv:2503.13792.
- verified: arxiv.org/abs/2503.13792 (comment: "Accepted to CVPR2025").
- Abstract: LVLM "predictions significantly affected by the alteration of image positions"; open-source models "excel in reasoning with images positioned later but underperform with those in the middle or at the beginning, while proprietary models show improved comprehension for images at the beginning and end". Supports early/middle/late crop-position effects.

[E15] Tan, Chu, Li, Mo. Order Matters: Exploring Order Sensitivity in Multimodal Large Language Models. arXiv:2410.16983. Preprint.
- verified: arxiv.org/abs/2410.16983.
- Abstract: "changing the order of multimodal input can cause the model's performance to fluctuate between advanced performance and random guessing", in "single-modality ... and mixed-modality (image-text-pair) contexts".

[E16] Zhao, Wallace, Feng, Klein, Singh. Calibrate Before Use: Improving Few-Shot Performance of Language Models. ICML 2021. arXiv:2102.09690.
- verified: arxiv.org/abs/2102.09690 (comment: "ICML 2021").
- Abstract: "the choice of prompt format, training examples, and even the order of the training examples can cause accuracy to vary from near chance to near state-of-the-art"; bias toward answers "placed near the end of the prompt or ... common in the pre-training data".

[E17] Lu, Bartolo, Moore, Riedel, Stenetorp. Fantastically Ordered Prompts and Where to Find Them. ACL 2022. arXiv:2104.08786.
- verified: arxiv.org/abs/2104.08786 (comment: "ACL 2022").
- Abstract: sample order "can make the difference between near state-of-the-art and random guess performance"; present "across model sizes (even for the largest current models)".

[E18] Sclar, Choi, Tsvetkov, Suhr. Quantifying Language Models' Sensitivity to Spurious Features in Prompt Design or: How I learned to start worrying about prompt formatting. ICLR 2024. arXiv:2310.11324.
- verified: arxiv.org/abs/2310.11324 (comment: "ICLR 2024 Camera Ready").
- Abstract: "performance differences of up to 76 accuracy points" from meaning-preserving formatting changes; "reporting a range of performance across plausible prompt formats".

[E19] Liu, Lin, Hewitt, Paranjape, Bevilacqua, Petroni, et al. (7 authors). Lost in the Middle: How Language Models Use Long Contexts. TACL 2024 (accepted 2023). arXiv:2307.03172.
- verified: arxiv.org/abs/2307.03172 (comment: accepted to TACL).
- Abstract: performance "highest when relevant information occurs at the beginning or end of the input context, and significantly degrades when models must access relevant information in the middle".

[E20] Atil, Aykent, Chittams, Fu, Passonneau, Radcliffe, et al. (13 authors). Non-Determinism of "Deterministic" LLM Settings. arXiv:2408.04667 (2024-08-06). Preprint.
- verified: arxiv.org/abs/2408.04667.
- Abstract: "accuracy variations up to 15% across naturally occurring runs with a gap of best possible performance to worst possible performance up to 70%"; "none of the LLMs consistently delivers repeatable accuracy across all tasks, much less identical output strings."

[E21] He, with others at Thinking Machines. Defeating Nondeterminism in LLM Inference. Blog post (Thinking Machines Lab), 2025-09-10. thinkingmachines.ai/blog/defeating-nondeterminism-in-llm-inference/
- verified: page opened and text grepped. Not peer reviewed; cite as a technical report/blog.
- Body: "even when we adjust the temperature down to 0 ... LLM APIs are still not deterministic in practice"; "we sample 1000 completions at temperature 0 ... we generate 80 unique completions"; cause: "our forward pass lacks 'batch invariance', causing our request's output to depend on the batch size of our forward pass" (so server load changes output).

[E22] Wang, Wei, Schuurmans, Le, Chi, Narang, et al. Self-Consistency Improves Chain of Thought Reasoning in Language Models. ICLR 2023. arXiv:2203.11171.
- verified: arxiv.org/abs/2203.11171 (comment: "Published at ICLR 2023").
- Abstract: "samples a diverse set of reasoning paths ... and then selects the most consistent answer by marginalizing out the sampled reasoning paths." Basis for repeated or permuted audits with majority vote.

---------------------------------------------------------------------
## F. Motion, background subtraction, temporal context (fixed cameras)

[F1] Stauffer, Grimson. Adaptive background mixture models for real-time tracking. CVPR 1999, pp. 246-252. doi:10.1109/CVPR.1999.784637.
- verified: Crossref record (title, authors, proceedings title, pp 246-252; Crossref gives no year field, the DOI and proceedings title are 1999). Content claims not read (abstract not opened).

[F2] Zivkovic. Improved adaptive Gaussian mixture model for background subtraction. ICPR 2004, vol. 2, pp. 28-31. doi:10.1109/ICPR.2004.1333992.
- verified: Crossref record (title, author, proceedings, year 2004, pages). Abstract not opened. (This is the MOG2 reference.)

[F3] Giordano, Palazzo, Spampinato. Fish Detection. In: Fish4Knowledge: Collecting and Analyzing Massive Coral Reef Fish Video Data (Springer, 2016), pp. 103-. doi:10.1007/978-3-319-30208-9_9.
- verified: link.springer.com/chapter/10.1007/978-3-319-30208-9_9 (opened; authors, book, abstract).
- Abstract: "We opted for background modeling-based approaches as they fit better with the underwater domain peculiarities. In particular, kernel density estimation methods ... proved to be the best performing ones"; "a post-processing layer ... able to filter out effectively false detections by using 'real-world' object properties"; low frame rate and resolution. Classic precedent for motion-based fish detection plus a false-positive filter; ours replaces the hand-built filter with a VLM judge.

[F4] Beery, Wu, Rathod, Votel, Huang. Context R-CNN: Long Term Temporal Context for Per-Camera Object Detection. CVPR 2020. arXiv:1912.03538.
- verified: arxiv.org/abs/1912.03538; openaccess.thecvf.com CVPR_2020 Beery Context_R-CNN page.
- Abstract: "In static monitoring cameras ... background objects remain static"; leverages "temporal context from the unlabeled frames of a novel camera".

[F5] Beery, van Horn, Perona. Recognition in Terra Incognita. ECCV 2018. arXiv:1807.04975.
- verified: arxiv.org/abs/1807.04975 (comment: "Accepted to ECCV 2018").
- Abstract: "Camera traps are fixed at one location, hence the background changes little across images"; detectors generalize poorly to new locations.

---------------------------------------------------------------------
## G. Tracking, counting, metrics, human-in-the-loop annotation

[G1] Luiten, Osep, Dendorfer, Torr, Geiger, Leal-Taixe, Leibe. HOTA: A Higher Order Metric for Evaluating Multi-Object Tracking. IJCV 129:548-578, 2021 (online 2020). arXiv:2009.07736. doi:10.1007/s11263-020-01375-2.
- verified: arxiv.org/abs/2009.07736 (jref IJCV 2020); Crossref record (IJCV vol 129, pp 548-578).
- Abstract: HOTA "explicitly balances the effect of performing accurate detection, association and localization into a single unified metric". SAM 3 reports a HOTA variant (pHOTA) on SA-Co/VEval ([A3]).

[G2] Bewley, Ge, Ott, Ramos, Upcroft. Simple Online and Realtime Tracking (SORT). ICIP 2016. arXiv:1602.00763.
- verified: arxiv.org/abs/1602.00763 (comment: "Presented at ICIP 2016").
- Abstract: "detection quality is identified as a key factor influencing tracking performance, where changing the detector can improve tracking by up to 18.9%."

[G3] Zhang, Sun, Jiang, Yu, Weng, Yuan, et al. ByteTrack: Multi-Object Tracking by Associating Every Detection Box. ECCV 2022. arXiv:2110.06864.
- verified: arxiv.org/abs/2110.06864. Venue: listing only (link.springer.com/chapter/10.1007/978-3-031-20047-2_1, LNCS 13682 pp 1-21, seen in search results).
- Abstract: low-score objects "are simply thrown away, which brings non-negligible true object missing and fragmented trajectories"; "For the low score detection boxes, we utilize their similarities with tracklets to recover true objects and filter out the background detections." Analogue of recovering missed animals while rejecting background (our motion-residual seeds).

[G4] Ranjan, Sharma, Nguyen, Hoai. Learning To Count Everything. CVPR 2021. arXiv:2104.08391.
- verified: arxiv.org/abs/2104.08391; openaccess.thecvf.com CVPR2021 Ranjan page.
- Abstract: "count objects from any category given only a few annotated instances"; counting as density regression. Contrast with counting-by-tracking-identity, which gives per-individual evidence for MaxN-type audits.

[G5] Papadopoulos, Uijlings, Keller, Ferrari. We don't need no bounding-boxes: Training object class detectors using only human verification. CVPR 2016. arXiv:1602.08405.
- verified: arxiv.org/abs/1602.08405; openaccess.thecvf.com CVPR 2016 page (title, venue).
- Abstract: "only requires annotators to verify bounding-boxes produced automatically by the learning algorithm". Verification replaces drawing; our VLM takes the verifier role with a human reviewing only disputed items.

[G6] Papadopoulos, Uijlings, Keller, Ferrari. Extreme clicking for efficient object annotation. ICCV 2017. arXiv:1708.02750.
- verified: arxiv.org/abs/1708.02750; openaccess.thecvf.com ICCV 2017 page.
- Abstract: extreme points give "annotation time ... only 7s per box, 5x faster" than drawing boxes (comparison to the 35s for ILSVRC boxes cited in abstract).

[G7] Papadopoulos, Uijlings, Keller, Ferrari. Training object class detectors with click supervision. CVPR 2017. arXiv:1704.06189.
- verified: arxiv.org/abs/1704.06189 (comment: "CVPR 2017"). Title/venue only; abstract not read. Optional.

[G8] Benenson, Popov, Ferrari. Large-scale interactive object segmentation with human annotators. CVPR 2019. arXiv:1903.10830.
- verified: arxiv.org/abs/1903.10830; openaccess.thecvf.com CVPR_2019 page.
- Abstract: "a human annotator and a machine segmentation model collaborate"; annotation campaign producing "masks for 2.5M instances on the OpenImages dataset".

[G9] Kuznetsova, Rom, Alldrin, Uijlings, Krasin, Pont-Tuset, et al. The Open Images Dataset V4. IJCV 128:1956-1981, 2020. arXiv:1811.00982. doi:10.1007/s11263-020-01316-z.
- verified: arxiv.org/abs/1811.00982; Crossref record (IJCV 128, pp 1956-1981).
- Abstract: "9.2M images" with "15.4M bounding boxes for 600 object classes". I read only the abstract's first part, which is about scale; the human-verification protocol details were not read, so cite only for dataset scale.

---------------------------------------------------------------------
## H. Underwater precedent (CV side)

[H1] Kavasidis, Sorrenti, Tomarchio, Giordano, Milazzo, Turco, Cattano, Spampinato. Training-free fish species population monitoring in unconstrained underwater videos. Procedia Computer Science 257:809-, 2025. doi:10.1016/j.procs.2025.03.104.
- verified: iris.unipa.it/handle/10447/692846 (opened; metadata and abstract).
- Abstract: "train-free computational pipeline ... leverages the Segment Anything Model 2 (SAM2) for precise detection and segmentation of fish in unconstrained and cluttered underwater videos recorded by Baited Remote Underwater Video systems (BRUVs)"; "eliminating noise such as bait cages". Closest published SAM-on-BRUV precedent found.

[H2] Zhang, Liu, Huang, Zhang, Wen, Zhou, et al. Underwater Camouflaged Object Tracking Meets Vision-Language SAM2 (UW-COT220, VL-SAM2). CVPR 2025 Workshop on CV4Animals. arXiv:2409.16902.
- verified: arxiv.org/abs/2409.16902 (comment: "Accepted to CVPR 2025 Workshop on CV4Animals").
- Abstract: "Our findings highlight the improvements of SAM2 over SAM"; "vision-language tracking framework called VL-SAM2". A CV4Animals precedent for SAM2 plus language in underwater animal tracking.

[H3] Lian, Li. Evaluation of Segment Anything Model 2: The Role of SAM2 in the Underwater Environment. arXiv:2408.02924. Technical report.
- verified: arxiv.org/abs/2408.02924.
- Abstract: "the performance of SAM2 is extremely dependent on the type of user-provided prompts. When using the ground truth bounding box as prompt, SAM2 performed excellently ... when running in automatic mode, SAM2's ability with point prompts to sense and segment underwater instances is significantly degraded." Supports box-prompt seeding from verified boxes.

[H4] Saleh, Laradji, Konovalov, Bradley, Vazquez, Sheaves. A Realistic Fish-Habitat Dataset to Evaluate Algorithms for Underwater Visual Analysis (DeepFish). Scientific Reports, 2020. arXiv:2008.12603.
- verified: arxiv.org/abs/2008.12603 (comment: "Accepted for Publication in Scientific Reports (Nature) 14 August 2020").
- Abstract: "current datasets for fish analysis tend to focus on the classification task within constrained, plain environments which do not capture the complexity of underwater fish habitats"; ~40 thousand images, 20 habitats.

---------------------------------------------------------------------
## How our observations relate (closest prior finding; agrees / extends / new)

1. SAM 3 returns 0 detections for hypernyms ("animal") and descriptive names ("pink seabream"); "hagfish" fails where "eel" works.
 - Agrees with: SAM 3 constrains prompts to "simple noun phrases" and "atomic visual concepts" ([A3] Sec. 1); "struggles to generalize to fine-grained out-of-domain concepts" ([A3] App. B); OVDEval "all fail ... except for simple object types" ([B9]); synonym sensitivity of OV detectors ([B10]); sensitivity to "handcrafted class names" and "non-descriptive or ambiguous class names" ([B11]); LVIS is built from "entry-level" categories ([B7]).
 - Extends: those are measured on synonyms, attributes, or domain shift. We found no paper that measures hypernym failure ("animal" returning nothing) or the rare-species-to-common-noun fallback ("hagfish" -> "eel") for SAM-class models. [C2] shows VLMs themselves prefer basic-level words, which is the reason a VLM can serve as the translator. Treat the hypernym and hagfish/eel results as NEW empirical observations (our measurement; state the SAM version, 3.1, and prompt strings). Caveat: SAM 3's ontology contains an "animal" top-level category (A3 App. D.2), so say "returned zero detections in our videos" rather than "cannot".

2. VLM auditor adopted a candidate name present in its prompt (anchoring/priming).
 - Agrees with: misleading-cue flips of 65% of correct answers ([E5]); VLM sycophancy toward prompt content ([E4]); alignment-induced external instruction bias ([E6]); anchoring in LLMs including that "Ignoring Anchor Hints" and Reflection do not fix it ([E8]); anchors shifting output distributions ([E9]); Codex "adjusts outputs towards anchors" ([E7]); LVLMs hallucinate objects that appear in instructions ([E2], analogy only).
 - Extends: prior work uses QA, text decisions or code. Ours is a labelled-candidate audit of image crops in a detection pipeline, with a measurable false-positive consequence for counts. The unprimed-second-look fix matches the "answer independently so not biased by other responses" step of CoVe ([D6]) and the failure of in-prompt "ignore the anchor" ([E8]). The pipeline-level result (anchored audit -> inflated count, fixed by an unlabeled look) is NEW as an applied finding; the mechanism is not new.

3. Answers changed with sheet layout and what else was on the sheet (context sensitivity).
 - Agrees with: option-order sensitivity of 13% to 75% ([E12]); selection bias ([E11]); formatting changes up to 76 accuracy points ([E18]); order of few-shot items from near-SOTA to chance ([E16], [E17]); position effects in multi-image VLM inputs ([E14], [E15]); mid-context degradation ([E19]); position bias in judges ([D1], [E13]); cropping/visual-overlay effects on MLLM perception ([D12], [D13]).
 - Extends: tested on audit sheets built from video-track crops, with "what else is on the sheet" (neighbouring tracks, labels) as the manipulated variable. Mitigation precedent: permute and aggregate, escalate disagreement to a human ([E13]); self-consistency voting ([E22]).

4. Nondeterminism.
 - Agrees with: accuracy varies up to 15% across runs of "deterministic" settings ([E20]); 80 unique completions from 1000 samples at temperature 0, caused by batch-size dependence ([E21]).
 - Extends: reported at the level of text accuracy; we report it at the level of per-track keep/reject decisions that change a MaxN count. Recommended practice: log raw responses and request ids, repeat audits, and report disagreement rate.

5. JSON format breaks.
 - No peer-reviewed paper in this list measures it (UNVERIFIED search not done for structured-output failures). Treat as an engineering observation; do not cite it as new science. Note constrained decoding or retry-with-schema as engineering, not literature.

6. Pipeline design relations (not failure modes).
 - VLM verifying SAM masks is published practice in SAM 3's own data engine ([A3] Sec. 4, "AI verifiers"); an MLLM proposing noun phrases for SAM 3 and checking masks is the "SAM 3 Agent" ([A3] Sec. 6). Ours differs by: video-level three-crop audit, peak-frame (MaxN) box verification, overlap-merge judging, and motion-residual seeding; and by a documented list of audit failure modes. Frame claims as "applies this pattern to ecological counting", not as a new agent concept.
 - Motion residual seeding follows classic fixed-camera background modelling for fish ([F3]) and static-camera temporal context ([F4], [F5]); the VLM judge replaces hand-built false-positive filters ([F3]) and is analogous to recovering low-score detections while rejecting background ([G3]).
 - Self-critique alone is unreliable ([D5]); our use of external evidence (masks, motion, a second unprimed look) is consistent with that.
 - Human-in-the-loop framing: verification instead of drawing ([G5], [G6], [G8]); disputed items to a human ([E13] Human-in-the-Loop Calibration).
 - Prior SAM on BRUV ([H1]) and CV4Animals underwater SAM2 work ([H2]) are the nearest domain precedents; SAM2's sensitivity to prompt type underwater ([H3]) motivates box seeding from verified boxes.

---------------------------------------------------------------------
## UNVERIFIED (seen only in search results or not checked; do not cite without opening)

- Vague2Detect: Handling Ambiguous Prompts in Knowledge-Based Open-World Detection, arXiv 2609.09949 (appeared in a search result; not opened). Possibly relevant to vague/hypernym prompts.
- Hsiao et al. 2014 (GMM fish background subtraction), Kavasidis (comparison of background models on underwater footage), Rout et al. 2018 (GMM + Wronskian change detection, Fish4Knowledge): named in a search summary; none opened.
- Kaul et al. 2023 and Jin et al. 2024 (richer descriptions help rare/novel OV classes): named only in a secondary summary.
- MaxN origin. Crossref confirms Priede, Bagley, Smith, Creasey, Merrett (1994), "Scavenging deep demersal fishes of the Porcupine Seabight, north-east Atlantic: observations by baited camera, trap and trawl", J. Mar. Biol. Assoc. UK 74:481-498, doi:10.1017/s0025315400047615, and Cappo, Speare, De'ath (2004), J. Exp. Mar. Biol. Ecol. 302:123-152, doi:10.1016/j.jembe.2003.10.006 exist, but I did NOT verify that either defines MaxN. A search summary attributes the approach to Cappo et al. 2003. Marine side owns this; confirm there.
- Hugging Face model card huggingface.co/facebook/sam3.1 and any Meta blog post on SAM 3.1: not opened.
- Stauffer & Grimson 1999 and Zivkovic 2004: only bibliographic records checked; no content claims verified.
- Rosch et al. 1976: bibliographic record only; content claims rely on [C2].
- Venues given as "listing only" ([A2], [B2], [B3], [D4], [E3], [E4], [G3]) were read from search-result listings of official sites, not from an opened page. Venues for [B14] (ICLR 2023), [B17] (ICCV 2021), [D6] (Findings ACL 2024), [E10] (Findings EMNLP 2024) come from memory/common citation and are NOT verified; use arXiv as the citation or verify first.
- Any paper measuring structured-output (JSON) failures of VLMs, or hypernym-prompt failure of open-vocabulary segmenters: searched briefly, none found; absence is not proven.
- Counting-by-tracking literature specific to fish (beyond DeepFish [H4] and [H1]): not searched in depth.
