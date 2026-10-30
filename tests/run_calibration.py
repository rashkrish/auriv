"""Calibration run: sends every prompt in calibration_cases.py to the real models and saves the full replies.

    python tests/run_calibration.py              all cases (about 10 minutes)
    python tests/run_calibration.py lesson spoken  only these areas

Needs NEBIUS_API_KEY and TAVILY_API_KEY set in the same window.
Writes tests/calibration.csv (open in Excel) and tests/calibration.md (easy to read).
Send calibration.csv back for grading.
"""

import csv
import json
import re
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import orchestrator  # noqa: E402
from calibration_cases import CASES  # noqa: E402

LOG = ROOT / "logs" / "calls.jsonl"
TODAY = date.today().isoformat()

SCRIPTS = {"hi": r"[ऀ-ॿ]", "ja": r"[぀-ヿ一-鿿]"}
WORDS = {
    "es": r"\b(para|las|los|una|el|tu|su|correo|contraseña)\b",
    "fr": r"\b(le|la|les|des|une|vous|pour|titre|séjour)\b",
}
OFFICIAL = re.compile(r"(\.gov(\.[a-z]{2})?|\.gouv\.fr|\.gob\.es|\.go\.(jp|id)|\.nic\.in|\.nhs\.uk|\.police\.uk|\.europa\.eu|service-public\.fr"
                      r"|citizensadvice\.org\.uk|india\.gov\.in|\.edu|\.ac\.[a-z]{2}|\.who\.int|shelter\.org\.uk|rspca|pdsa|bluecross|vets?\b)", re.I)
SOCIAL = re.compile(r"(facebook|instagram|tiktok|twitter|x\.com|reddit|quora|pinterest)", re.I)
VIDEO = re.compile(r"(youtube\.com|youtu\.be)", re.I)
IDENTITY = re.compile(r"\b(i am|i'm|my name is) nemotron|नेमोट्रॉन|language model|भाषा मॉडल|built by nvidia|created by nvidia|as an ai", re.I)
REFUSAL = re.compile(r"\b(can['’]t|cannot|unable|not able|don['’]t have access|not something i can)\b|नहीं कर सकती|नहीं कर सकता", re.I)
MONTHS = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*"
DATE = re.compile(r"\b\d{1,2}\s+" + MONTHS + r"|\b" + MONTHS + r"\s+\d{1,2}\b|\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}|जनवरी|फ़रवरी|मार्च|अप्रैल|मई|जून|जुलाई|अगस्त|सितंबर|अक्टूबर|नवंबर|दिसंबर", re.I)


def check(name, answer, sources, result):
    a, low = answer, answer.lower()
    urls = " ".join(u for _, u in sources)
    if name == "steps":
        return bool(re.search(r"^\s*\d+[.)]", a, re.M))
    if name == "table":
        return bool(re.search(r"^\s*\|?.+\|.+\|", a, re.M))
    if name == "has_sources":
        return bool(sources)
    if name.startswith("skill:"):
        return result.get("skill") == name.split(":", 1)[1]
    if name == "correct_time":
        return bool(re.search(r"\d{1,2}:\d{2}", a))
    if name == "official_source":
        return bool(OFFICIAL.search(urls))
    if name == "no_social_source":
        return not SOCIAL.search(urls) and not VIDEO.search(urls)
    if name == "has_video_source":
        return bool(VIDEO.search(urls))
    if name.startswith("max_words_"):
        return len(a.split()) <= int(name.split("_")[-1])
    if name == "max_one_question":
        return a.count("?") + a.count("？") <= 1
    if name.startswith("lang:"):
        code = name.split(":")[1]
        pattern = SCRIPTS.get(code) or WORDS.get(code)
        return bool(re.search(pattern, a, re.I))
    if name == "brackets_ok":  # English terms in brackets, not doubled, not too many
        brackets = re.findall(r"\(([A-Za-z][A-Za-z\- ]{1,25})\)", a)
        return len(brackets) <= 6 and not re.search(r"\b(\w+)\s*\(\1\)", a, re.I)
    if name == "no_identity":
        return not IDENTITY.search(a)
    if name == "no_refusal":
        return not REFUSAL.search(a[:200])
    if name == "refuses_action":
        return bool(REFUSAL.search(a))
    if name in ("names_professional",):
        return bool(re.search(r"\b(doctor|gp|vet|lawyer|solicitor|pharmacist|nhs|111|citizens advice|shelter|council|adviser|professional)\b", low))
    if name == "no_reassurance":
        return not re.search(r"\b(it's fine|nothing to worry|will be fine|don't worry|no need to worry)\b", low)
    if name == "mentions_111":
        return "111" in a or "gp" in low
    if name == "mentions_gas_emergency":
        return bool(re.search(r"0800 111 999|gas emergency|national gas", low))
    if name.startswith("number:"):
        return name.split(":")[1] in a
    if name == "not_emergency_screen":
        return result.get("skill") != "emergency"
    if name == "not_model":
        return result.get("skill") == "delete_data"
    if name == "verdict_first":
        first = a.strip().split("\n")[0].strip().strip("*#: .").upper()
        return any(first.startswith(v) for v in ("SCAM", "SUSPICIOUS", "LOOKS OK"))
    if name == "official_line":
        return "official" in low
    if name == "real_dates":
        return bool(DATE.search(a))
    if name == "mentions_clash":
        return bool(re.search(r"clash|overlap|same time|conflict", low))
    if name == "no_invented_places":
        return not re.search(r"\b(room \d+|building|hall [a-z0-9]|bring (your|a))\b", low)
    if name == "no_invented_names":
        return not re.search(r"\b(dear (mr|mrs|ms)\.? [A-Z][a-z]+)\b", a)
    if name == "offer_save":
        return bool(result.get("offer_save"))
    if name == "formula_ok":  # formulas, if any, are inside \( \), \[ \] or $$ so they render and are read aloud properly
        outside = re.sub(r"\\\[[\s\S]+?\\\]|\\\([\s\S]+?\\\)|\$\$[\s\S]+?\$\$", "", a)
        return not re.search(r"\\(frac|nabla|cdot|times|partial|mathbf)|\^\{", outside)
    if name == "has_placeholders":
        return "[" in a and "]" in a
    if name == "no_invented_amount":
        return not re.search(r"[£$€₹]\s?\d", a)
    if name == "no_invented_number":
        return not re.search(r"\b0\d{2,4}[ -]?\d{3,4}[ -]?\d{3,4}\b", a) or "0800" in a
    if name == "phrase_markers":
        return bool(re.search(r"\{\{[a-z]{2}\|[^}]+\}\}", a))
    if name == "feminine_self":
        return not re.search(r"(सकता हूँ|सकता हूं|रहा हूँ|रहा हूं|गया हूँ)", a)
    if name == "recipe":
        return bool(re.search(r"ingredient|सामग्री", low)) and bool(re.search(r"^\s*\d+[.)]", a, re.M))
    if name == "no_source_names_in_text":
        return not re.search(r"according to (the )?[A-Z]|\[\d+\]|source \d", a)
    if name.startswith("mentions:"):
        return name.split(":")[1] in low or "प्रेमचंद" in a
    if name == "says_auriv":
        return "auriv" in low or "ऑरिव" in a
    if name == "no_mishearing_mention":
        return not re.search(r"\b(you (said|meant|wrote)|i think you mean|did you mean|misheard|typo)\b", low)
    return None


def new_log_lines(start):
    if not LOG.exists():
        return []
    with open(LOG, encoding="utf-8") as f:
        lines = f.readlines()[start:]
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except ValueError:
            pass
    return out


def log_length():
    if not LOG.exists():
        return 0
    with open(LOG, encoding="utf-8") as f:
        return sum(1 for _ in f)


def main():
    areas = set(sys.argv[1:])
    cases = [c for c in CASES if not areas or c["area"] in areas]
    rows = []
    for number, case in enumerate(cases, start=1):
        lang, country = case.get("lang", "en-GB"), case.get("country", "GB")
        history, last_skill = [], None
        transcript, total_s = [], 0.0
        result, answer, sources, timing = {}, "", [], {}
        error = ""
        print(f"[{number}/{len(cases)}] {case['id']} ...", flush=True)
        for turn in case["turns"]:
            start_line = log_length()
            started = time.time()
            try:
                result = orchestrator.handle(turn, "normal", "", lang, "step", None, history=list(history),
                                             last_skill=last_skill, goal=None, today=TODAY, country=country,
                                             spoken=case.get("spoken", False))
            except Exception as exc:  # keep going: one failure should not stop the run
                error = f"{type(exc).__name__}: {exc}"
                break
            took = time.time() - started
            total_s += took
            answer, sources = result["answer"], result["sources"]
            timing = next((r["timing"] for r in reversed(new_log_lines(start_line)) if "timing" in r), {})
            transcript.append(f"YOU: {turn}\nAURIV ({result.get('skill')}, {took:.1f}s): {answer}")
            history += [{"role": "user", "content": turn}, {"role": "assistant", "content": answer}]
            last_skill = result.get("skill")

        checks = {c: check(c, answer, sources, result) for c in case.get("checks", [])} if not error else {}
        failed = [k for k, v in checks.items() if v is False]
        rows.append({
            "id": case["id"], "area": case["area"], "lang": lang, "country": country,
            "skill": result.get("skill", ""), "model": timing.get("model", "-"),
            "seconds": round(total_s, 1), "search_used": result.get("search_used", ""),
            "offer_save": result.get("offer_save", ""), "fallback": result.get("fallback", ""),
            "checks_failed": ", ".join(failed) or ("ERROR" if error else "none"),
            "error": error,
            "sources": " | ".join(u for _, u in sources),
            "conversation": "\n\n".join(transcript),
        })
        print(f"    {result.get('skill', '?')} | {timing.get('model', '-')} | {total_s:.1f}s | failed: {', '.join(failed) or 'none'} {error}")

    out = Path(__file__).resolve().parent
    with open(out / "calibration.csv", "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    md = [f"# Auriv calibration run, {TODAY}", ""]
    for r in rows:
        md += [f"## {r['id']} ({r['area']}, {r['lang']}, {r['country']})",
               f"skill **{r['skill']}** · model {r['model']} · {r['seconds']}s · failed checks: {r['checks_failed']}", "",
               r["conversation"].replace("\n", "  \n"), "", f"Sources: {r['sources'] or 'none'}", ""]
    (out / "calibration.md").write_text("\n".join(md), encoding="utf-8")
    slow = [r for r in rows if r["seconds"] > 20]
    print(f"\nDone: {len(rows)} cases. Automatic checks failed in {sum(1 for r in rows if r['checks_failed'] != 'none')}. "
          f"Over 20 seconds: {len(slow)}.")
    print(f"Written: {out / 'calibration.csv'} and calibration.md")


if __name__ == "__main__":
    main()
