// The static demo's first screen: the real boxed frame next to the MaxN table, and one track from the review queue to
// answer right there. Static demo only (demo/build_static.py copies it to static/shot.js; web/ is not touched).
// It is drawn from the same state.run the review screen below draws from: build_static.py hooks drawRun, so a clip
// change, a queue answer or a group rename redraws both. The pure functions are what tests/test_static_review.py checks
// against web/server.py effective() at every review step; draw() only moves their output into the page.
(function (root) {
  "use strict";
  const hidden = (n, m) => m.maxn === 0 && n.endsWith(" (unidentified)");      // app.js hidden()

  function rows(run) {                 // app.js order() and countRow(): the same rows, order and numbers as the panels
    return Object.entries(run.metrics).filter(([n, m]) => !hidden(n, m)).sort(([a, x], [b, y]) =>
      (run.origin[a] === "asked" ? 0 : 1) - (run.origin[b] === "asked" ? 0 : 1) || y.maxn - x.maxn || a.localeCompare(b))
      .map(([n, m]) => ({
        name: n, origin: run.origin[n], big: (m.lower_bound ? "≥" : "") + m.maxn,
        range: m.maxn_confirmed != null && m.maxn_confirmed < (m.maxn_upper ?? m.maxn) ? `${m.maxn_confirmed}–${m.maxn_upper ?? m.maxn}` : null,
        first_time: m.first_time, maxn_time: m.maxn_time, maxn_frame: m.maxn_frame,
        evidence: m.evidence || null, evidence_stale: !!m.evidence_stale,
      }));
  }

  function firstPick(run, show) {      // the row the frame opens on: the clip's featured animal, else the first row
    const rs = rows(run);
    return rs.some((r) => r.name === show) ? show : rs.length ? rs[0].name : null;
  }

  function select(run, name, show) {   // what the frame, its caption and the play button show for a clicked row
    const rs = rows(run);
    const r = rs.find((x) => x.name === name) || rs.find((x) => x.name === firstPick(run, show));   // renamed away: back to the first pick
    if (!r) return null;
    return { name: r.name, big: r.big, time: r.maxn_time, stale: r.evidence_stale,
      img: r.evidence ? `runs/${encodeURIComponent(run.id)}/${encodeURIComponent(r.evidence)}` : null, noFrame: !r.evidence,
      renamed: (run.renames || []).some((x) => x.to === r.name), playFrame: r.maxn_frame };   // app.js renameAll: a rule's .to is the row name
  }

  function nextAsk(run) {              // the queue item the review screen shows first (server order: open, then ranked)
    const q = run.queue || [];
    const it = q.find((x) => !x.reviewed && x.rank != null) || q.find((x) => !x.reviewed);
    if (!it) return null;
    const guess = it.species && it.species !== "unknown" ? it.species.toLowerCase() : it.category;   // app.js drawQueue
    return { track: it.track, name: it.name, thumb: `runs/${encodeURIComponent(run.id)}/${it.thumb.split("/").map(encodeURIComponent).join("/")}`, guess,
      yes: it.yes_label || guess, says: it.is_target === false ? `not a ${it.category}` : (it.species || "unknown"),
      confidence: it.confidence, reason: it.reason || "" };
  }

  function inputLine(run) {
    const secs = run.video && run.video.fps ? Math.round(run.video.n_frames / run.video.fps) : null;
    const words = (run.prompts || []).map((p) => `“${p[1]}”`).join(", ");
    return `Video in: ${secs != null ? `a ${secs} s ` : "a "}deep-sea clip${run.source ? ` (${run.source})` : ""} · told to count: ${words}`;
  }

  // ---- the page (browser only; uses app.js globals: $, el, fill, review, seek, zoom, state) ----
  const cur = { id: null, pick: null };
  const secs = (t) => (t == null ? "–" : `${t.toFixed(1)} s`);

  function draw(run, keepAsk) {
    const body = $("shotRows");
    if (!body) return;
    document.querySelectorAll(".chip[data-run]").forEach((c) => c.setAttribute("aria-pressed", String(!!run && c.dataset.run === run.id)));
    if (!run) {
      fill(body, el("tr", {}, el("td", { colspan: 4 }, "Loading…")));
      fill($("shotAsk")); $("shotInput").textContent = ""; return;
    }
    if (cur.id !== run.id) { cur.id = run.id; cur.pick = firstPick(run, (api.show || {})[run.id]); }
    const sel = select(run, cur.pick, (api.show || {})[run.id]);
    cur.pick = sel ? sel.name : null;
    $("shotInput").textContent = inputLine(run);
    fill(body, ...rows(run).map((r) => el("tr", { class: r.origin === "asked" ? "asked" : "found", "aria-selected": String(!!sel && r.name === sel.name), onclick: () => pick(r.name) },
      el("td", { class: "n" }, el("button", { type: "button", "aria-label": `Show the frame for ${r.name}` }, r.big),
        r.range ? el("small", {}, `${r.range} until checked`) : null),
      el("td", {}, r.name, el("small", {}, r.origin === "asked" ? "asked for" : "not asked for, found")),
      el("td", { class: "t" }, secs(r.first_time)), el("td", { class: "t" }, secs(r.maxn_time)))));
    if (!body.children.length) fill(body, el("tr", {}, el("td", { colspan: 4 }, "Nothing was counted in this clip.")));
    drawFrame(sel);
    if (!keepAsk) drawAsk(run);     // a row click changes nothing in the queue: keep a name being typed there
  }

  function pick(name) {             // redraw, then give the keyboard back to the clicked row's button
    cur.pick = name; draw(state.run, true);
    const b = document.querySelector("#shotRows tr[aria-selected=true] button");
    if (b) b.focus();
  }

  function drawFrame(sel) {
    const img = $("shotImg"), none = $("shotNoFrame"), cap = $("shotCap"), play = $("shotPlay");
    img.hidden = !sel || sel.noFrame; none.hidden = !sel || !sel.noFrame; play.hidden = !sel || sel.playFrame == null;
    if (!sel) { cap.textContent = ""; return; }
    none.textContent = sel.renamed ? `No saved frame for this row (renamed in this page).${sel.playFrame != null ? " Play the clip to see it." : ""}`
      : "No saved frame for this row.";
    if (sel.img) { img.src = sel.img; img.alt = `The frame behind the count for ${sel.name}, boxes as the pipeline drew them`; }
    cap.textContent = sel.time == null ? `${sel.name}: not in any frame now` :
      `${sel.name}: ${sel.big} in this frame, at ${secs(sel.time)}${sel.stale && sel.img ? " (image from before the review)" : ""}`;
    img.onclick = () => zoom(img.src, cap.textContent);
    play.onclick = () => {
      seek(sel.playFrame);
      const v = $("vid");
      v.play().catch(() => {});
      v.scrollIntoView({ behavior: "smooth", block: "center" });
    };
  }

  function drawAsk(run) {
    const it = nextAsk(run), n = (run.queue || []).filter((q) => !q.reviewed).length;
    if (!it) {
      fill($("shotAsk"), el("p", { class: "askhead" }, (run.queue || []).length
        ? "Every track is answered; these counts are settled." : "Spark was sure of every track; nothing waits for a person."));
      return;
    }
    const input = el("input", { value: it.guess || "", required: true, pattern: ".*\\S.*", title: "Type a name (Not an animal removes it)", "aria-label": `New name for ${it.name}` });
    const form = el("form", { class: "rename", hidden: true, onsubmit: (e) => { e.preventDefault(); review(it.track, input.value); } },
      input, el("button", { class: "btn small" }, "Save name"));
    fill($("shotAsk"),
      el("p", { class: "askhead" }, el("b", { class: "num" }, n), ` track${n === 1 ? "" : "s"} wait${n === 1 ? "s" : ""} for a person. Answer one here; the counts above and below change.`),
      el("div", { class: "qline" },
        el("img", { src: it.thumb, alt: `Crop of track ${it.name}`, onclick: () => zoom(it.thumb, `${it.name}: ${it.reason}`) }),
        el("div", {},
          el("div", { class: "said" }, `${it.name}: Spark says `, el("b", {}, it.says),
            it.confidence != null ? `, ${Math.round(it.confidence * 100)}% sure` : ""),
          el("div", { class: "acts" },
            el("button", { class: "btn small", onclick: () => review(it.track, it.yes) }, `Yes, ${it.yes}`),
            el("button", { class: "btn ghost small", onclick: () => { form.hidden = !form.hidden; if (!form.hidden) input.focus(); } }, "Rename"),
            el("button", { class: "btn ghost small", onclick: () => review(it.track, null) }, "Not an animal")),
          form)));
  }

  const api = { rows, firstPick, select, nextAsk, inputLine, draw, pick, show: null };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.StaticShot = api;
})(typeof window !== "undefined" ? window : this);
