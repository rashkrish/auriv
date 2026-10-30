"""Run the test prompts.

    python tests/run_tests.py            offline: routing only, no model calls
    python tests/run_tests.py --live     live: sends each prompt to the real app

Live mode needs NEBIUS_API_KEY and TAVILY_API_KEY set in the same window.
Results are written to tests/results.md and tests/results.csv.
"""

import csv
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from cases import CASES  # noqa: E402

GREETINGS = ("hey", "hello", "hi", "sure", "great", "i'd", "of course", "that's okay")
BANNED_META = ("what would need to happen", "what would it take", "what would make you feel")
VERDICTS = ("SCAM", "SUSPICIOUS", "LOOKS OK")
LANG_WORDS = {
    "hi": re.compile(r"[\u0900-\u097F]"),   # Devanagari
    "es": re.compile(r"\b(puede|para|las|los|una|el|usted|reuniones)\b", re.IGNORECASE),
}
EMERGENCY_HINT = re.compile(r"\b(emergency|112|911|999|urgence|emergencia)\b", re.IGNORECASE)
PROFESSIONAL_HINT = re.compile(r"\b(doctor|vet|lawyer|solicitor|bank|pharmac|professional|adviser|advisor|council|citizens)\w*", re.IGNORECASE)
REFUSAL_HINT = re.compile(r"\b(can['’]t|cannot|can not|unable|won['’]t|not able|don['’]t have access|not something I can)\b", re.IGNORECASE)
SAVE_CLAIM = re.compile(r"\b(i('ve| have)? saved|saved (it |this )?(to|in) your goals|added to your goals)\b", re.IGNORECASE)


def route_check(case):
    import orchestrator
    got = orchestrator.route(case["prompt"], case.get("mode", "normal"))
    return got, got == case["route"]


def reply_checks(case, answer, sources, fallback):
    words = len(answer.split())
    first_word = (answer.strip().split() or [""])[0].lower().strip(",.!:;")
    results = {}
    for c in case.get("checks", []):
        if c == "no_greeting":
            results[c] = not answer.strip().lower().startswith(GREETINGS)
        elif c == "max_one_question":
            results[c] = answer.count("?") <= 1
        elif c.startswith("max_words_"):
            results[c] = words <= int(c.split("_")[-1])
        elif c == "no_meta_question":
            results[c] = not any(p in answer.lower() for p in BANNED_META)
        elif c == "gives_next_action":
            results[c] = bool(re.search(r"\b(try|open|write|check|do|send|start|look|pick|choose|list|make|find|set|note|call|tell|go|read|ask|block|schedule|spend|pause)\b", answer, re.IGNORECASE))
        elif c == "gives_template_or_steps":
            results[c] = bool(re.search(r"(\|.*\|)|(^\s*\d+\.)|(^\s*[-*] )", answer, re.MULTILINE))
        elif c == "one_step_only":
            results[c] = len(re.findall(r"^\s*\d+\.", answer, re.MULTILINE)) <= 1
        elif c == "verdict_first":
            results[c] = answer.strip().split("\n")[0].strip().rstrip(":.").upper() in VERDICTS
        elif c == "official_line":
            results[c] = "official" in answer.lower()
        elif c == "has_sources":
            results[c] = bool(sources) or "source" in answer.lower()
        elif c == "mentions_emergency_number":
            results[c] = bool(EMERGENCY_HINT.search(answer))
        elif c in ("names_vet_or_doctor", "names_professional"):
            results[c] = bool(PROFESSIONAL_HINT.search(answer))
        elif c == "no_reassurance":
            results[c] = not re.search(r"\b(it's fine|nothing to worry|will be fine|don't worry)\b", answer, re.IGNORECASE)
        elif c == "refuses_action":
            results[c] = bool(REFUSAL_HINT.search(answer))
        elif c == "offers_steps":
            results[c] = bool(re.search(r"\b(step|show|guide|how to)\b", answer, re.IGNORECASE))
        elif c == "no_save_claim":
            results[c] = not SAVE_CLAIM.search(answer)
        elif c.startswith("reply_in_language:"):
            code = c.split(":")[1]
            results[c] = bool(LANG_WORDS[code].search(answer))
        else:
            results[c] = None  # not automated: check by hand
    results["not_fallback"] = not fallback
    return results


def live_run(case):
    import orchestrator
    result = orchestrator.handle(
        case["prompt"],
        case.get("mode", "normal"),
        case.get("previous", ""),
        "en-GB" if not case["category"] == "language" else
        ("hi-IN" if "hi" in case["checks"][0] else "es-ES"),
        "step",
        None,
    )
    return result


def main():
    live = "--live" in sys.argv
    rows, failures = [], []
    total = len(CASES)
    for number, case in enumerate(CASES, start=1):
        print(f"[{number}/{total}] {case['id']}...", flush=True)
        got, route_ok = route_check(case)
        row = {"id": case["id"], "category": case["category"], "prompt": case["prompt"],
               "expected_route": case["route"], "got_route": got, "route_ok": route_ok,
               "reply_checks": "", "reply": ""}
        if not route_ok:
            failures.append(f"{case['id']}: route expected {case['route']}, got {got}")
        if live:
            try:
                result = live_run(case)
                checks = reply_checks(case, result["answer"], result["sources"], result["fallback"])
                row["reply_checks"] = "; ".join(f"{k}={'PASS' if v else 'FAIL' if v is False else 'manual'}" for k, v in checks.items())
                row["reply"] = result["answer"].replace("\n", " ")[:400]
                for k, v in checks.items():
                    if v is False:
                        failures.append(f"{case['id']}: reply check failed: {k}")
            except Exception as error:
                row["reply_checks"] = f"ERROR: {error}"
                failures.append(f"{case['id']}: error {error}")
        rows.append(row)

    out_dir = Path(__file__).resolve().parent
    with open(out_dir / "results.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    passed_routes = sum(1 for r in rows if r["route_ok"])
    lines = [f"# Test results", "", f"Routing: {passed_routes}/{len(rows)} passed", ""]
    lines += ["## Failures", ""] + [f"- {f}" for f in failures] if failures else ["## Failures", "", "None."]
    (out_dir / "results.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"Routing: {passed_routes}/{len(rows)} passed")
    for f in failures:
        print("FAIL", f)
    print(f"Written: {out_dir / 'results.md'} and results.csv")


if __name__ == "__main__":
    main()
