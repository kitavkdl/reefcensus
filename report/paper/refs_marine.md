# Marine / ecology references for Related Work + Introduction

Compiled 2026-11-02. Scope: marine/ecology side only.

## How "verified" is used here (read first)

- **[A]** = I opened the paper page or the full-text PDF/HTML and read the passage cited. Location is given.
- **[B]** = I confirmed the bibliographic record (authors/venue/volume/pages/DOI) and abstract from a DOI-registry record (Crossref via fetch, or the OpenAlex record), but did NOT read the paper text. Only abstract-level claims are listed. The publisher page was blocked (403), paywalled, or the claim does not need more.
- Anything I could not confirm is in the UNVERIFIED section at the bottom.
- My fetch tool paraphrases pages; where I give "quote" it is a short verbatim string I then re-checked in a locally saved copy of the page text (marked "re-checked locally") or it comes from the abstract text in the record. Where I only have a paraphrase, it says "paraphrase".
- Local copies (page text, PDFs) are in `/tmp/claude-1000/-home-jiyul-git-ops/308fdf48-0205-43de-ae39-91e034b22d52/scratchpad/dl/`.

## Corrections to assumptions in the brief (important)

1. **Lopez-Marcano et al. 2021 tracks yellowfin bream, not luderick.** (Abstract: bream *Acanthopagrus australis* tracked with MOSSE, Seq-NMS, SiamMask.) Do not describe it as "luderick tracking".
2. **Barord et al. 2014 does not use MaxN.** The word "MaxN" does not appear in the article text (searched the full HTML: 0 hits for "MaxN", "maximum number"). They count individual nautiluses by photo-ID (Hotspotter) and divide by an estimated sampled area. So MaxN is *our* metric imposed on their clips, not theirs. Their four supplementary videos are S1-S4 (Methods/Results text: "From the video footage (see Video S1, S2, S3, and S4)"), which matches the "4 nautilus clips".
3. **The Ditria luderick dataset is an image dataset (4,281 images, 9,429 annotations; 9,304 luderick + 125 bream), not a count of videos.** The dataset paper says the images come from "18 individual camera deployments". It does not give a video count. Check the PANGAEA archive (3.4 GB) for raw video before saying "N videos".
4. **MaxN origin.** Langlois 2020 attributes the MaxN definition to Priede et al. 1994 (read directly). Ellis & DeMartini 1995 define the same idea as "MAXNO" for baited video (read directly). I did not read Priede 1994 itself (Crossref abstract is about arrival time at baits), so do not claim Priede 1994 "defines MaxN" in your own voice; write "MaxN (Priede et al. 1994; see Langlois et al. 2020)".
5. **SharkTrack speed claim.** I read the arXiv v3 abstract verbatim (see ref 18). It contains a "two minutes of manual classification per hour of video / estimated 95% reduction" statement. Per your instruction I do not reuse it. Note the numbers are the authors' own estimate, from their abstract.
6. **"Schobernd et al. 2014"**: the Crossref record gives CJFAS 71:464-471, year 2014. Langlois 2020 cites the same paper as "2013" (online-first). Use 2014 (print) and be consistent.
7. **Whitmarsh et al. "2017"**: Crossref/OpenAlex list year 2016 (online) for Rev Fish Biol Fisheries 27:53-73. Langlois and Connolly cite it as 2017 (print volume year). Pick one convention.
8. The marine-specific "SAM"/foundation-model landscape I found: CoralSCOP (CVPR 2024), Dual-SAM (CVPR 2024), UW-VOS/SAM-U (arXiv Mar 2026), a SAM2+CUTIE annotation tool in Sánchez et al. 2026 (Sci Data), MarineGPT (arXiv 2023). "FishSAM" and "MarineSAM": my searches did not return a paper by those names, so I list them as not found (not as non-existent). MarineInst (ECCV 2024) exists as a DOI record but I could not open it (see UNVERIFIED).

---

# VERIFIED REFERENCES

## 1. MaxN / BRUV methodology

### 1. Langlois et al. 2020 [A]
Langlois, T., Goetze, J., Bond, T., Monk, J., Abesamis, R.A., Asher, J., Barrett, N., Bernard, A.T.F., Bouchet, P.J., Birt, M.J., Cappo, M., Currey-Randall, L.M., Driessen, D., Fairclough, D.V., Fullwood, L.A.F., Gibbons, B.A., Harasti, D., Heupel, M.R., Hicks, J., Holmes, T.H., Huveneers, C., Ierodiaconou, D., Jordan, A., Knott, N.A., Lindfield, S., Malcolm, H.A., McLean, D., Meekan, M., Miller, D., Mitchell, P.J., Newman, S.J., Radford, B., Rolim, F.A., Saunders, B.J., Stowar, M., Smith, A.N.H., Travers, M.J., Wakefield, C.B., Whitmarsh, S.K., Williams, J., Harvey, E.S. (2020). A field and video annotation guide for baited remote underwater stereo-video surveys of demersal fish assemblages. *Methods in Ecology and Evolution* 11(11): 1401-1409. DOI 10.1111/2041-210X.13470. Open access (CC BY).
- verified: read the full-text PDF from the JCU repository (https://researchonline.jcu.edu.au/79976/1/79976.pdf, found via the OpenAlex record), plus Crossref record. Section numbers below are from that PDF.
- Usable claims:
  - Sec. 2.6.3 "Abundance estimates": "The standard metric of abundance is MaxN, the maximum number of individuals of a given species present in a single video frame (Priede, Bagley, Smith, Creasey, & Merrett, 1994)." (verbatim, re-checked locally). Also: MaxN "is widely used for BRUVs (Whitmarsh et al., 2017), as it is conservative and ensures that no individual is counted more than once (Schobernd et al., 2013)."
  - Same section: "We recommend all fish be identified to the lowest taxonomic level possible." Unidentified individuals get placeholder names (Genus sp 1-10) for later batch renaming (Sec. 2.6.6). This is the manual standard an automated system must meet: a full assemblage, not one target species.
  - Sec. 2.6.1 (annotation software): "Manual image annotation and measurement can be time consuming, but the emerging field of automated image annotation provides promise of increased cost efficiency and collection of novel metrics (Marini et al., 2018)." (verbatim, re-checked). No numeric time/cost figure in this paper.
  - Sec. 2.6.7 (QC): a second annotator checks MaxN and lengths; a senior analyst reviews "a random review of 10% of annotated videos"; "If accuracy is below 95% for all identifications and estimates of MaxN, reannotation should be undertaken." (paraphrase of the bullet list; the 10% / 95% numbers are verbatim). Useful as the human-QA benchmark that a review queue should be compared against.
  - Sec. 2.6.3: MaxN annotations "may be updated when individual fish are more clearly visible", with length measured "at the last MaxN annotated" (paraphrase). Supports the idea that the MaxN frame is the unit of record.

### 2. Ellis & DeMartini 1995 [A]
Ellis, D.M. and DeMartini, E.E. (1995). Evaluation of a video camera technique for indexing abundances of juvenile pink snapper, *Pristipomoides filamentosus*, and other Hawaiian insular shelf fishes. *Fishery Bulletin* 93(1): 67-77. (No DOI found.) PDF: https://spo.nmfs.noaa.gov/sites/default/files/pdf-content/1995/931/ellis.pdf
- verified: downloaded the scanned PDF (has an OCR text layer); extracted text with pypdf and read the Abstract, Methods and Discussion.
- Usable claims:
  - Methods: "The MAXNO index was determined as the peak number of a species visible at any one time (maximum interval one second) during a deployment." (re-checked locally). This is an early formal definition of the MaxN idea in a baited-video fishery index.
  - Abstract: video MAXNO (natural-log mean of three camera drops) correlated with log longline CPUE, r = 0.79, P < 0.001, n = 15 (verbatim numbers). Study at 39 stations off Oahu/Maui/Kauai, 1992, plus 18 stations in 1993.
  - Discussion (p. 75): earlier deep-sea baited-camera studies found that time of first arrival tracked density while "the maximum number of fish seen at a station (MAXNO) either was unrelated or inversely related to densities" (re-checked locally). An early caution that max-count indices are not trivially tied to abundance. Methods also say the camera sequences were scored for three indices (MAXNO, time to first appearance, total duration).

### 3. Priede et al. 1994 [B]
Priede, I.G., Bagley, P.M., Smith, A., Creasey, S., Merrett, N.R. (1994). Scavenging deep demersal fishes of the Porcupine Seabight, north-east Atlantic: observations by baited camera, trap and trawl. *Journal of the Marine Biological Association of the UK* 74(3): 481-498. DOI 10.1017/S0025315400047615.
- verified: Crossref record (title, authors, volume, pages, DOI, abstract). Also seen as a reference in Langlois 2020's list, which cites it for MaxN. Paper text not read.
- Usable claims:
  - Cited by Langlois et al. 2020 as the source of the MaxN definition (see ref 1).
  - Abstract (paraphrase): 71 species trawled, only 18 approached baits; arrival time of the first fish at baits can estimate population density. Shows that baited cameras see only a subset of the community that a trawl sees (selectivity of bait).

### 4. Schobernd, Bacheler & Conn 2014 [B]
Schobernd, Z.H., Bacheler, N.M., Conn, P.B. (2014). Examining the utility of alternative video monitoring metrics for indexing reef fish abundance. *Canadian Journal of Fisheries and Aquatic Sciences* 71(3): 464-471. DOI 10.1139/cjfas-2013-0086.
- verified: Crossref record with abstract; the paper is also cited in Langlois 2020 (read).
- Usable claims (abstract-level): compares MaxN and MeanCount using simulation, lab experiment and field data; "MaxN was nonlinearly related to true abundance" (verbatim fragment from the record) and tends to saturate as abundance rises; MeanCount was generally linear with similar variability.

### 5. Campbell et al. 2015 [B, metadata only]
Campbell, M.D., Pollack, A.G., Gledhill, C.T., Switzer, T.S., DeVries, D.A. (2015). Comparison of relative abundance indices calculated from two methods of generating video count data. *Fisheries Research* 170: 125-133. DOI 10.1016/j.fishres.2015.05.011.
- verified: Crossref record (title/authors/venue/volume/pages/DOI). The abstract was not in the record and the Elsevier page would not load, so I make no claim about its content beyond the title (it compares two ways of generating video count data / indices).

### 6. Whitmarsh, Fairweather & Huveneers 2017 [B]
Whitmarsh, S.K., Fairweather, P.G., Huveneers, C. (2017; online 2016). What is Big BRUVver up to? Methods and uses of baited underwater video. *Reviews in Fish Biology and Fisheries* 27: 53-73. DOI 10.1007/s11160-016-9450-1.
- verified: Crossref and OpenAlex records (no abstract in either). Cited by Langlois 2020 ("MaxN is widely used for BRUVs") and by Connolly 2021 ("A single MaxN per video is the most commonly reported metric (Whitmarsh et al., 2017)", Intro, re-checked locally).
- Usable claim: standard review of BRUV methods and uses; the supporting citation for "MaxN is the most common BRUV metric". Do not attribute any specific number to it.

### 7. Kilfoil, Campbell, Heithaus & Zhang 2021 [A, abstract page]
Kilfoil, J.P., Campbell, M.D., Heithaus, M.R., Zhang, Y. (2021). The influence of shark behavior and environmental conditions on baited remote underwater video survey results. *Ecological Modelling* 447: 109507, doi:10.1016/j.ecolmodel.2021.109507 (DOI read from the IDEAS page 11/2; Elsevier article numbers equal the DOI suffix). IDEAS page: https://ideas.repec.org/a/eee/ecomod/v447y2021ics0304380021000788.html
- verified: opened the IDEAS/RePEc abstract page and read the abstract (journal volume/year from the URL and page header; DOI not read).
- Usable claim: individual-based simulation of a 60-min BRUV targeting elasmobranchs finds that "density as well as non-density-related factors were highly significant in predicting camera counts, regardless of the camera's FOV or count metric used" (abstract; MaxN and MeanCount both affected by swimming speed, bait attraction, plume size, visibility). A recent critique of MaxN/MeanCount as density indices.

### 8. Hsu et al. 2025 [B]
Hsu, T.-H.T., Gordon, S.E., Ferrari, R., Hoey, A.S., Figueira, W.F. (2025). Optimizing remote underwater video sampling to quantify relative abundance, richness, and corallivory rates of reef fish. *Coral Reefs* 44(2): 435-449. DOI 10.1007/s00338-024-02613-6.
- verified: OpenAlex record with abstract.
- Usable claims (abstract): "analyzing them is time-consuming"; subsampling 40 frames per 60-min video gave accurate MeanCount, but "underestimated species richness by ~40%, missing the less common species". Evidence that cutting annotation effort by subsampling loses rare taxa (a cost of the shortcuts people already use).

### 9. Barord et al. 2014 [A]
Barord, G.J., Dooley, F., Dunstan, A., Ilano, A., Keister, K.N., Neumeister, H., Preuss, T., Schoepfer, S., Ward, P.D. (2014). Comparative population assessments of *Nautilus* sp. in the Philippines, Australia, Fiji, and American Samoa using baited remote underwater video systems. *PLoS ONE* 9(6): e100799. DOI 10.1371/journal.pone.0100799. CC BY. (Correction: PLoS ONE 9(9): e107836.)
- verified: opened the PLOS article page, read abstract, Methods, Data Analysis, Results, supplementary captions (page text saved and grepped).
- Usable claims:
  - Abstract: BRUVS used at sites in the Philippines, American Samoa, Fiji and a ~125 km Great Barrier Reef transect (Cairns to Lizard Island); "The BRUVS proved to be a valuable tool to measure Nautilus abundance in the deep sea (300-400 m)". Significantly fewer nautiluses at the fished Philippines site (6 total, 0.25 per km, vs 93 / 20 / 22 elsewhere).
  - Methods: "Each BRUVS recorded up to 12 hours of video footage"; deployed at dusk (~1800 h) and retrieved ~0600 h; average soak 12 h; chicken bait (tuna/mackerel substitutes in Fiji and American Samoa); three units 1 km apart in Australia pooled as one sample.
  - Data Analysis: "Each of the videos was reviewed and individual nautiluses were identified by their unique color pattern using ... Hotspotter"; "The total number of nautiluses was recorded from each of the videos." No MaxN (0 hits in text).
  - Supplementary Video S4 caption: the BRUVS "record one Nautilus attracted to our bait as well as other species that co-exist with Nautilus, such as the hagfish and shrimps." Direct evidence that nautilus clips contain untargeted taxa (hagfish, shrimp).
  - Species are given only as "*Nautilus* sp." in the title and abstract.

### 10. IMAS curated MPA video highlights (dataset record) [A for the record; authorship UNVERIFIED]
"Curated underwater video highlights of marine protected areas (IMAS, UWA & collaborators)". Australian Ocean Data Network record on data.gov.au, created/updated 24/06/2025. Landing page: https://data.gov.au/data/dataset/b75639f4-c6d8-4a52-b633-988d6ba8a247 (also reachable as .../curated-underwater-video-highlights-of-marine-protected-areas-imas-uwa-collaborators). Contact point listed: jacquomo.monk@utas.edu.au.
- verified: opened the dataset page and two resource pages (WMS layer; "Browse & download media files (IMAS only)", source https://data.imas.utas.edu.au/attachments/UW_curated_video).
- Usable claims (paraphrase of the description): a national compilation of video clips "predominantly derived from underwater video sampling techniques (e.g. BRUV, Stereo-BOSS) for quantitative sampling of abundance, body size, and diversity of demersal fishes"; contributors IMAS, UWA, Geoscience Australia and the NESP Marine Biodiversity & Marine and Coastal Hubs; "As of August 2024" it covers footage in/around 28 named Australian Marine Parks plus Bathurst Channel (Port Davey).
- Caveats: the page lists **License: Not Specified** for the dataset and resources (the data.gov.au site-wide CC BY 4.0 footer is about the portal, not this dataset; do not claim CC BY). The page does **not** name "Monk, Barrett, Langlois" or a 2024 year; I could not find a citation string with those authors (see UNVERIFIED). Cite by title, publisher (IMAS/UTAS via AODN) and the record URL with access date until the authors confirm the preferred citation.

## 2. Automated fish detection / counting in underwater video

### 11. Ditria et al. 2020 (Frontiers) [A]
Ditria, E.M., Lopez-Marcano, S., Sievers, M., Jinks, E.L., Brown, C.J., Connolly, R.M. (2020). Automating the analysis of fish abundance using object detection: optimizing animal ecology with deep learning. *Frontiers in Marine Science* 7: 429. DOI 10.3389/fmars.2020.00429. CC BY 4.0 article.
- verified: opened the full text on frontiersin.org (page text saved and grepped for every number below).
- Usable claims:
  - Abstract: Mask R-CNN models for luderick (*Girella tricuspidata*) trained on "a total of 6,080 annotations"; F1 = 92.4% / mAP50 = 92.5% on unseen footage from the same estuary and F1 = 92.3% / mAP50 = 93.4% on novel footage from a different estuary; computer was "7.1% better than human marine experts and 13.4% better than citizen scientists" on single images and "1.5 and 7.8% higher in video datasets".
  - Results/Table 1 (video test, N = 31 videos): computer F1 86.8% vs expert 85.3% and citizen scientist 79.0%; computer had the lowest false-positive rate but the highest false-negative rate in the video test (24.3 vs 12.1 expert; text and Table 1). Speed: computer 1.2 min per minute of video vs 2.8 (expert) and 2.4 (citizen); 0.4 s per image vs 14.3 and 12.6 s. Text: "In our setup, inference time for video footage by the computer was about half that of humans." Note this is a *modest* speedup, not orders of magnitude.
  - Performance Curve section: "the average time for an operator to annotate one fish was 13.5 s, and the total time to annotate all 6,080 images was in the order of 23 h (not including breaks)." (Note the abstract says 6,080 annotations; this sentence says images. The paper is inconsistent; avoid repeating either as the dataset size, use the dataset paper's 4,281 images / 9,429 annotations.)
  - Methods: humans were asked to "estimate the MaxN of luderick in any single frame per video", "simulating the most popular manual method currently used in analyzing videos"; MaxN is the abundance metric scored with F1. Single target species; footage from six action cameras deployed for 1 h per sampling day in the Tweed River Estuary, Feb-Jul 2019.
  - Data availability statement: data available on request (the later dataset paper, ref 12, put the data on PANGAEA).

### 12. Ditria et al. 2021 (dataset paper) and PANGAEA archive [A]
Ditria, E.M., Connolly, R.M., Jinks, E.L., Lopez-Marcano, S. (2021). Annotated video footage for automated identification and counting of fish in unconstrained seagrass habitats. *Frontiers in Marine Science* 8: 629485 (Data Report, published 3 March 2021). DOI 10.3389/fmars.2021.629485.
Dataset: Ditria, E.M., Connolly, R.M., Jinks, E.L., Lopez-Marcano, S. (2021). Annotated video footage for automated identification and counting of fish in unconstrained marine environments. PANGAEA. DOI 10.1594/PANGAEA.926930. License CC BY 4.0. Size 3.4 GB. (Title differs slightly between the paper and the PANGAEA record: "seagrass habitats" vs "marine environments".)
- verified: opened the Frontiers data report (full text saved, grepped) and the PANGAEA landing page (license, citation, size).
- Usable claims:
  - Dataset section: "The dataset consists of 4,281 images and 9,429 annotations (9,304 luderick, 125 bream)" at 1920 x 1080, from "18 individual camera deployments"; videos "manually trimmed for training to contain only footage of luderick" and "split evenly into 5 frames per second for manual annotation".
  - Data Presentation: annotations as bounding boxes [x, y, width, height] and polygon segmentation masks, in CSV and COCO JSON; three sub-datasets "allocated for suggested training, test and novel test purposes"; images in a ZIP; metadata in dataset_images.csv; ED and volunteers annotated.
  - Footage: submerged Haldex Sports Action Cam HD 1080p cameras, Tweed River estuary (Feb-Jul 2019) and Tallebudgera Creek, SE Queensland; six cameras deployed 1 h per sampling day.
  - Not stated: number of videos; whether the raw (untrimmed) videos are in the archive. Check before reporting a video count.

### 13. Ditria et al. 2020 (multiple habitats) [B]
Ditria, E.M., Sievers, M., Lopez-Marcano, S., Jinks, E.L., Connolly, R.M. (2020). Deep learning for automated analysis of fish abundance: the benefits of training across multiple habitats. *Environmental Monitoring and Assessment* 192(11): 698. DOI 10.1007/s10661-020-08653-z. (bioRxiv preprint 10.1101/2020.05.19.105056.)
- verified: OpenAlex record (journal/volume/issue/article number/DOI); the abstract was read from the Crossref record of the bioRxiv preprint (paraphrase only).
- Usable claim (paraphrase of the preprint abstract): three detectors for luderick trained on seagrass, reef, or both; each did well in its own habitat and poorly in the other; the combined-habitat model performed best, and MaxN estimates showed the same pattern. Evidence that single-species detectors transfer poorly across habitats.

### 14. Lopez-Marcano et al. 2021 [B]
Lopez-Marcano, S., Jinks, E.L., Buelow, C.A., Brown, C.J., Wang, D., Kusy, B., Ditria, E.M., Connolly, R.M. (2021). Automatic detection of fish and tracking of movement for ecology. *Ecology and Evolution* 11(12): 8254-8263. DOI 10.1002/ece3.7656.
- verified: Europe PMC record with abstract.
- Usable claims (paraphrase of abstract): object detection + tracking pipeline for **yellowfin bream** in field video from a known movement passageway; three trackers compared (MOSSE, Seq-NMS, SiamMask); detector F1 = 91% in a multispecies assemblage; Seq-NMS tracking accuracy 84%, MOSSE and SiamMask 78%. Closed-set detector plus classical/lightweight trackers, no vision-language component.

### 15. Connolly et al. 2021 [A]
Connolly, R.M., Fairclough, D.V., Jinks, E.L., Ditria, E.M., Jackson, G., Lopez-Marcano, S., Olds, A.D., Jinks, K.I. (2021). Improved accuracy for automated counting of a fish in baited underwater videos for stock assessment. *Frontiers in Marine Science* 8: 658135 (published 12 Oct 2021). DOI 10.3389/fmars.2021.658135.
- verified: opened the Frontiers full text (saved; grepped).
- Usable claims:
  - Abstract: "The potential for BRUVS-based monitoring is restricted, however, by the substantial costs of manual data extraction from videos" (verbatim, re-checked). The paper does not give a numeric time/cost figure.
  - Intro: "The most common measure of fish abundance derived from underwater videos is the maximum count of a target species in any one frame (MaxN)" with a single MaxN per video most commonly reported (Whitmarsh 2017); multiple MaxN over short intervals recommended as more reliable (Schobernd 2014) (re-checked).
  - Data: BRUVS off Shark Bay, WA (July 2019), six sites, 1 h deployments, 1 kg pilchard bait; Australasian snapper *Chrysophrys auratus*; train/val on three sites (4,690 annotations), test on three independent sites (3,627 annotations); brown-stripe and stripey snapper annotated as lookalike negatives.
  - Method/result: Faster R-CNN (ResNet50) + Seq-NMS; raw model over-predicted at high density (>15 fish per frame) through double/triple detections, "off by as much as 50%"; best procedure (Seq-NMS, 45% threshold, cubic correction) R^2 = 88% vs manual counts. Full-hour MaxN model vs manual: Site 2, 25 vs 30; Site 4, 8 vs 7; Site 6, 1 vs 1. (From my fetch summary of Results; counts re-checked only partially, so treat the 25/30 etc. as paraphrase.) Relevance: a single-frame count (MaxN) inherits any duplicate-detection error in that frame, which motivates checking the frame that sets MaxN.

### 16. Marrable et al. 2022 [A]
Marrable, D., Barker, K., Tippaya, S., Wyatt, M., Bainbridge, S., Stowar, M., Larke, J. (2022). Accelerating species recognition and labelling of fish from underwater video with machine-assisted deep learning. *Frontiers in Marine Science* 9: 944582 (published 2 Aug 2022). DOI 10.3389/fmars.2022.944582.
- verified: opened the Frontiers full text (saved; grepped each quote below).
- Usable claims:
  - Sec. 1 (cost): "BRUVS video analysis ... is a time-consuming and expensive process, typically taking several hours per hour of video (Francour et al., 1999). The Australian Institute of Marine Science (AIMS), a major user of BRUVS, estimates that 4,000 h of video from BRUVS are collected annually in Australia alone, taking approximately 12,000 h of highly trained analysts to manually extract usable fish diversity and abundance data." (verbatim, re-checked locally). The 12,000 h figure is an AIMS estimate quoted by the authors, not a measurement in the paper.
  - Sec. 4 (Discussion): "it takes approximately 10 s to draw and adjust the bounding box around a single fish" vs "less than 1 s for a point measurement" (re-checked) -- why BRUVS labels are points, not boxes.
  - Sec. 1.4: the OzFish dataset has boxes + species "only for the MaxN objects"; "MaxN is therefore unsuitable for DL dataset generation which requires every object ... to be labelled" (re-checked).
  - Abstract: machine-assisted pipeline with up to 12 target species plus a catch-all "fish" class; recall 0.70-0.89 on out-of-sample data; species-level F1 = 0.79; "On average, 12% of fish were given a bounding box with species labels and 88% of fish were located and given a fish label and identified for manual labelling." "Manual labelling and classification effort is still required." Closed-set (12 species) and still human-labelled for the rest.
  - Speed (paraphrase from my fetch, not re-checked): about 500 ms per image, about 15 minutes to process one hour of 30 fps video.
  - Sources: OzFish dataset (AIMS 2019), 1,751 images with point labels used; YOLOv5 detector.

### 17. Marrable et al. 2023 [B]
Marrable, D., Tippaya, S., Barker, K., Harvey, E.S., Bierwagen, S.L., Wyatt, M., Bainbridge, S., Stowar, M. (2023). Generalised deep learning model for semi-automated length measurement of fish in stereo-BRUVS. *Frontiers in Marine Science* 10: 1171625. DOI 10.3389/fmars.2023.1171625.
- verified: OpenAlex record with abstract.
- Usable claim (abstract): stereo-BRUVS are "widely used as a non-invasive, stressless method for manually counting and measuring fish"; the paper applies deep learning to semi-automate the manual head/tail length task. Shows the "semi-automated, human completes" pattern in BRUVS.

### 18. SharkTrack (Varini et al.) [A]
Varini, F., Gayford, J.H., Jenrette, J., Witt, M.J., Garzon, F., Ferretti, F., Wilday, S., Bond, M.E., Heithaus, M.R., Robinson, D., Carter, D., Gumbs, N., Webster, V., Glocker, B. SharkTrack: an accurate, generalisable software for streamlining shark and ray underwater video analysis.
- arXiv:2407.20623 (cs.CV), v1 30 Jul 2024, v3 1 Oct 2024, CC BY 4.0. DOI 10.48550/arXiv.2407.20623.
- Journal version: *Ecological Informatics* 95: 103713 (published 1 May 2026). DOI 10.1016/j.ecoinf.2026.103713.
- verified: opened arXiv abs page v3 (read the abstract text verbatim via the page HTML) and the FIU Discovery record for the journal version (volume, year, DOI, abstract). Journal PDF not read.
- Usable claims (abstract, verbatim from arXiv v3):
  - "SharkTrack uses Convolutional Neural Networks (CNN) and Multi-Object Tracking to automatically detect and track elasmobranchs and provides an annotation pipeline to manually classify elasmobranch species and compute species-specific MaxN (ssMaxN), the standard metric of relative abundance."
  - "When tested on BRUVS footage from locations unseen by the CNN model during training, SharkTrack computed ssMaxN with 89% accuracy over 207 hours of footage."
  - The abstract also states "two minutes of manual classification per hour of video" and "an estimated 95% reduction of manual analysis time". Per your instruction I recommend NOT repeating this; it is the authors' own estimate. (The preprint also said, per a search snippet I did not open, a different reduction in v1; I did not verify v1 vs v3 wording.)
  - Scope is elasmobranchs only ("sharks and rays"); the user classifies species manually after tracking. Closest prior art to this work for BRUV + tracking + MaxN.

### 19. DeepFish (Saleh et al. 2020) [B]
Saleh, A., Laradji, I.H., Konovalov, D.A., Bradley, M., Vazquez, D., Sheaves, M. (2020). A realistic fish-habitat dataset to evaluate algorithms for underwater visual analysis. *Scientific Reports* 10: 14671. DOI 10.1038/s41598-020-71639-x.
- verified: OpenAlex record with full abstract.
- Usable claims (abstract): "approximately 40 thousand images collected underwater from 20 habitats in the marine-environments of tropical Australia"; originally classification labels only, then point-level and segmentation labels added to support "fish count, identify their locations, and estimate their sizes"; models pre-trained on ImageNet performed well but "there is still room for improvement". Used as out-of-sample test images by Marrable 2022.

### 20. Fish4Knowledge (Fisher et al. 2016) [B, record only]
Fisher, R.B., Chen-Burger, Y.-H., Giordano, D., Hardman, L., Lin, F.-P. (eds.) (2016). *Fish4Knowledge: Collecting and Analyzing Massive Coral Reef Fish Video Data.* Intelligent Systems Reference Library 104, Springer. DOI 10.1007/978-3-319-30208-9.
- verified: OpenAlex record (title, editors, year, DOI). I did not open the book. Volume number "104" is from memory and NOT verified: omit it if you cannot confirm.
- Usable claim: the repository from which the Complex Scenes dataset used by Salman 2020 (ref 22) was extracted (Salman abstract: "two benchmark datasets extracted from a large Fish4Knowledge underwater video repository"). Make no other claim.

### 21. FishNet (Khan et al. 2023) [B]
Khan, F.F., Li, X., Temple, A.J., Elhoseiny, M. (2023). FishNet: a large-scale dataset and benchmark for fish recognition, detection, and functional trait prediction. *ICCV 2023*, pp. 20439-20449. DOI 10.1109/ICCV51070.2023.01874.
- verified: OpenAlex record with abstract.
- Usable claims (abstract): "94,532 meticulously organized images from 17,357 aquatic species" with three benchmarks (classification, detection, functional trait prediction). Mostly specimen-style images, not BRUV video (inference from the abstract's "images ... organized according to aquatic biological taxonomy"; I did not open the dataset).

### 22. Salman et al. 2020 [B]
Salman, A., Siddiqui, S.A., Shafait, F., Mian, A., Shortis, M.R., Khurshid, K., Ulges, A., Schwanecke, U. (2020; online 2019). Automatic fish detection in underwater videos by a deep neural network-based hybrid motion learning system. *ICES Journal of Marine Science* 77(4): 1295-1307. DOI 10.1093/icesjms/fsz025.
- verified: OpenAlex record with full abstract (publisher page returned 403).
- Usable claims (abstract): detector for "freely moving fish in unconstrained underwater environments" using R-CNN; "a novel approach to utilize motion information of fish in videos via background subtraction and optical flow, and subsequently combine the outcomes with the raw image to generate fish-dependent candidate regions"; F-score 87.44% (Complex Scenes) and 80.02% (LifeCLEF 2015), both extracted from Fish4Knowledge. Closest ecology precedent for motion cues feeding candidate regions, but used to train a closed-set detector, not to prompt a promptable segmenter.

### 23. Jalal et al. 2020 [B, title only]
Jalal, A., Salman, A., Mian, A., Shortis, M., Shafait, F. (2020). Fish detection and species classification in underwater environments using deep learning with temporal information. *Ecological Informatics* 57: 101088. DOI 10.1016/j.ecoinf.2020.101088.
- verified: OpenAlex record (no abstract). Make no claim beyond the title (uses temporal information for fish detection and species classification).

### 24. Saleh, Sheaves & Rahimi Azghadi 2022 [B]
Saleh, A., Sheaves, M., Rahimi Azghadi, M. (2022). Computer vision and deep learning for fish classification in underwater habitats: a survey. *Fish and Fisheries* 23(4): 977-999. DOI 10.1111/faf.12666.
- verified: OpenAlex record with abstract.
- Usable claim (abstract): "the enormous volume of collected videos makes extracting useful information a daunting and time-consuming task for a human being"; deep learning is positioned as the response.

### 25. Saleh, Sheaves, Jerry & Rahimi Azghadi 2024 [B]
Saleh, A., Sheaves, M., Jerry, D.R., Rahimi Azghadi, M. (2024; Expert Systems with Applications vol. 238 is the November 2023 / March 2024 issue; the record lists year 2023). Applications of deep learning in fish habitat monitoring: a tutorial and survey. *Expert Systems with Applications* 238: 121841. DOI 10.1016/j.eswa.2023.121841.
- verified: OpenAlex record with abstract. Year ambiguity: OpenAlex says 2023; cite as 2023/2024 per the journal page you retrieve at submission.
- Usable claim (abstract): permanent and temporary underwater cameras "generate a massive volume of digital data, which cannot be efficiently analyzed manually" (abstract text cut off in my record; use as paraphrase).

### 26. Goodwin et al. 2022 [B]
Goodwin, M., Halvorsen, K.T., Jiao, L., Knausgard, K.M., Martin, A.H., Moyano, M., Oomen, R.A., Rasmussen, J.H., Sorensen, T.K., Thorbjornsen, S.H. (2022). Unlocking the potential of deep learning for marine ecology: overview, applications, and outlook. *ICES Journal of Marine Science* 79(2): 319-336. DOI 10.1093/icesjms/fsab255. (Authors' diacritics omitted here; pull the exact spelling from the DOI page.)
- verified: Crossref record (authors as given there, volume, pages 319-336, published 14 Jan 2022) with abstract. Issue number 2 is not from the record; omit if you cannot confirm.
- Usable claim (abstract, paraphrase): review focused on supervised learning with deep neural networks with case studies on plankton, fish, marine mammals, pollution and nutrient cycling spanning detection, classification, tracking and segmentation.

### 27. Ditria, Buelow, Gonzalez-Rivero & Connolly 2022 [A]
Ditria, E.M., Buelow, C.A., Gonzalez-Rivero, M., Connolly, R.M. (2022). Artificial intelligence and automated monitoring for assisting conservation of marine ecosystems: a perspective. *Frontiers in Marine Science* 9: 918104 (published 28 Jul 2022). DOI 10.3389/fmars.2022.918104.
- verified: opened the Frontiers full text (saved; grepped).
- Usable claims (abstract, verbatim fragments): roadblocks to timely monitoring include "limited funding, inadequate sampling, and data processing bottlenecks"; AI "can help alleviate a number of these issues by reducing the monitoring bottlenecks and long-term costs of monitoring". Perspective paper (no new data).

### 28. Marini et al. 2018 [B]
Marini, S., Fanelli, E., Sbragaglia, V., Azzurro, E., del Rio Fernandez, J., Aguzzi, J. (2018). Tracking fish abundance by underwater image recognition. *Scientific Reports* 8: 13748. DOI 10.1038/s41598-018-32089-8.
- verified: OpenAlex record with abstract. This is the paper Langlois 2020 cites for "automated image annotation" (ref list line, read).
- Usable claim (abstract): processed more than 20,000 images from a coastal cabled observatory (OBSEA-EMSO) with genetic-programming-based content analysis; automated counts highly correlated with manual counts.

### 29. Sanchez et al. 2026 (Sci Data) [A, landing page]
Sanchez, J.S., Lisani, J.-L., Catalan, I.A., Alvarez-Ellacuria, A. (2026). A dataset for fish segmentation and tracking in underwater videos. *Scientific Data* 13: 1181 (online 12 Aug 2026). DOI 10.1038/s41597-026-07786-z.
- verified: opened the Nature landing page (title, authors, volume, article number, DOI, online date, description meta tag).
- Usable claims (abstract): underwater videos from the Balearic Sea annotated for pixel-level segmentation and multi-object tracking; baselines with Deep OC-SORT; the authors "release an open-source, browser-based annotation tool integrating the Segment Anything Model (SAM2) and CUTIE for efficient semi-automatic segmentation and tracking." Precedent for SAM2 in fish video annotation, as an annotation aid with a person in the loop, not as an autonomous counter.

### 30. Iyer et al. 2025 (DeepSee) [A, landing page]
Iyer, K.H., Marnor, C.M., Schmid, D.W., Hartz, E.H. (2024; Frontiers lists publication date 13 Jan 2025). Detecting and quantifying deep sea benthic life using advanced object detection. *Frontiers in Marine Science* 11: 1470424. DOI 10.3389/fmars.2024.1470424.
- verified: opened the DOI landing page (meta: volume 11, first page 1470424, online 19 Dec 2024, publication date 13 Jan 2025); abstract from the OpenAlex record.
- Usable claims (abstract): dataset of "2,825 carefully curated images, encompassing 20,076 instances across 15 object-detection classes based on morphospecies" (North Atlantic deep sea), YOLOv8, mAP 0.84; the authors state the model is "not intended to replace the expertise of experienced biologists". Example of a closed-set (15 classes) deep-sea detector. The abstract also claims "reducing annotation workloads by over 1000 times"; I would not repeat that figure without reading how it is computed.

## 3. Open-set / long-tail / novelty and marine foundation models

### 31. FathomNet (Katija et al. 2022) [A]
Katija, K., Orenstein, E., Schlining, B., Lundsten, L., Barnard, K., Sainz, G., Boulais, O., Cromwell, M., Butler, E., Woodward, B., Bell, K.L.C. (2022). FathomNet: a global image database for enabling artificial intelligence in the ocean. *Scientific Reports* 12: 15914. DOI 10.1038/s41598-022-19939-2. PMCID PMC9508077. (Note: the DOI suffix is s41598-022-19939-2; s41598-022-11990-7 is not this paper.)
- verified: opened the PMC full text and Europe PMC record.
- Usable claims:
  - Results, "FathomNet dataset statistics": "As of July 2022, FathomNet has 84,454 images, 175,873 localizations from 204 separate collections for 2244 concepts." (re-checked in my fetch result; treat as quoted from the paper).
  - Abstract: ML has "had limited success in the ocean due to lack of data standardization, insufficient formatting, and demand for large, labeled datasets"; FathomNet "standardizes and aggregates expertly curated labeled data".
  - Methods (VARS): MBARI's VARS holds >170,000 localizations over 1,185 concepts (about 75% in FathomNet) and over 7.5 M annotations across 4,300 concepts (paraphrase from my fetch).
  - Discussion para 3 (paraphrase): models trained on benchmark datasets are not robust to natural distribution shift; the authors argue no single general classifier is feasible given the many undiscovered organisms. The paper does not use the words "long-tail" or "open-set" (searched by the fetch tool).
  - Images and ROV video, not BRUV; no MaxN.

### 32. FathomNet2023 competition dataset (Orenstein et al. 2023) [A]
Orenstein, E.C., Barnard, K., Lundsten, L., Patterson, G., Woodward, B., Katija, K. (2023). The FathomNet2023 competition dataset. arXiv:2307.08781 (cs.CV), submitted 17 Jul 2023; presented at the 10th Fine-Grained Visual Categorization workshop, CVPR 2023.
- verified: opened the arXiv abstract page (date from the page metadata).
- Usable claims (abstract, verbatim): "Creating models that are able to recognize when an image or video sequence contains a new organism, an unusual collection of animals, or is otherwise out-of-sample is critical to fully leverage visual data in the ocean." The competition "presents a realistic scenario where the set of animals in the target data differs from the training data. The challenge is both to identify the organisms in a target image and assess whether it is out-of-sample." Dataset size and class counts not stated on the abstract page.

### 33. BIIGLE 2.0 (Langenkamper et al. 2017) [B]
Langenkamper, D., Zurowietz, M., Schoening, T., Nattkemper, T.W. (2017). BIIGLE 2.0 - browsing and annotating large marine image collections. *Frontiers in Marine Science* 4: 83. DOI 10.3389/fmars.2017.00083. (Corrigendum: Front. Mar. Sci. 7: 617268, 2020, which only fixes the web address.)
- verified: OpenAlex record with abstract.
- Usable claims (abstract): "a comprehensive interpretation of such image collections requires the detection, classification and quantification of objects of interest in the images usually performed by domain experts"; BIIGLE 2.0 is built "with a special focus on annotating benthic fauna" with tools "customized to increase efficiency and effectiveness in the manual annotation process". Image (not BRUV video) annotation tool.

### 34. MAIA (Zurowietz et al. 2018) [B]
Zurowietz, M., Langenkamper, D., Hosking, B., Ruhl, H.A., Nattkemper, T.W. (2018). MAIA - a machine learning assisted image annotation method for environmental monitoring and exploration. *PLoS ONE* 13(11): e0207498. DOI 10.1371/journal.pone.0207498.
- verified: OpenAlex record with abstract.
- Usable claims (abstract): marine imaging "presents a bottleneck problem as tens of thousands or more images can be collected during a single dive"; the method is "machine learning assisted" annotation because "training data and class labels cannot be collected as efficiently and comprehensively as in other areas". Human-in-the-loop precedent in marine imagery (still images).

### 35. CoralNet (Beijbom et al. 2015) [B]
Beijbom, O., Edmunds, P.J., Roelfsema, C., Smith, J., Kline, D.I., Neal, B.P., Dunlap, M.J., Moriarty, V., Fan, T.-Y., Tan, C.-J., Chan, S., Treibitz, T., Gamst, A., Mitchell, B.G., Kriegman, D. (2015; author list truncated in my record at 15 names; I did not confirm the last three). Towards automated annotation of benthic survey images: variability of human experts and operational modes of automation. *PLoS ONE* 10(7): e0130312. DOI 10.1371/journal.pone.0130312.
- verified: OpenAlex record with abstract. The names after "Treibitz" (Gamst, Mitchell, Kriegman) are from memory; check them against the DOI page or use "et al.".
- Usable claims (abstract): manual annotation of benthic survey images "is typically a time consuming, manual task"; compares inter- and intra-annotator variability among six human experts with automated point annotation. Supports "human annotators disagree" and "operational modes of automation" (automation with human confirmation).

### 36. Squidle+ (Friedman et al. 2025/2026) [A]
Friedman, A., Monk, J., Pizarro, O., Lindsay, D., Oh, E., Thornton, B., Carroll, A., Przeslawski, R., Williams, S. Squidle+: a collaborative platform to manage, discover and annotate marine imagery. *Frontiers in Marine Science* 12 (2025 volume; published 30 January 2026): 1677103. DOI 10.3389/fmars.2025.1677103.
- verified: opened the Frontiers full text (first ~100k characters read via the fetch tool).
- Usable claims:
  - Abstract: "integrated QA/QC tools enable cross-validation between human annotators and Machine Learning (ML) algorithms"; "currently the largest known repository of openly accessible georeferenced marine images with associated annotations."
  - Sec. 2.3: active learning described as "an algorithm prompting a human to interactively review Annotations"; Sec. 2.4: ML "supplementary annotations" appear as label suggestions that users accept or correct; Sec. 2.1: a "Needs Review" flag. (paraphrases)
  - Sec. 3.4 (as at June 2025): "over 10.2 million images from 22,107 deployments across 1,062 campaigns"; over 5.85 million annotations; 2,416 registered users (paraphrase from my fetch).
  - Co-author Jacquomo Monk (IMAS/UTAS) is also the contact on the IMAS dataset record (ref 10), so the tooling and dataset are from the same group. Framed around images/imagery, not MaxN.

### 37. MarineGPT (Zheng et al. 2023) [A]
Zheng, Z., Zhang, J., Vu, T.-A., Diao, S., Wong, Y.H.T. (as listed on arXiv: "Yue Him Wong Tim"), Yeung, S.-K. (2023). MarineGPT: unlocking secrets of ocean to the public. arXiv:2310.13596 (cs.CL), v1 20 Oct 2023.
- verified: opened the arXiv abstract page.
- Usable claims (abstract): "the first vision-language model specially designed for the marine domain"; general-purpose multimodal LLMs "understand marine-specific intents poorly" (paraphrase); Marine-5M dataset of "more than 5 million marine image-text pairs". A chat/VQA-style marine VLM; the abstract describes no tracking, counting or auditing of detector outputs. I did not read beyond the abstract.

### 38. CoralSCOP (Zheng et al. 2024) [B]
Zheng, Z., Liang, H., Hua, B.-S., Wong, Y.H., Ang, P., Chui, A.P.Y., Yeung, S.-K. (2024). CoralSCOP: segment any coral image on this planet. *CVPR 2024*, pp. 28170-28180. DOI 10.1109/CVPR52733.2024.02661.
- verified: OpenAlex record with abstract; the CVF open-access page loaded but without abstract text.
- Usable claims (abstract): "the first foundation model designed for the automatic dense segmentation of coral reefs"; "strong zero-shot ability to segment unseen coral images"; trained on CoralMask, "41,297 densely labeled coral images and 330,144 coral masks". A SAM-style model for benthic stills, not animals in video.

### 39. Dual-SAM, "Segment Any Marine Animal" (Zhang et al. 2024) [B]
Zhang, P., Yan, T., Liu, Y., Lu, H. (2024). Fantastic animals and where to find them: segment any marine animal with dual SAM. *CVPR 2024*, pp. 2578-2587. DOI 10.1109/CVPR52733.2024.00249.
- verified: OpenAlex record with abstract (the CVF page URL I guessed returned 404, so the page itself was not opened).
- Usable claims (abstract): SAM "trained with natural images, ... does not obtain the prior knowledge from marine images" and "the single-position prompt of SAM is very insufficient for prior guidance", so they fine-tune with adapters and a "Multi-level Coupled Prompt". Evidence that marine users adapt SAM by training; target is single-image marine animal segmentation.

### 40. UW-VOS / SAM-U (Zhao et al. 2026) [A, arXiv page + record]
Zhao, H., Tai, J., Wu, Y., Zhang, W., Lan, X., Wang, S., Zhang, T., Yang, W. (2026). UW-VOS: a large-scale dataset for underwater video object segmentation. arXiv:2603.24006 (submitted 25 Mar 2026).
- verified: opened arXiv abs page (title/date); abstract from the OpenAlex record.
- Usable claims (abstract): "1,431 video sequences across 409 categories with 309,295 mask annotations"; proposes SAM-U that "adapts SAM2 to the underwater domain" with adapters, "only ~2% trainable parameters"; existing methods "experience an average 13-point J&F drop on UW-VOS". Evidence of a domain gap for open-air video segmenters in water; the paper's fix is fine-tuning. Preprint, not peer reviewed as far as I can tell.

### 41. Fish-Vista (Mehrab et al. 2025) [B]
Mehrab, K.S., Maruf, M., Daw, A., Neog, A., Manogaran, H.B., Khurana, M., Feng, Z., Altintas, B., Bakis, Y., Campolongo, E., Thompson, M.J., Wang, X., et al. (2025). Fish-Vista: a multi-purpose dataset for understanding & identification of traits from images. *CVPR 2025*, pp. 24275-24285. DOI 10.1109/CVPR52734.2025.02261. (19 authors in the record; I list only those I saw.)
- verified: OpenAlex record with abstract.
- Usable claim (abstract): "69,269 annotated images spanning 4,316 fish species", from museum collections; offers grounds for "handling long-tailed distributions, out-of-distribution generalization". Museum specimen images, not in situ video.

## 4. Human-in-the-loop analogues in ecology

### 42. Norouzzadeh et al. 2018 [B]
Norouzzadeh, M.S., Nguyen, A., Kosmala, M., Swanson, A., Palmer, M.S., Packer, C., Clune, J. (2018). Automatically identifying, counting, and describing wild animals in camera-trap images with deep learning. *Proceedings of the National Academy of Sciences* 115(25): E5716-E5725. DOI 10.1073/pnas.1719367115.
- verified: OpenAlex record with abstract.
- Usable claims (abstract): networks identify 48 species in the 3.2 million-image Snapshot Serengeti set with ">93.8% accuracy"; "if our system classifies only images it is confident about, our system can automate animal identification for 99.3% of the data while still performing at the same 96.6% accuracy as that of crowdsourced teams" (my record shows the sentence cut off after "crowdsourced tea"; the full phrase "crowdsourced teams of human volunteers" is from memory, so quote only up to "96.6% accuracy"). Confidence-gated automation with people for the rest.

### 43. Tabak et al. 2019 [B]
Tabak, M.A., Norouzzadeh, M.S., Wolfson, D.W., et al. (24 authors; Clune, J., Miller, R.S. last). (2019). Machine learning to classify animal species in camera trap images: applications in ecology. *Methods in Ecology and Evolution* 10(4): 585-590. DOI 10.1111/2041-210X.13120.
- verified: OpenAlex record with abstract (OpenAlex lists year 2018 online).
- Usable claims (abstract): ResNet-18 on "3,367,383 images" from five US states; "98% accuracy at identifying species in the United States"; "out-of-sample validation from Canada achieved 82% accuracy"; "correctly identified 94% of images containing an animal in the dataset from Tanzania", a community "novel to the model". Shows accuracy drops on novel faunas.

### 44. Willi et al. 2019 [B]
Willi, M., Pitman, R.T., Cardoso, A.W., Locke, C., Swanson, A., Boyer, A., Veldthuis, M., Fortson, L. (2019; online 2018). Identifying animal species in camera trap images using deep learning and citizen science. *Methods in Ecology and Evolution* 10(1): 80-91. DOI 10.1111/2041-210X.13099.
- verified: OpenAlex record with abstract.
- Usable claim (abstract): by training on images classified by citizen scientists and applying the models to new studies "human effort may be reduced substantially"; models are applied on a live citizen-science project. Humans-plus-model workflow.

### 45. Beery, Morris & Yang 2019 [A]
Beery, S., Morris, D., Yang, S. (2019). Efficient pipeline for camera trap image review. arXiv:1907.06772 (submitted 15 Jul 2019).
- verified: opened the arXiv abs page (title/date) and abstract.
- Usable claims (abstract): classifiers trained in one region can fail "catastrophically in new region, due to both changes in background and the presence of previously-unseen species"; proposes using a pre-trained general animal detector plus a small labeled set. This is the MegaDetector line of work (the abstract does not use the name "MegaDetector"; if you cite it as such, cite the project, not this abstract).

---

# POSITIONING GAPS (what the prior work I verified does not do, with evidence)

I state each gap as "in the papers I read, X is not done or not reported". I did not do a systematic review; searches were by title/abstract keywords in OpenAlex plus the pages above. Reword to "to our knowledge" in the paper.

1. **Prior automated BRUV/underwater counters are closed-set and target-species-specific, while the manual standard counts the whole assemblage.**
   - Langlois 2020 (ref 1, Sec. 2.6.3): "all fish be identified to the lowest taxonomic level possible".
   - Ditria 2020 (ref 11): one species (luderick); Connolly 2021 (ref 15): one species (Australasian snapper) with two lookalikes as negatives; SharkTrack (ref 18): sharks and rays only, with species chosen by a person afterwards; Lopez-Marcano 2021 (ref 14): bream.
   - Marrable 2022 (ref 16) is the broadest BRUV effort: 12 target species plus a catch-all "fish" class, and "88% of fish were located and given a fish label and identified for manual labelling."
   - Ditria 2020 multi-habitat (ref 13): single-species detectors "performed well on test footage from their own habitat but poorly on the other".
   - Barord 2014 (ref 9) shows in its own supplementary video that BRUV footage of the target (nautilus) also contains hagfish and shrimp. A detector trained on one taxon has no way to name them.
   => Gap: discovery and naming of *untargeted* taxa in BRUV video without a pre-trained species list. I found no BRUV paper that does this (negative result from my searches, not proof).

2. **Open-set/novelty work in marine imagery exists but is not about BRUV video counts.**
   - FathomNet2023 (ref 32) frames "recognize when an image or video sequence contains a new organism ... out-of-sample" as the central problem; Katija 2022 (ref 31) argues no single general classifier is feasible given undiscovered organisms. Both work on images/ROV data and evaluate identification, not MaxN.
   - Tabak 2019 (ref 43) shows accuracy drops on novel faunas in camera traps (82% on Canadian ungulates).
   => Gap: connecting open-vocabulary naming to the BRUV abundance metric (MaxN) and its frame.

3. **Foundation models in marine work are fine-tuned or used for annotation/chat, not zero-shot concept-prompted video segmentation for counting.**
   - CoralSCOP (ref 38): coral stills. Dual-SAM (ref 39): fine-tuned for single-image marine animal segmentation; says SAM lacks marine prior knowledge and single-point prompts are insufficient. UW-VOS/SAM-U (ref 40): fine-tunes SAM2 with adapters after a 13-point J&F drop. Sánchez 2026 (ref 29): SAM2 + CUTIE as an annotation tool for building a dataset. MarineGPT (ref 37): a marine chat VLM (abstract: image-text pairs, no counting).
   => Gap: an off-the-shelf concept-prompted video segmenter (text and box prompts) used directly as the BRUV tracker, evaluated on MaxN. This is a claim about *absence in what I read*; I did not find a BRUV-MaxN paper using SAM-family models.

4. **No verified prior work uses a vision-language model to audit a tracker's output.**
   - Closest are QA/QC procedures built around humans or classifiers: Squidle+ (ref 36) cross-validation between humans and ML with a "Needs Review" flag; Langlois 2020 (ref 1) reviews 10% of videos and requires 95% accuracy of identifications and MaxN; Beery 2019 (ref 45) and Norouzzadeh 2018 (ref 42) gate automation by detector or classifier confidence.
   - I found no marine paper where a VLM re-examines tracks and checks the MaxN frame (searches: "vision-language model species identification underwater video BRUV", "zero-shot open-vocabulary fish detection ... baited remote underwater video" returned nothing relevant).
   => Gap stated as "to our knowledge".

5. **MaxN is sensitive to single-frame errors, which motivates checking that frame.**
   - Connolly 2021 (ref 15): the raw detector double/triple-counted at >15 fish per frame and was off by up to 50%; mitigated with Seq-NMS and a fitted cubic correction.
   - Schobernd 2014 (ref 4) and Kilfoil 2021 (ref 7): MaxN is nonlinear in abundance and depends on non-density factors; Ellis & DeMartini 1995 (ref 2) found MAXNO unrelated or inversely related to density in earlier deep-sea baited-camera work.
   - Langlois 2020: second-annotator check of MaxN.
   => The unit that matters (one frame) is also the unit most easily corrupted by one duplicate or missed animal.

6. **Motion cues as prompts.** The closest prior art uses motion to *generate candidate regions for training a closed-set detector* (Salman 2020, ref 22: background subtraction and optical flow) or temporal information in the title of Jalal 2020 (ref 23). Seq-NMS (Connolly 2021, Lopez-Marcano 2021) links detections over neighbouring frames. None of these, in the abstracts I read, turns motion into box prompts for a promptable segmenter. Again, absence in what I read.

7. **Cost framing (use with care).** The only numeric manual-effort figures I read on a source page: Marrable 2022 Sec. 1 (several hours of analyst time per hour of video, citing Francour 1999; AIMS estimate of ~12,000 analyst hours for ~4,000 h of video per year; both the authors' quotations of others) and Ditria 2020 (13.5 s per fish annotation, ~23 h to annotate the training set; computer inference about half the human time for video, 1.2 vs 2.4-2.8 min per minute of video). Langlois 2020 and Connolly 2021 state the burden qualitatively ("time consuming"; "substantial costs") without numbers.

8. **Human review is the accepted endpoint, not a weakness.** Marrable 2022: "Manual labelling and classification effort is still required." SharkTrack: user classifies species. Squidle+, MAIA, CoralNet: assisted annotation. Camera-trap work (refs 42-45): confidence-gated automation. A "person reviews a short queue" design is consistent with the field's norm; the novelty is what goes into the queue (audited tracks, the MaxN frame, untargeted taxa).

---

# UNVERIFIED (do not cite until confirmed)

- **Monk, Barrett & Langlois (2024) as the author/year of the IMAS curated-video dataset.** The data.gov.au record I opened does not list authors or a 2024 year (dates: created/updated 24/06/2025; "As of August 2024" in the description; contact jacquomo.monk@utas.edu.au). A web search snippet said researchdata.edu.au lists Monk and Barrett as creators, but that URL returned 404 when I fetched it, so I did not see this myself. Langlois's authorship is not confirmed anywhere I looked.
- **Dataset license for the IMAS record**: "Not Specified" on the page; unknown otherwise.
- **MarineInst** (Zheng, Chen, Zeng, Vu, Hua, Yeung. MarineInst: a foundation model for marine image analysis with instance visual description. ECCV 2024, LNCS, pp. 239-257, DOI 10.1007/978-3-031-72627-9_14): the OpenAlex record exists (no abstract); the Springer page returned a bot challenge. Not opened, no claims.
- **Cappo et al. 2004** (JEMBE, BRUVS vs prawn trawls, Great Barrier Reef) and **Cappo, Harvey & Shortis 2006** (counting and measuring fish with baited video techniques): seen only as entries in Langlois 2020's reference list (read), not opened. Crossref title search returned unrelated items. Do not cite for MaxN history without opening them.
- **Coghlan et al. 2017**, J. Exp. Mar. Biol. Ecol. 497: 143-151, DOI 10.1016/j.jembe.2017.09.005 ("Does fish behaviour bias abundance and length information collected by baited underwater video?"): citation appears in Langlois's reference list; Langlois says it is "the only study so far" finding MaxN "provides a representative sample of size distributions". Paper not opened.
- **Francour et al. 1999** and **Sheaves et al. 2020**, **Jager et al. 2015**, **Gilby et al. 2017**: cited inside Marrable/Ditria text I read; not opened.
- **Thalassas 2022 Philippine nautilus survey** (Siquijor / Dalaguete-Alcoy, baited traps + BRUVS, ~20 h and ~12 h of footage, no nautilus on video): seen only in a search-result snippet; not opened; authors/title unknown.
- **Any other nautilus BRUV study that reports MaxN**: I did not find one.
- **FishSAM, MarineSAM**: no paper found under these names.
- **Nature page for Katija 2022 and Sharktrack journal PDF**: not opened (nature.com blocked; I used PMC and the FIU record).
- **Fish4Knowledge volume number, Goodwin issue number, Beijbom last three authors, Norouzzadeh abstract tail**: see notes in refs 20, 26, 35, 42 (parts from memory, not verified).
- **Springer/Wiley/Elsevier pages** for Salman 2020, Campbell 2015, Schobernd 2014: publisher pages blocked (403/redirect); data from DOI-registry records only.
- **Ellis & DeMartini 1995 DOI**: none found; cite by journal/pages and the NOAA URL.
