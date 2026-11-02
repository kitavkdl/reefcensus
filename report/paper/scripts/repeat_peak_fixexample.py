"""Test of one suspected cause (written before the calls, 2 Nov 2026): on the V6 frame-35 sheet (run eval7) Spark called
the faint fish "other fish" in 4 of 25 calls although the A4 question asks about "fish". The question's examples of a
different animal read "part of an eel, hagfish or fish". This script sends the identical sheet with only that phrase
changed to "part of an eel or hagfish", 25 times without the cache, and saves the replies. Tallied by
repeat_peak_score.py (row "V6, example without 'fish'"); prediction if the example is the cause: "other fish" ~0 of 25.
  FISH_BUDGET=<cap> python3 report/paper/scripts/repeat_peak_fixexample.py --n 25"""
import argparse, ast, json, os, subprocess, sys
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
from fishcount import api  # noqa: E402
OUT = os.path.join(ROOT, "report/paper/data/repeat_peak_f35_fixexample.json")
OLD, NEW = "part of an eel, hagfish or fish", "part of an eel or hagfish"


def prompt_at(commit):
    src = subprocess.run(["git", "-C", ROOT, "show", f"{commit}:fishcount/pipeline.py"], capture_output=True, text=True).stdout
    for node in ast.parse(src).body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "VERIFY_PROMPT" for t in node.targets):
            return ast.literal_eval(node.value)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--n", type=int, default=25); a = ap.parse_args()
    base = prompt_at("acd979a")
    assert base.count(OLD) == 1
    pr = base.replace(OLD, NEW).format(name="fish")
    sheet = open(os.path.join(ROOT, "runs", "eval7_fish_20190618_9", "verify_striped_seabream_f35_1.jpg"), "rb").read()
    content = [{"type": "text", "text": pr}, {"type": "image_url", "image_url": {"url": api.img_data_url(sheet)}}]
    p = {"model": api.SPARK_MODEL, "messages": [{"role": "user", "content": content}], "max_tokens": 6000,
         "reasoning_effort": "low"}
    out = json.load(open(OUT)) if os.path.exists(OUT) else {"prompt_change": [OLD, NEW], "repeats": []}
    import requests
    while len(out["repeats"]) < a.n:
        api._guard(0.02)
        r = requests.post(f"{api.BASE}/chat/completions", headers={"Authorization": f"Bearer {api._key()}"}, json=p,
                          timeout=(30, 300))
        r.raise_for_status()
        j = r.json(); u = j.get("usage") or {}
        api._log("spark", u.get("prompt_tokens", 0) * api.SPARK_IN + u.get("completion_tokens", 0) * api.SPARK_OUT,
                 f"paper repeat_peak fixexample in={u.get('prompt_tokens')} out={u.get('completion_tokens')}")
        out["repeats"].append(j["choices"][0]["message"]["content"] or "")
        json.dump(out, open(OUT, "w"), indent=1)        # saved after every call
        print(len(out["repeats"]), out["repeats"][-1][-160:].replace("\n", " "), flush=True)


main()
