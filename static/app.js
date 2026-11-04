// reefcensus review screen. Plain DOM; every model-written string goes in through textContent.
"use strict";

const STAGES = [
  ["ingest", "Read video"], ["scout", "Spark scouts"], ["discover", "Spark looks wider"], ["track", "SAM tracks"],
  ["recover", "Second look"], ["motion", "Motion look"], ["audit", "Spark audits"], ["verify", "Peak check"], ["render", "Draw"], ["done", "Done"],
];
const $ = (id) => document.getElementById(id);
const state = { id: null, run: null, status: null, lastStage: null, poll: null, fps: 5, n: 0 };

function el(tag, attrs = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k === "class") e.className = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else e.setAttribute(k, v === true ? "" : v);
  }
  for (const k of kids.flat()) if (k != null && k !== false) e.append(k instanceof Node ? k : document.createTextNode(String(k)));
  return e;
}
const svgEl = (tag, attrs = {}) => {
  const e = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  return e;
};
async function api(path, opts = {}) {
  const r = await fetch(path, opts);
  const body = r.headers.get("Content-Type")?.includes("json") ? await r.json() : await r.text();
  if (!r.ok) throw new Error(body.error || r.statusText);
  return body;
}
const secs = (t) => (t == null ? "–" : `${t.toFixed(1)} s`);
const colour = (origin) => (origin === "asked" ? "var(--asked)" : "var(--found)");

// ---------- runs ----------
async function loadRuns(select) {
  const { runs } = await api("api/runs.json");
  const sel = $("runSel");
  sel.replaceChildren(...runs.map((r) => el("option", { value: r.id },
    `${r.id}${r.stage === "done" ? "" : `  (${r.stage})`}`)));
  const want = select || decodeURIComponent(location.hash.slice(1)) || (runs.find((r) => r.stage === "done") || runs[0] || {}).id;
  if (want) { sel.value = want; openRun(want); }
  else showScreen("No runs yet. Start one with New run.");
}

async function openRun(id) {
  clearTimeout(state.poll);
  if (state.id !== id) { state.run = null; state.lastStage = null; }
  state.id = id;
  history.replaceState(null, "", `#${encodeURIComponent(id)}`);
  $("exportBtn").href = `api/runs/${encodeURIComponent(id)}/export.csv`;
  $("exportGaBtn").href = `api/runs/${encodeURIComponent(id)}/export_globalarchive.csv`;
  let st;
  try { st = await api(`runs/${encodeURIComponent(id)}/status.json`); }
  catch { state.poll = setTimeout(() => openRun(id), 1000); return; }   // being written or not there yet
  if (state.id !== id) return;
  state.status = st;
  if (st.stage !== "error") state.lastStage = st.stage;
  drawRail(st); drawMeter(st); drawLog(st);
  if (st.stage === "done") {
    if (!state.run) { state.run = await api(`api/runs/${encodeURIComponent(id)}.json`); drawRun(true); }
  } else if (st.stage === "error") {
    showScreen(`Run stopped. ${st.error || ""}`);
  } else {
    showScreen(`Working: ${(st.log.at(-1) || "starting").replace(/^\d\d:\d\d:\d\d /, "")}`);
    state.poll = setTimeout(() => openRun(id), 1000);
  }
}

function drawRail(st) {
  const at = STAGES.findIndex(([k]) => k === (st.stage === "error" ? state.lastStage : st.stage));
  $("rail").replaceChildren(...STAGES.map(([, name], i) => el("li", {
    class: i < at || st.stage === "done" ? "past" : i === at ? (st.stage === "error" ? "fail" : "now") : "",
    "aria-current": i === at ? "step" : null,
  }, name)));
}

function drawMeter(st) {
  const live = st.live_calls > 0;
  const took = st.done ? `, ${Math.round(st.done - st.started)} s` : "";
  $("meter").replaceChildren(
    el("b", { class: live ? "live" : "cache" }, live ? "Live API calls" : "Replayed from saved answers"),
    el("span", { class: "num" }, live
      ? `${st.live_calls} calls, ${st.cached_calls} reused, $${st.billed_usd.toFixed(3)} billed${took}`
      : `${st.cached_calls} saved answers, $0 billed${took}`));
}

function drawLog(st) {
  $("log").replaceChildren(...st.log.map((l) => el("li", {}, l)));
}

function showScreen(msg) {
  const v = $("vid");
  if (msg) { v.removeAttribute("src"); v.load(); }
  $("screenMsg").hidden = !msg;
  $("screenMsg").textContent = msg || "";
}

// ---------- finished run ----------
// a row that is both MaxN 0 and "(unidentified)" says nothing: not shown here, not in the CSV (server.export_csv)
const hidden = (name, m) => m.maxn === 0 && name.endsWith(" (unidentified)");

function order(run) {
  return Object.entries(run.metrics).filter(([n, m]) => !hidden(n, m)).sort(([a, x], [b, y]) =>
    (run.origin[a] === "asked" ? 0 : 1) - (run.origin[b] === "asked" ? 0 : 1) || y.maxn - x.maxn || a.localeCompare(b));
}

function drawRun(withVideo) {
  const run = state.run;
  state.fps = run.video.fps || 5; state.n = run.video.n_frames;
  if (withVideo) {
    showScreen(null);
    const v = $("vid");
    v.src = `runs/${encodeURIComponent(run.id)}/${run.annotated ? "annotated.mp4" : "clip.mp4"}`;
  }
  drawStrip(); drawEvidence(); drawAsked(); drawFound(); drawSecond(); drawQueue();
}

function seek(frame) {
  const v = $("vid");
  v.currentTime = (frame + 0.5) / state.fps;   // middle of the frame: browsers land on frame boundaries unevenly
  v.pause();
}

function drawStrip() {
  const run = state.run, n = state.n, strip = $("strip");
  const lanes = order(run).map(([name, m]) => {
    const top = Math.max(1, m.maxn), c = m.curve;
    const svg = svgEl("svg", { viewBox: `0 0 ${n} 1`, preserveAspectRatio: "none", "aria-hidden": "true" });
    let d = `M0 1`;
    c.forEach((v, i) => { const y = 1 - (v / top) * 0.92; d += ` L${i} ${y} L${i + 1} ${y}`; });
    d += ` L${n} 1 Z`;
    const col = colour(run.origin[name]);
    svg.append(svgEl("rect", { x: 0, y: 0.98, width: n, height: 0.02, fill: "var(--rule)" }));
    svg.append(svgEl("path", { d, fill: col, "fill-opacity": name.endsWith("(unidentified)") ? 0.35 : 0.8 }));
    if (m.maxn_frame != null)
      svg.append(svgEl("rect", { x: m.maxn_frame, y: 0, width: 1, height: 1, fill: "var(--graphite)", "fill-opacity": 0.85 }));
    return el("div", { class: "lane", title: `${name}: MaxN ${m.maxn} at ${secs(m.maxn_time)}` },
      el("div", { class: "who" }, el("i", { style: `background:${col}` }), name), svg,
      el("div", { class: "peak num" }, m.maxn));
  });
  const dur = n / state.fps;
  const axis = el("div", { class: "axis" }, el("span"), el("div", { class: "num" },
    ...[0, 0.25, 0.5, 0.75, 1].map((p) => el("span", {}, `${(dur * p).toFixed(0)} s`))), el("span"));
  const head = el("div", { class: "head" });
  strip.replaceChildren(...(lanes.length ? lanes : [el("p", { class: "empty", style: "padding:0 12px" }, "Nothing was counted in this clip.")]), axis, head);
  const reviewed = run.n_reviewed;
  $("strip").nextElementSibling?.classList?.contains("stale") && $("strip").nextElementSibling.remove();
  if (reviewed) strip.after(el("p", { class: "stale" },
    `The video shows the automatic labels. Counts, lanes and the table include your ${reviewed} edit${reviewed > 1 ? "s" : ""}.`));
  movePlayhead();
}

function laneBox() {
  const svg = $("strip").querySelector("svg");
  return svg ? [svg.getBoundingClientRect(), $("strip").getBoundingClientRect()] : null;
}
function movePlayhead() {
  const b = laneBox(), head = $("strip").querySelector(".head");
  if (!b || !head) return;
  const [s, outer] = b, f = Math.min(state.n - 1, Math.floor($("vid").currentTime * state.fps));
  head.style.left = `${s.left - outer.left + ((f + 0.5) / state.n) * s.width}px`;
}
(function tick() { if (!$("vid").paused) movePlayhead(); requestAnimationFrame(tick); })();

function drawEvidence() {
  const run = state.run;
  $("evidence").replaceChildren(...order(run).filter(([, m]) => m.evidence).map(([name, m]) => {
    const src = `runs/${encodeURIComponent(run.id)}/${m.evidence}`;
    const cap = `${name}: ${m.maxn} at ${secs(m.maxn_time)}${m.peak_checked ? ", every box checked by Spark" : ""}`;
    return el("figure", { class: run.origin[name], tabindex: 0, onclick: () => zoom(src, cap), onkeydown: (e) => e.key === "Enter" && zoom(src, cap) },
      el("img", { src, alt: `Peak frame for ${name}`, loading: "lazy" }), el("figcaption", {}, cap));
  }));
}

function tally(n, col) {
  const shown = Math.min(n, 40), groups = Math.ceil(shown / 5);
  const w = Math.max(1, groups) * 34;
  const svg = svgEl("svg", { class: "tally", viewBox: `0 0 ${w} 28`, width: w, height: 28, role: "img", "aria-label": `${n} counted` });
  for (let g = 0; g < groups; g++) {
    const k = Math.min(5, shown - g * 5), x0 = g * 34 + 3;
    for (let i = 0; i < Math.min(k, 4); i++)
      svg.append(svgEl("line", { x1: x0 + i * 6, y1: 3, x2: x0 + i * 6, y2: 25, stroke: col, "stroke-width": 3, "stroke-linecap": "round" }));
    if (k === 5) svg.append(svgEl("line", { x1: x0 - 3, y1: 22, x2: x0 + 21, y2: 6, stroke: col, "stroke-width": 3, "stroke-linecap": "round" }));
  }
  return svg;
}

function countRow(name, m, origin, extra = []) {
  return el("div", { class: "count" },
    el("div", { class: "name" }, name),
    el("div", { class: "big num" }, (m.lower_bound ? "≥" : "") + m.maxn),
    tally(m.maxn, colour(origin)),
    el("div", { class: "facts" },
      el("span", {}, `first seen ${secs(m.first_time)}`),
      m.maxn_frame != null ? el("button", { class: "jump", onclick: () => seek(m.maxn_frame) }, `peak at ${secs(m.maxn_time)}`) : null,
      m.peak_checked ? el("span", { class: "checked" }, "Spark checked every box in the peak frame") : null),
    // the server's lower end leaves out queued tracks nobody has reviewed; reviewing them closes the range
    m.maxn_confirmed != null && m.maxn_confirmed < m.maxn
      ? el("div", { class: "range" }, "Until a person checks the queue: ",
        el("span", { class: "num" }, `${m.maxn_confirmed}–${m.maxn}`),
        ` (${m.maxn_confirmed} counts only what Spark was sure of)`)
      : null,
    crowdNote(m),
    ...extra);
}

function drawAsked() {
  const run = state.run;
  const words = run.prompts.map(([, p]) => p);
  const rows = order(run).filter(([n]) => run.origin[n] === "asked");
  $("askedPanel").replaceChildren(
    el("h2", {}, `You asked for ${words.join(", ")}`, el("small", {}, "SAM 3.1 tracks only the words it is given. MaxN is the most seen in one frame.")),
    ...(rows.length ? rows.map(([n, m]) => countRow(n, m, "asked"))
      : [el("p", { class: "empty" }, `No ${words.join(" or ")} in this clip.`)]));
}

function drawFound() {
  const run = state.run, disc = run.discovered || [];
  const rows = order(run).filter(([n]) => run.origin[n] === "found");
  const items = rows.map(([name, m]) => {
    const d = disc.find((x) => x.what.toLowerCase() === name);
    const extra = [];
    if (d && d.maxn_full != null && d.maxn_full < m.maxn)
      extra.push(el("div", { class: "climb" }, "First pass saw ", el("span", { class: "num" }, d.maxn_full),
        ", the second look found ", el("span", { class: "num" }, m.maxn)));
    if (d && d.tried?.length)
      extra.push(el("div", { class: "ladder" }, "SAM words tried:",
        ...d.tried.map((t) => el("span", { class: t.frames ? "hit" : "miss", title: `${t.frames} frames` }, t.word))));
    const sm = (run.site_rows || {})[name];
    if (sm)
      extra.push(el("div", { class: "ladder sitemem" }, `From site memory (${run.site.name}): a reviewer's '${sm.remembered}' from an earlier video; SAM tracked it as '${sm.word}' in ${sm.frames} frames.`));
    const fromMotion = Object.entries(run.tracks || {}).some(([t, v]) => v.source.startsWith("m") && labelOf(run, t) === name);
    if (fromMotion)
      extra.push(el("div", { class: "ladder" }, "Includes an animal no word found: it moved, Spark said it was alive, and SAM tracked a box drawn on it."));
    if (name.endsWith("(unidentified)")) {
      extra.push(el("div", { class: "ladder" }, "Spark could not name these with confidence; they wait in Needs a person."));
      const g = groupTotal(rows, name);
      if (g) extra.push(el("div", { class: "climb" }, `All ${g.head} together: `, el("span", { class: "num" }, g.maxn),
        ` in one frame (${g.parts.join(" + ")}) `,
        el("button", { class: "jump", onclick: () => seek(g.frame) }, `at ${secs(g.frame / state.fps)}`),
        g.low < g.maxn ? `; ${g.low} before the queue is checked` : ""));
    }
    return countRow(name, m, "found", extra);
  });
  const missed = disc.filter((d) => !d.word);
  $("foundPanel").replaceChildren(
    el("h2", {}, "Found without being asked", el("small", {}, "Muse Spark named what else was there; SAM tracked it under a plain word.")),
    ...(items.length ? items : [el("p", { class: "empty" }, disc.length ? "Spark saw other animals, but SAM could not track them." : "Spark saw nothing else living in this clip.")]),
    ...siteBlock(run),
    ...(missed.length ? [el("p", { class: "signs" }, "Seen but not trackable: ",
      ...missed.map((d, i) => [i ? "; " : "", el("b", {}, d.what), ` (tried ${d.tried.map((t) => t.word).join(", ")})`]))] : []),
    ...groupBlock(run));
}

// opt-in site memory: words a reviewer gave earlier videos of this site, and what SAM did with them
function siteBlock(run) {
  const s = run.site;
  if (!s) return [];
  if (!s.entries.length) return [el("p", { class: "signs" }, `Site memory (${s.name}): nothing remembered yet; renames you save here will be tried first on the next video from this site.`)];
  return [el("p", { class: "signs sitemem" }, `Site memory (${s.name}) added: `,
    ...s.entries.map((e, i) => [i ? "; " : "", el("b", {}, e.label),
      ` (${(e.tried || []).map((t) => `${t.word} ${t.frames} frames`).join(", ") || "not tried"}${e.word || !(e.tried || []).length ? "" : ": tracked nothing"})`]))];
}

// the labels behind a group total, minus rows hidden elsewhere (MaxN 0 and "(unidentified)"); the numbers are unchanged
const groupParts = (run, m) => m.labels.filter((n) => !run.metrics[n] || !hidden(n, run.metrics[n]))
  .map((n) => `${run.metrics[n]?.curve?.[m.maxn_frame] || 0} ${n}`);

// crowd check: Spark, shown the peak frame with no boxes, counted clearly more than were tracked -> a person counts it
const crowdNote = (m) => m.lower_bound ? el("div", { class: "range crowd" }, "Crowded: Spark counts about ", el("span", { class: "num" }, m.crowd_total),
  " in this frame without boxes, more than were tracked. The count is a lower bound; please count this frame.") : null;

// same-frame totals per animal group (server: pipeline.group_metrics), shown under both count panels
function groupBlock(run) {
  const gm = Object.entries(run.group_metrics || {});
  if (!gm.length) return [];
  return [el("div", { class: "groups" }, el("h3", {}, "By animal group", el("small", {}, " the labels below added frame by frame")),
    ...gm.map(([g, m]) => el("div", { class: "climb" }, `All ${g === "fish" ? "fish" : g + "s"}: `,
      el("span", { class: "num" }, (m.lower_bound ? "≥" : "") + m.maxn), ` in one frame (${groupParts(run, m).join(" + ")}) `,
      m.maxn_frame != null ? el("button", { class: "jump", onclick: () => seek(m.maxn_frame) }, `at ${secs(m.maxn_time)}`) : null,
      m.maxn_confirmed != null && m.maxn_confirmed < m.maxn ? `; ${m.maxn_confirmed} before the queue is checked` : "",
      crowdNote(m))))];
}

// "shrimp (unidentified)" and "caridean shrimp" are both shrimp: one track has one label, so per-frame counts add.
function groupTotal(rows, name) {
  const head = name.replace(/\s*\(unidentified\)$/, "");
  const members = rows.filter(([n]) => n === name || n.split(" ").at(-1) === head);
  if (members.length < 2) return null;
  const sum = members[0][1].curve.map((_, i) => members.reduce((s, [, m]) => s + (m.curve[i] || 0), 0));
  const maxn = Math.max(...sum), frame = sum.indexOf(maxn);
  const parts = members.map(([n, m]) => `${m.curve[frame] || 0} ${n === name ? "unidentified" : n.slice(0, -head.length).trim()}`);
  const conf = (m) => m.curve_confirmed || m.curve;
  const low = Math.max(...sum.map((_, i) => members.reduce((s, [, m]) => s + (conf(m)[i] || 0), 0)));
  return { head, maxn, frame, parts, low };
}

const labelOf = (run, t) => {
  const r = run.review || {}, a = run.auto_labels || {};
  return t in r ? r[t] : t in a ? a[t] : run.tracks[t].label;
};
const KIND = { backfill: "Played backwards", zoom: "Zoomed in", cell: "Closer look", sign: "Checked a sign", motion: "Motion look", "motion-scan": "Motion look" };
function motionStep(run, r) {
  if (r.kind === "motion-scan") {
    if (r.note) return el("span", { class: "none" }, "Movement outside every box: not saved for this clip, skipped in the free replay");
    const sheet = `runs/${encodeURIComponent(run.id)}/motion_sheet.jpg`;
    return el("span", { class: r.animals ? "" : "none" }, `${r.candidates} moving spot${r.candidates === 1 ? "" : "s"} where nothing was boxed; Spark looked at ${r.shown}`,
      r.shown ? [" (", el("a", { href: sheet, target: "_blank" }, "sheet"), ")"] : "",
      `, called ${r.animals} ${r.animals === 1 ? "an animal" : "animals"}` + (r.said?.length ? `: ${r.said.map((v) => `${v.tile} ${v.is_animal ? "" : "no, "}${v.what || "?"}`).join("; ")}` : ""));
  }
  const res = r.word
    ? `SAM tracked the box (no word) in ${r.frames} frames as '${r.word}'` + (r.absorbed_into ? `, joined an existing '${r.absorbed_into}' track` : "")
      + (r.overlapped ? `; ${r.overlapped} frames already tracked were dropped` : "")
      + (r.counted === false ? ". Spark's audit doubted it, so it waits in Needs a person, not in the count" : "")
    : r.note?.startsWith("already") ? `the same animal an earlier box was already following (${r.note.slice(19).trim()}), no second call`
    : r.note ? `box prompt failed (${r.note})` : "SAM found nothing new from the box";
  return el("span", { class: r.word ? "" : "none" }, `${r.tile ? r.tile + " " : ""}${r.what}, frame ${r.frame}: ${res}`);
}
function drawSecond() {
  const run = state.run;
  const steps = (run.recovered || []).map((r) => {
    if (r.kind === "motion" || r.kind === "motion-scan") return el("li", {}, el("span", { class: "kind" }, KIND[r.kind]), motionStep(run, r));
    const where = r.kind === "cell" ? `${r.cell} cell at 3x, best word then played backwards` : r.cell ? `${r.cell} block` : "whole clip";
    const res = r.word
      ? `'${r.word}' tracked in ${r.frames} frames, up to ${r.max_per_frame} at once`
      : `nothing with ${r.tried.map((t) => `'${t.word}'`).join(", ")}`;
    return el("li", {}, el("span", { class: "kind" }, KIND[r.kind] || r.kind),
      el("span", { class: r.word ? "" : "none" }, `${r.what}, ${where}: ${res}`));
  });
  const peaks = (run.peak_checks || []).map((c) => el("li", {}, el("span", { class: "kind" }, "Peak check"),
    el("span", {}, `${c.label}, frame ${c.frame}: Spark looked at ${c.checked} box${c.checked === 1 ? "" : "es"}, kept ${c.kept}`
      + (c.rejected.length ? `. Removed: ${c.rejected.map((x) => x.said).join("; ")}` : ""))));
  const dups = run.duplicates || [];
  const same = dups.filter((d) => d.same).length;
  if (dups.length) peaks.unshift(el("li", {}, el("span", { class: "kind" }, "Same animal?"),
    el("span", {}, `Spark compared ${dups.length} pair${dups.length === 1 ? "" : "s"} of nested outlines: ${same} ${same === 1 ? "was one animal" : "were one animal"} boxed twice (removed from the count)`
      + (dups.length > same ? `. Kept apart: ${dups.filter((d) => !d.same).map((d) => d.said).join("; ")}` : ""))));
  const signs = run.signs || [];
  $("secondPanel").replaceChildren(
    el("h2", {}, "Second look", el("small", {}, "SAM recognises an animal late or misses it in a crowded frame, so the pipeline tries again.")),
    steps.length || peaks.length ? el("ul", { class: "steps" }, ...steps, ...peaks) : el("p", { class: "empty" }, "No second look was needed."),
    signs.length ? el("p", { class: "signs" }, "Indirect signs Spark noticed: ",
      ...signs.map((s, i) => [i ? "; " : "", el("b", {}, s.sign), ` (frame ${s.frame}, ${s.region}${s.possible_animal && s.possible_animal !== "unknown" ? `, maybe ${s.possible_animal}` : ""})`])) : null);
}

function drawQueue() {
  const run = state.run, q = run.queue, total = Object.keys(run.verdicts || {}).length;
  const items = q.map((it) => {
    const thumb = `runs/${encodeURIComponent(run.id)}/${it.thumb}`;
    // the three crops Spark judged (early, middle, late); runs made before 11/2 v13 have only the one crop
    const trio = it.has_trio ? `runs/${encodeURIComponent(run.id)}/${it.trio}` : thumb;
    const guess = it.species && it.species !== "unknown" ? it.species.toLowerCase() : it.category;
    const said = el("div", { class: "said" }, `${it.name}: Spark says `,
      el("b", {}, it.is_target === false ? `not a ${it.category}` : (it.species || "unknown")),
      it.confidence != null ? [", ", el("span", { class: "num" }, `${Math.round(it.confidence * 100)}%`), " sure"] : null);
    const body = [said, it.from_site ? el("div", { class: "why" }, `Found because site memory asked SAM for '${it.from_site}'.`) : null,
      it.reason ? el("div", { class: "why" }, it.reason) : null];
    if (it.reviewed) {
      body.push(el("div", { class: "set" }, it.label ? `You set: ${it.label}` : "You removed it from the counts"),
        it.remembered ? el("div", { class: "why" }, `Remembered for site ${run.site.name}: '${it.remembered}' is tried first on its next video.`) : null,
        el("div", { class: "acts" }, el("button", { class: "btn ghost small", onclick: () => review(it.track, "__undo__") }, "Undo")));
    } else {
      const input = el("input", { value: guess, "aria-label": `New name for ${it.name}` });
      const form = el("form", { class: "rename", hidden: true, onsubmit: (e) => { e.preventDefault(); review(it.track, input.value); } },
        input, el("button", { class: "btn small" }, "Save name"));
      body.push(el("div", { class: "acts" },
        el("button", { class: "btn small", onclick: () => review(it.track, it.yes_label || guess) }, `Yes, ${guess}`),
        el("button", { class: "btn ghost small", onclick: () => { form.hidden = !form.hidden; if (!form.hidden) input.focus(); } }, "Rename"),
        el("button", { class: "btn ghost small", onclick: () => review(it.track, null) }, "Not an animal")), form);
    }
    if (it.rank) body.unshift(el("div", { class: "decides" }, "Your answer can change a count"));
    return el("div", { class: `qitem${it.reviewed ? " done" : ""}`, "data-rest": it.reviewed || it.rank ? null : "1" },
      el("img", { src: thumb, alt: `Crop of track ${it.name}`, loading: "lazy", onclick: () => zoom(trio, `${it.name}: ${it.reason || ""}${it.has_trio ? " (the three crops Spark saw: early, middle, late)" : ""}`) }),
      el("div", {}, ...body));
  });
  // settle.py: only tracks whose answer can still move a MaxN or a first arrival come first; the server recomputes after
  // every answer, so accepting one can drop others. The rest cannot change any count as things stand.
  const rest = items.filter((x) => x.dataset.rest), head = items.filter((x) => !x.dataset.rest);
  const left = run.n_decisive || 0;
  $("queuePanel").replaceChildren(
    el("h2", {}, "Needs a person",
      el("small", {}, total ? `${run.n_flagged} of ${total} tracks: Spark was unsure, or said it is not the animal.` : "Spark did not audit this run.")),
    run.n_flagged ? el("p", { class: "settle" }, left
      ? [el("b", { class: "num" }, left), ` of them can still change a MaxN or a first arrival; they are first, from the frame with the highest possible count. Each answer can make others irrelevant.`]
      : "Every MaxN and first arrival is settled; the tracks left cannot change a count.") : null,
    ...(items.length ? head : [el("p", { class: "empty" }, total ? `Nothing to check. Spark was confident on all ${total} tracks.` : "")]),
    rest.length ? el("details", { class: "rest" }, el("summary", {}, `${rest.length} more that cannot change a count now (names, or a second opinion)`), ...rest) : null);
}

async function review(track, label) {
  const n = document.getElementById("staticNote");
  if (n) n.textContent = "Static demo: reviews are not saved. Run the server from the repository to review and export.";
}

function zoom(src, cap) {
  $("lbImg").src = src; $("lbCap").textContent = cap; $("lightbox").showModal();
}

// ---------- new run ----------
async function loadClips(select) {
  const { clips } = await api("/api/clips");
  $("clipSel").replaceChildren(...clips.map((c) => el("option", { value: c.name }, `${c.name}  (${c.mb} MB)`)));
  if (select) $("clipSel").value = select;
}

async function upload(file) {
  $("formErr").textContent = `Uploading ${file.name}…`;
  try {
    const safe = file.name.replace(/[^A-Za-z0-9._-]/g, "_").replace(/^[._-]+/, "");
    const r = await api(`/api/clips/${encodeURIComponent(safe)}`, { method: "PUT", body: file });
    await loadClips(r.name);
    $("formErr").textContent = "";
  } catch (e) { $("formErr").textContent = e.message; }
}

function wireForm() {
  const drop = $("drop");
  $("newBtn").onclick = () => {
    const open = $("newRun").hidden;
    $("newRun").hidden = !open; $("newBtn").setAttribute("aria-expanded", open);
    if (open) loadClips();
  };
  $("browse").onclick = () => $("fileIn").click();
  $("fileIn").onchange = () => $("fileIn").files[0] && upload($("fileIn").files[0]);
  drop.ondragover = (e) => { e.preventDefault(); drop.classList.add("over"); };
  drop.ondragleave = () => drop.classList.remove("over");
  drop.ondrop = (e) => { e.preventDefault(); drop.classList.remove("over"); e.dataTransfer.files[0] && upload(e.dataTransfer.files[0]); };
  $("allowApi").onchange = () => {
    $("moneyHint").textContent = $("allowApi").checked
      ? "On: clips not seen before call SAM 3.1 ($0.20 per 1,000 frames, 50 minimum, per word) and Muse Spark. Saved answers are still reused."
      : "Off: replays saved API answers only, free. Clips seen before replay exactly.";
  };
  $("runForm").onsubmit = async (e) => {
    e.preventDefault();
    $("startBtn").disabled = true; $("formErr").textContent = "";
    try {
      const r = await api("/api/run", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          clip: $("clipSel").value, prompts: $("words").value.split(","), discover: $("discover").checked,
          allow_api: $("allowApi").checked, max_usd: parseFloat($("cap").value) || 1, site: $("site").value.trim() || null,
        }),
      });
      $("newRun").hidden = true; $("newBtn").setAttribute("aria-expanded", false);
      await loadRuns(r.id);
    } catch (err) { $("formErr").textContent = err.message; }
    finally { $("startBtn").disabled = false; }
  };
}

$("runSel").onchange = () => openRun($("runSel").value);
$("strip").addEventListener("click", (e) => {
  const b = laneBox();
  if (!b || !state.run) return;
  const [s] = b, p = (e.clientX - s.left) / s.width;
  if (p >= 0 && p <= 1) seek(Math.min(state.n - 1, Math.floor(p * state.n)));
});
["seeked", "timeupdate", "loadedmetadata"].forEach((ev) => $("vid").addEventListener(ev, movePlayhead));
window.addEventListener("resize", movePlayhead);
$("lbClose").onclick = () => $("lightbox").close();
loadRuns();
