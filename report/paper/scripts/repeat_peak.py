"""Repeat the A4 peak-frame judgement on the saved sheets of luderick 20190618_9 frame 35 (the faint-fish case),
V4 layout (run eval5, code 3ea6a8c) vs V5 layout (run eval6, code 53e690a), N fresh calls each, to separate the
layout effect from run-to-run nondeterminism (11/2 review item 5).
  python3 report/paper/scripts/repeat_peak.py --check      # prove the saved sheet + prompt hit the original cache
  FISH_BUDGET=<cap> python3 report/paper/scripts/repeat_peak.py --n 5   # live, uncached; replies saved to JSON"""
import argparse, ast, hashlib, json, os, subprocess, sys, time
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
from fishcount import api  # noqa: E402

CASES = [("V4", "3ea6a8c", "eval5_fish_20190618_9"), ("V5", "53e690a", "eval6_fish_20190618_9")]
OUT = os.path.join(ROOT, "report/paper/data/repeat_peak_f35.json")


def prompt_at(commit):
    src = subprocess.run(["git", "-C", ROOT, "show", f"{commit}:fishcount/pipeline.py"], capture_output=True, text=True).stdout
    for node in ast.parse(src).body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "VERIFY_PROMPT" for t in node.targets):
            return ast.literal_eval(node.value)
    raise SystemExit(f"no VERIFY_PROMPT at {commit}")


def payload(prompt, sheet):
    content = [{"type": "text", "text": prompt}, {"type": "image_url", "image_url": {"url": api.img_data_url(sheet)}}]
    p = {"model": api.SPARK_MODEL, "messages": [{"role": "user", "content": content}], "max_tokens": 6000}
    p["reasoning_effort"] = "low"
    return p


def fresh(p):
    import requests
    api._guard(0.02)
    r = requests.post(f"{api.BASE}/chat/completions", headers={"Authorization": f"Bearer {api._key()}"}, json=p, timeout=(30, 300))
    r.raise_for_status()
    j = r.json(); u = j.get("usage") or {}
    api._log("spark", u.get("prompt_tokens", 0) * api.SPARK_IN + u.get("completion_tokens", 0) * api.SPARK_OUT,
             f"paper repeat_peak in={u.get('prompt_tokens')} out={u.get('completion_tokens')}")
    return j["choices"][0]["message"]["content"] or ""


def cases():
    for v, commit, run in CASES:
        sheet = open(os.path.join(ROOT, "runs", run, "verify_striped_seabream_f35_1.jpg"), "rb").read()
        base = prompt_at(commit)
        for word in ("striped seabream", "fish"):
            pr = base.format(name=word)
            cp = api._cache_path("spark", payload(pr, sheet))
            if os.path.exists(cp):
                yield v, run, pr, sheet, cp
                break
        else:
            yield v, run, None, sheet, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--n", type=int, default=5)
    a = ap.parse_args()
    found = list(cases())
    for v, run, pr, sheet, cp in found:
        print(v, run, "cache hit" if cp else "NO CACHE MATCH", (json.load(open(cp))["text"][:400] if cp else ""))
    if a.check or not all(cp for *_, cp in found):
        return
    out = json.load(open(OUT)) if os.path.exists(OUT) else {}
    for v, run, pr, sheet, cp in found:
        out.setdefault(v, {"run": run, "original": json.load(open(cp))["text"], "repeats": []})
        for i in range(a.n):
            text = fresh(payload(pr, sheet))      # the identical payload, sent again without the cache
            out[v]["repeats"].append(text)
            print(v, i, text[:300].replace("\n", " "))
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, "w"), indent=1)


main()
