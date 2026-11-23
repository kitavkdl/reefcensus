// Review in the static demo, with no server: web/server.py effective(), export_csv() and fishcount/maxn_export.to_csv()
// recomputed in the browser from the run's stored frames, after each edit. Same rules as fishcount/tracks.metrics,
// fishcount/settle.decisive and fishcount/pipeline.group_metrics; tests/test_static_review.py applies the same review
// steps to every demo run here (with node) and through the server code, and checks the JSON and both CSVs agree.
// Edits live in memory only (a reload starts again). demo/build_static.py writes `_static` into each run's JSON:
// frames, base metrics, time strings as Python prints them, the queued tracks, the "Yes" label of each, the queue cards.
(function (root) {
  "use strict";
  const has = (o, k) => Object.prototype.hasOwnProperty.call(o, k);
  const cmp = (a, b) => (a < b ? -1 : a > b ? 1 : 0);
  const PLACE = ["on", "at", "in", "near", "by", "under", "over", "with", "from", "behind", "inside", "beside", "among"];
  const VAGUE = ["none", "unknown", "animal", "creature", "thing", "object", "organism", "unclear"];
  const words = (s) => (s || "").toLowerCase().replace(/[^a-z ]/g, " ").split(" ").filter(Boolean);

  function normLabel(name) {           // pipeline.norm_label
    const ws = words(name);
    if (!ws.length) return null;
    let w = ws[ws.length - 1];
    if (VAGUE.includes(w)) return null;
    if (w.length > 4 && w.endsWith("ies")) w = w.slice(0, -3) + "y";
    else if (w.length > 5 && w.endsWith("uses") && !"aeiou".includes(w[w.length - 5])) w = w.slice(0, -2);
    else if (w.length > 4 && /(shes|ches|xes)$/.test(w)) w = w.slice(0, -2);
    else if (w.length > 3 && w.endsWith("s") && !/(ss|us|is)$/.test(w)) w = w.slice(0, -1);
    return w;
  }
  function head(name) {                // pipeline._head
    let ws = words(name);
    const i = ws.findIndex((w) => PLACE.includes(w));
    if (i >= 0) ws = ws.slice(0, i);
    return normLabel(ws.join(" "));
  }
  function groupOfWord(w, groupOf) {   // pipeline._group_of_word: the table, else a longer "...fish"/"...shark" word
    if (!w) return null;
    if (has(groupOf, w)) return groupOf[w];
    if (w.length > 5 && /(fish|shark)$/.test(w) && w !== "shellfish" && !w.startsWith("non")) return "fish";
    return null;
  }
  function nameGroup(name, groupOf) {  // pipeline.name_group (a negated phrase, pipeline._NEGATED, names no animal)
    name = (name || "").toLowerCase().replace(/\bno-([a-z]+)/g,
      (m, w) => (groupOfWord(normLabel(w), groupOf) ? "no " + w : m)).replace(
      /\bnon-?[a-z]*|\b(?:not\b|no\b(?!-))(?:(?!\b(?:but|only|rather|instead|however|though|although|except|yet|just)\b)[^,;.()/])*/g, " ");
    const g = groupOfWord(head(name), groupOf);
    if (g) return g;
    for (const w of words(name)) {
      const n = groupOfWord(normLabel(w), groupOf);
      if (n) return n;
    }
    return null;
  }
  const apiSafe = (s) => Array.from(s).map((ch) => (/[\p{L}\p{N}]/u.test(ch) ? ch : "_")).join("");

  function metrics(S, tracks, labels) {   // tracks.metrics
    const lab = (t) => (has(tracks, t) ? (has(labels, t) ? labels[t] : tracks[t].label) : null);
    const names = [...new Set(Object.keys(tracks).map(lab).filter(Boolean))].sort(cmp);
    const n = S.n_frames, curve = {}, alive = new Set();
    for (const nm of names) curve[nm] = new Array(n).fill(0);
    for (const [fk, ks] of Object.entries(S.frames)) {
      for (const k of ks) alive.add(k.track);
      const f = +fk;
      if (f >= n) continue;
      for (const k of ks) { const l = lab(k.track); if (l) curve[l][f] += 1; }
    }
    const out = {};
    for (const nm of names) {
      const c = curve[nm], m = c.length ? Math.max(...c) : 0, first = c.findIndex((v) => v);
      out[nm] = { maxn: m, maxn_frame: m ? c.indexOf(m) : null, maxn_time: m ? S.times[c.indexOf(m)] : null,
        first_frame: first >= 0 ? first : null, first_time: first >= 0 ? S.times[first] : null,
        tracks: Object.keys(tracks).filter((t) => lab(t) === nm && alive.has(t)).length, curve: c };
    }
    return out;
  }

  function groupMetrics(S, m, minLabels) {   // pipeline.group_metrics
    const groups = {};
    for (const name of Object.keys(m)) {
      const g = nameGroup(name, S.group_of);
      if (g) (groups[g] = groups[g] || []).push(name);
    }
    const out = {};
    for (const g of Object.keys(groups).sort(cmp)) {
      const names = groups[g];
      if (names.length < minLabels) continue;
      const n = Math.max(...names.map((x) => m[x].curve.length));
      const c = Array.from({ length: n }, (_, i) => names.reduce((s, x) => s + (i < m[x].curve.length ? m[x].curve[i] : 0), 0));
      const top = c.length ? Math.max(...c) : 0;
      const firsts = names.map((x) => m[x].first_frame).filter((f) => f != null);
      const first = firsts.length ? Math.min(...firsts) : null;
      out[g] = { labels: [...names].sort(cmp), maxn: top, maxn_frame: top ? c.indexOf(top) : null,
        maxn_time: top ? S.times[c.indexOf(top)] : null, first_frame: first, first_time: first != null ? S.times[first] : null,
        tracks: names.reduce((s, x) => s + m[x].tracks, 0), curve: c };
    }
    return out;
  }

  function renamed(name, rules) {      // settle.renamed: group renames in order (a -> b then b -> c makes a c)
    for (const r of rules || []) if (name != null && name === r.from) name = r.to;
    return name;
  }

  function decisive(run, review, rules) {     // settle.decisive
    const S = run._static;
    let labels = { ...run.auto_labels, ...review };
    if (rules && rules.length) labels = Object.fromEntries(Object.entries(labels).map(([t, l]) => [t, renamed(l, rules)]));
    const openQ = new Set(S.queued.filter((t) => !has(review, t)));
    const sure = {}, maybe = {}, firstSure = {}, firstTrack = {};
    for (const [fk, ks] of Object.entries(S.frames)) {
      const f = +fk;
      for (const k of ks) {
        const t = k.track;
        if (openQ.has(t)) {
          const L = renamed(S.accept[t], rules);
          ((maybe[L] = maybe[L] || {})[f] = maybe[L][f] || new Set()).add(t);
          firstTrack[t] = Math.min(has(firstTrack, t) ? firstTrack[t] : f, f);
        } else if (labels[t]) {
          const L = labels[t];
          (sure[L] = sure[L] || {})[f] = (sure[L][f] || 0) + 1;
          firstSure[L] = Math.min(has(firstSure, L) ? firstSure[L] : f, f);
        }
      }
    }
    const score = {}, better = (a, b) => (a[0] !== b[0] ? a[0] > b[0] : a[1] > b[1]);
    for (const [L, fr] of Object.entries(maybe)) {
      const sL = sure[L] || {}, frames = new Set([...Object.keys(fr), ...Object.keys(sL)]);
      const low = Math.max(0, ...[...frames].map((f) => sL[f] || 0));
      for (const [fk, ts] of Object.entries(fr)) {
        const up = (sL[fk] || 0) + ts.size, s = [up, -fk];
        if (up > low) for (const t of ts) if (!has(score, t) || better(s, score[t])) score[t] = s;
      }
      for (const ts of Object.values(fr))
        for (const t of ts)
          if (!has(score, t) && firstTrack[t] < (has(firstSure, L) ? firstSure[L] : Infinity)) score[t] = [0, -firstTrack[t]];
    }
    const ranked = Object.keys(score).sort((a, b) =>
      (score[b][0] - score[a][0]) || (score[b][1] - score[a][1]) || (firstTrack[a] - firstTrack[b]) || cmp(a, b));
    const out = {};
    ranked.forEach((t, i) => { out[t] = i + 1; });
    return out;
  }

  function effective(run, review, rules = run.renames || []) {    // web/server.py effective(), for a run with no site memory
    const S = run._static;
    let labels = { ...run.auto_labels, ...review };
    // group renames (renameGroup): every track's final name goes through them; the queued tracks a rename marked
    // reviewed count as reviewed until it is undone, unless the track was reviewed itself
    const accepted = new Set(rules.flatMap((r) => r.accept || []).filter((t) => !has(review, t)));
    const before = Object.fromEntries(Object.entries(run.tracks).map(([t, v]) => [t, has(labels, t) ? labels[t] : v.label]));
    if (rules.length) labels = Object.fromEntries(Object.entries(before).map(([t, l]) => [t, renamed(l, rules)]));
    const yes = (t) => renamed(S.accept[t], rules);
    const nRev = Object.keys(review).length, edited = nRev > 0 || rules.length > 0;
    const m = edited ? metrics(S, run.tracks, labels) : JSON.parse(JSON.stringify(S.base_metrics));
    const openQ = S.queued.filter((t) => !has(review, t) && !accepted.has(t));
    let lo = {}, hi = {};
    if (openQ.length) {
      const l2 = { ...labels }, l3 = { ...labels };
      for (const t of openQ) { l2[t] = null; l3[t] = yes(t); }
      lo = metrics(S, run.tracks, l2);
      hi = metrics(S, run.tracks, l3);
    }
    const checked = new Set((run.peak_checks || []).map((c) => `${c.label}\u0000${c.frame}`));
    // a box whose one SAM mask fell into n separate blobs nobody split (fishcount/split.py "blobs") is n in the upper end
    const wide = {};
    if (Object.values(S.frames).some((ks) => ks.some((k) => has(k, "blobs")))) {
      const up = { ...labels };
      for (const t of openQ) up[t] = yes(t);
      for (const ks of Object.values(S.frames)) {
        const c = {};
        for (const k of ks) {
          const l = has(up, k.track) ? up[k.track] : (has(run.tracks, k.track) ? run.tracks[k.track].label : null);
          if (l) c[l] = (c[l] || 0) + (has(k, "blobs") ? k.blobs : 1);
        }
        for (const [l, n] of Object.entries(c)) wide[l] = Math.max(wide[l] || 0, n);
      }
    }
    const anyWide = Object.keys(wide).length > 0;
    for (const [name, mm] of Object.entries(m)) {
      mm.maxn_confirmed = openQ.length ? (has(lo, name) ? lo[name].maxn : 0) : mm.maxn;
      mm.maxn_upper = openQ.length || anyWide
        ? Math.max(mm.maxn, has(hi, name) ? hi[name].maxn : 0, wide[name] || 0) : mm.maxn;
      if (openQ.length && JSON.stringify(has(lo, name) ? lo[name].curve : null) !== JSON.stringify(mm.curve))
        mm.curve_confirmed = has(lo, name) ? lo[name].curve : new Array(mm.curve.length).fill(0);
      mm.peak_checked = checked.has(`${name}\u0000${mm.maxn_frame}`);
      const ev = `evidence_${apiSafe(name)}.jpg`, runM = S.base_metrics[name] || {};
      if (edited && (runM.maxn !== mm.maxn || runM.maxn_frame !== mm.maxn_frame)) mm.evidence_stale = true;  // no clip here to redraw from
      mm.evidence = S.evidence.includes(ev) ? ev : null;
    }
    const gm = groupMetrics(S, m, 2), glo = openQ.length ? groupMetrics(S, lo, 1) : {};
    for (const [g, gg] of Object.entries(gm)) gg.maxn_confirmed = openQ.length ? (has(glo, g) ? glo[g].maxn : 0) : gg.maxn;
    for (const c of run.crowd_checks || []) {
      if (!c.lower_bound) continue;
      // after a group rename the checked labels go by their new names: a row only renamed keeps its mark
      const names = rules.length ? [...new Set(c.labels.map((l) => renamed(l, rules)))].sort() : c.labels;
      const row = gm[c.row] || (names.length === 1 ? m[names[0]] : null);
      if (row && row.maxn === c.maxn) Object.assign(row, { lower_bound: true, crowd_total: c.total, crowd_frame: c.frame });
    }
    const acc = {};
    for (const t of accepted) acc[t] = has(before, t) ? before[t] : null;   // counted under its row's name, not its "Yes" name
    const rank = decisive(run, { ...acc, ...review }, rules), queued = new Set(S.queued), queue = [];
    for (const t of S.verdict_order) {
      if (!queued.has(t) && !has(review, t)) continue;
      queue.push({ ...S.cards[t], reviewed: has(review, t) || accepted.has(t), label: has(labels, t) ? labels[t] : null,
        rank: has(rank, t) ? rank[t] : null, yes_label: yes(t) });
    }
    queue.sort((a, b) => (a.reviewed - b.reviewed) || ((a.rank == null) - (b.rank == null)) || ((a.rank || 0) - (b.rank || 0)));
    const asked = new Set((run.jobs || []).map((j) => j.name)), origin = {};
    const counts = rules.map(() => 0);              // settle.renamed_counts: tracks each rule renamed, in order
    for (let l of Object.values(before))
      rules.forEach((r, i) => { if (l != null && l === r.from) { l = r.to; counts[i]++; } });
    for (const [t, v] of Object.entries(run.tracks)) {
      const l = has(labels, t) ? labels[t] : v.label;
      if (l) origin[l] = asked.has(v.source) || origin[l] === "asked" ? "asked" : "found";
    }
    return { ...run, metrics: m, group_metrics: gm, origin, queue, review, renames: rules.map((r, i) => ({ ...r, tracks: counts[i] })), n_renames: rules.length, n_reviewed: nRev,
      n_flagged: queue.filter((q) => !q.reviewed).length, n_decisive: Object.keys(rank).length };
  }

  // web/server.py _save_review: one edit; "__undo__" removes it, null = not an animal, else the label (trimmed, lowercased)
  function review(run, track, label) {
    if (!has(run.tracks, track)) throw new Error(`unknown track ${track}`);
    const r = { ...(run.review || {}) };
    if (label === "__undo__") delete r[track];
    else r[track] = label == null ? null : (Array.from(String(label).trim().toLowerCase()).slice(0, 60).join("") || null);
    return effective(run, r);
  }

  // web/server.py rename_group: {from, to, accept} adds a rule, {undo: id} removes one; the review is left as it is
  function renameGroup(run, body) {
    let rules = run.renames || [];
    if (has(body, "undo")) {
      if (!rules.some((r) => r.id === body.undo)) throw new Error("no such rename");
      rules = rules.filter((r) => r.id !== body.undo);
    } else {
      const frm = body.from, to = Array.from(String(body.to || "").trim().toLowerCase()).slice(0, 60).join("");
      if (!has(run.metrics, frm)) throw new Error(`no row named ${frm}`);
      if (!to || to === frm) throw new Error("give a new name");
      const accept = body.accept ? run.queue.filter((q) => !q.reviewed && q.label === frm).map((q) => q.track).sort() : [];
      rules = [...rules, { id: Math.random().toString(16).slice(2, 10), at: Math.round(Date.now() / 1000), accept, from: frm, to }];
    }
    return effective(run, run.review || {}, rules);
  }

  // Python csv.writer (QUOTE_MINIMAL) cells: None -> "", True/False as Python prints them; floats come as Python strings
  const csvCell = (v) => {
    v = v == null ? "" : v === true ? "True" : v === false ? "False" : String(v);
    return /[",\r\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v;
  };
  const csv = (rows, eol) => rows.map((r) => r.map(csvCell).join(",") + eol).join("");
  // server/maxn_export cell(): note Python's `"" in "=+-@"` is True, so an empty string also gets the quote mark
  const noFormula = (v) => (typeof v === "string" && "=+-@".includes(v.slice(0, 1)) ? "'" + v : v);
  const tstr = (S, f) => (f == null ? null : S.times_str[f]);
  const byMaxn = (o) => Object.entries(o).sort(([, a], [, b]) => b.maxn - a.maxn);

  function exportCsv(e) {             // web/server.py export_csv
    const S = e._static, rows = [["label", "origin", "maxn", "maxn_confirmed", "maxn_upper", "maxn_time_s", "maxn_frame", "first_arrival_s", "tracks",
      "peak_frame_checked", "evidence_frame", "source", "human_edits"]];
    for (const [name, m] of byMaxn(e.metrics)) {
      if (m.maxn === 0 && name.endsWith(" (unidentified)")) continue;
      rows.push([noFormula(name), e.origin[name] || "", m.maxn, m.maxn_confirmed, m.maxn_upper, tstr(S, m.maxn_frame), m.maxn_frame,
        tstr(S, m.first_frame), m.tracks, m.peak_checked, m.evidence || "", e.source, e.n_reviewed + (e.n_renames || 0)]);
    }
    for (const [g, m] of byMaxn(e.group_metrics || {}))
      rows.push([noFormula(`all ${g}` + (g === "fish" ? "" : "s")), "group: " + m.labels.join(" + "), m.maxn, m.maxn_confirmed, "",
        tstr(S, m.maxn_frame), m.maxn_frame, tstr(S, m.first_frame), m.tracks, "", "", e.source, e.n_reviewed + (e.n_renames || 0)]);
    return csv(rows, "\r\n");
  }

  function globalArchiveCsv(e) {      // fishcount/maxn_export.to_csv, default OpCode
    const S = e._static, rows = [S.ga_columns];
    const lower = (name, m) => {
      const cand = [[name, m], ...Object.entries(e.group_metrics || {}).filter(([, gg]) => (gg.labels || []).includes(name))];
      for (const [row, r] of cand)
        if (r.lower_bound) return `yes (${row}): Spark counts about ${r.crowd_total} in frame ${r.crowd_frame} without boxes`;
      return "";
    };
    const ms = Object.entries(e.metrics).sort(([a, x], [b, y]) => (y.maxn - x.maxn) || cmp(a, b));
    for (const [name, m] of ms) {
      if (m.maxn <= 0) continue;
      rows.push([noFormula(S.opcode), "", "", "", m.maxn, m.maxn_frame, m.maxn_frame == null ? null : S.mins_str[m.maxn_frame],
        noFormula(name), has(m, "maxn_confirmed") ? m.maxn_confirmed : m.maxn, e.origin[name] || "",
        "not verified: common name from Muse Spark or a reviewer", noFormula(e.source || ""), e.id || "", (e.n_reviewed || 0) + (e.n_renames || 0), lower(name, m),
        has(m, "maxn_upper") ? m.maxn_upper : m.maxn]);
    }
    return csv(rows, "\n");
  }

  function download(name, text) {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([text], { type: "text/csv" }));
    a.download = name;
    document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }

  // the page keeps one edited copy per run, so switching clips and back keeps the edits until a reload
  const kept = {};
  const api = {
    open: (run) => kept[run.id] || run,
    review: (run, track, label) => (kept[run.id] = review(run, track, label)),
    renameGroup: (run, body) => (kept[run.id] = renameGroup(run, body)),
    effective, exportCsv, globalArchiveCsv, download, nameGroup,
  };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.StaticReview = api;
})(typeof window !== "undefined" ? window : globalThis);
