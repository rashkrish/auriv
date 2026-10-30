"""Web server for the Personal Capability Agent.

Run with:  python server.py
Then open http://127.0.0.1:5000 in Chrome or Edge.
"""

import json
import re
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

import yaml

import memory
import orchestrator

BASE = Path(__file__).parent
STATIC = BASE / "static"
LOG_DIR = BASE / "logs"
LOG_DIR.mkdir(exist_ok=True)

MAX_MESSAGE_CHARS = 2000
MAX_PREVIOUS_CHARS = 3000
MAX_HISTORY_TURNS = 8        # recent messages sent back for context
MAX_HISTORY_CHARS = 1500     # per message
ALLOWED_RATINGS = {"helpful", "not_right", "confusing"}


def clean_history(raw):
    """Keep only well-formed recent turns. Nothing here is stored on the server."""
    turns = []
    for item in (raw or [])[-MAX_HISTORY_TURNS:]:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = item.get("content")
        if role in ("user", "assistant") and isinstance(content, str) and content.strip():
            turns.append({"role": role, "content": content.strip()[:MAX_HISTORY_CHARS]})
    return turns


def clean_goal(raw):
    """The goal the person chose to continue, sent by the page. Text only, length-limited."""
    if not isinstance(raw, dict) or not isinstance(raw.get("title"), str) or not raw["title"].strip():
        return None
    steps = raw.get("steps_done", 0)
    checklist = []
    for st in (raw.get("steps") if isinstance(raw.get("steps"), list) else [])[:10]:
        if isinstance(st, dict) and isinstance(st.get("text"), str) and st["text"].strip():
            checklist.append({"text": st["text"].strip()[:200], "due": str(st.get("due") or "")[:10], "done": bool(st.get("done"))})
    return {
        "title": raw["title"].strip()[:120],
        "next_step": str(raw.get("next_step") or "").strip()[:300],
        "steps_done": steps if isinstance(steps, int) and 0 <= steps < 10000 else 0,
        "due": str(raw.get("due") or "")[:10],
        "steps": checklist,
    }

web = Flask(__name__, static_folder=None)

# A public demo spends the owner's API credits, so each visitor gets a fair number of model requests.
# Limits can be changed with environment variables. Emergencies and fixed answers are never blocked.
import os
import time as _time
from collections import defaultdict, deque

RATE_LIMIT = int(os.environ.get("AURIV_RATE_LIMIT", "40"))          # model requests per visitor...
RATE_WINDOW = int(os.environ.get("AURIV_RATE_WINDOW", "600"))       # ...per 10 minutes
_recent = defaultdict(deque)


def _visitor():
    forwarded = request.headers.get("X-Forwarded-For", "")
    return forwarded.split(",")[0].strip() or request.remote_addr or "unknown"


def rate_limited():
    now = _time.time()
    q = _recent[_visitor()]
    while q and now - q[0] > RATE_WINDOW:
        q.popleft()
    if len(q) >= RATE_LIMIT:
        return True
    q.append(now)
    return False


@web.get("/")
def index():
    return send_from_directory(STATIC, "index.html")


@web.get("/api/languages")
def languages():
    return jsonify(languages=[{"code": c, "name": n} for c, n in orchestrator.LANGUAGE_NAMES.items()])


@web.post("/api/chat")
def chat():
    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()
    mode = data.get("mode", "normal")
    previous = (data.get("previous") or "").strip()[:MAX_PREVIOUS_CHARS]
    language = data.get("language") or orchestrator.DEFAULT_LANGUAGE
    help_level = data.get("help_level", "step")
    skill = data.get("skill") or None
    history = clean_history(data.get("history"))
    last_skill = data.get("last_skill") if isinstance(data.get("last_skill"), str) else None
    goal = clean_goal(data.get("goal"))
    country = data.get("country") if isinstance(data.get("country"), str) and data.get("country") in load_helplines() else None
    today = data.get("today") if isinstance(data.get("today"), str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", data.get("today")) else None

    if not message:
        return jsonify(error="Please type or say something first."), 400
    if len(message) > MAX_MESSAGE_CHARS:
        return jsonify(error="That message is too long. Please shorten it."), 400
    if mode == "rephrase" and not previous:
        return jsonify(error="There is no earlier answer to explain again."), 400
    if orchestrator.route(message, mode) not in ("emergency", "delete_data") and rate_limited():
        return jsonify(error="You've sent a lot of messages in a short time. Please wait a few minutes and try again. "
                             "If this is an emergency, call your local emergency number now."), 429

    try:
        result = orchestrator.handle(message, mode, previous, language, help_level, skill,
                                     history=history, last_skill=last_skill, goal=goal, today=today, country=country,
                                     spoken=data.get("spoken") is True)
    except Exception:
        import traceback
        traceback.print_exc()  # shows the real error in the terminal
        return jsonify(error="The guide is unavailable right now. Please try again in a moment."), 503

    return jsonify(
        answer=result["answer"],
        fallback=result["fallback"],
        search_used=result["search_used"],
        skill=result.get("skill"),
        offer_save=result.get("offer_save", False),
        sources=[{"title": t, "url": u} for t, u in result["sources"] if u.startswith("https://")],
    )


@web.post("/api/feedback")
def feedback():
    """Logs the rating and time only. The message and the reply are not stored."""
    data = request.get_json(silent=True) or {}
    rating = data.get("rating")
    if rating not in ALLOWED_RATINGS:
        return jsonify(error="Unknown rating."), 400

    record = {"time": datetime.now().isoformat(timespec="seconds"), "rating": rating}
    with open(LOG_DIR / "feedback.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")
    return jsonify(ok=True)



HELPLINES_FILE = BASE / "helplines.yaml"


def load_helplines():
    with open(HELPLINES_FILE, encoding="utf-8") as f:
        return (yaml.safe_load(f) or {}).get("countries", {})


@web.get("/api/countries")
def countries():
    data = load_helplines()
    return jsonify(countries=[{"code": c, "name": v.get("name", c), "languages": v.get("languages", [])} for c, v in data.items()])


@web.get("/api/helplines/<code>")
def helplines(code):
    entry = load_helplines().get(code.upper())
    if not entry:
        return jsonify(message="Unknown country."), 404
    if entry.get("status") != "verified":
        return jsonify(message="We have not checked the helpline numbers for this country yet. "
                               "Please search for the official emergency number for your country, "
                               "or contact your bank using the number on your card."), 404
    return jsonify(numbers=entry.get("numbers", []), checked=entry.get("checked"), source=entry.get("source"))



# ---------- Personal memory (goals). Each browser has its own owner id. ----------

OWNER_RE = re.compile(r"^[a-f0-9]{16,64}$")


def _owner():
    owner = request.headers.get("X-Owner-Id", "")
    return owner if OWNER_RE.match(owner) else None


@web.get("/api/goals")
def goals_list():
    owner = _owner()
    if not owner:
        return jsonify(error="Missing owner id."), 400
    return jsonify(goals=memory.list_goals(owner))


@web.post("/api/goals")
def goals_add():
    owner = _owner()
    if not owner:
        return jsonify(error="Missing owner id."), 400
    data = request.get_json(silent=True) or {}
    try:
        steps = data.get("steps") if isinstance(data.get("steps"), list) else None
        gid = memory.add_goal(owner, data.get("title"), data.get("next_step", ""), data.get("due", ""), steps)
    except ValueError as error:
        return jsonify(error=str(error)), 400
    return jsonify(id=gid), 201


@web.patch("/api/goals/<int:gid>")
def goals_update(gid):
    owner = _owner()
    if not owner:
        return jsonify(error="Missing owner id."), 400
    data = request.get_json(silent=True) or {}
    try:
        changed = memory.update_goal(owner, gid, title=data.get("title"),
                                     next_step=data.get("next_step"), status=data.get("status"))
    except ValueError as error:
        return jsonify(error=str(error)), 400
    return (jsonify(ok=True), 200) if changed else (jsonify(error="Not found."), 404)


@web.delete("/api/my-data")
def delete_my_data():
    """Delete everything saved for this browser: goals, steps and to-dos."""
    owner = _owner()
    if not owner:
        return jsonify(error="Missing owner id."), 400
    memory.delete_everything(owner)
    return jsonify(ok=True)


@web.post("/api/goals/draft")
def goals_draft():
    """Auriv drafts a goal from the recent conversation. Nothing is saved until the person confirms."""
    owner = _owner()
    if not owner:
        return jsonify(error="Missing owner id."), 400
    data = request.get_json(silent=True) or {}
    history = clean_history(data.get("history"))
    if not history:
        return jsonify(error="There is nothing to turn into a goal yet."), 400
    today = data.get("today") if isinstance(data.get("today"), str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", data.get("today")) else None
    try:
        draft = orchestrator.draft_goal(history, data.get("language") or orchestrator.DEFAULT_LANGUAGE, today)
    except Exception:
        import traceback
        traceback.print_exc()
        draft = None
    if not draft:
        return jsonify(error="Could not draft a goal this time."), 503
    return jsonify(draft=draft)


@web.post("/api/goals/<int:gid>/steps/<int:sid>/toggle")
def goals_step_toggle(gid, sid):
    owner = _owner()
    if not owner:
        return jsonify(error="Missing owner id."), 400
    ok = memory.toggle_step(owner, gid, sid)
    return (jsonify(ok=True), 200) if ok else (jsonify(error="Not found."), 404)


@web.post("/api/goals/<int:gid>/step")
def goals_step(gid):
    owner = _owner()
    if not owner:
        return jsonify(error="Missing owner id."), 400
    ok = memory.mark_step_done(owner, gid)
    return (jsonify(ok=True), 200) if ok else (jsonify(error="Not found."), 404)


@web.delete("/api/goals/<int:gid>")
def goals_delete(gid):
    owner = _owner()
    if not owner:
        return jsonify(error="Missing owner id."), 400
    ok = memory.delete_goal(owner, gid)
    return (jsonify(ok=True), 200) if ok else (jsonify(error="Not found."), 404)


@web.delete("/api/goals")
def goals_clear():
    owner = _owner()
    if not owner:
        return jsonify(error="Missing owner id."), 400
    memory.clear_all(owner)
    return jsonify(ok=True)



# ---------- To-do list routes ----------

@web.get("/api/todos")
def todos_list():
    owner = _owner()
    if not owner:
        return jsonify(error="Missing owner id."), 400
    return jsonify(todos=memory.list_todos(owner))


@web.post("/api/todos")
def todos_add():
    owner = _owner()
    if not owner:
        return jsonify(error="Missing owner id."), 400
    data = request.get_json(silent=True) or {}
    try:
        tid = memory.add_todo(owner, data.get("text"), data.get("due", ""))
    except ValueError as error:
        return jsonify(error=str(error)), 400
    return jsonify(id=tid), 201


@web.post("/api/todos/<int:tid>/toggle")
def todos_toggle(tid):
    owner = _owner()
    if not owner:
        return jsonify(error="Missing owner id."), 400
    ok = memory.toggle_todo(owner, tid)
    return (jsonify(ok=True), 200) if ok else (jsonify(error="Not found."), 404)


@web.delete("/api/todos/<int:tid>")
def todos_delete(tid):
    owner = _owner()
    if not owner:
        return jsonify(error="Missing owner id."), 400
    ok = memory.delete_todo(owner, tid)
    return (jsonify(ok=True), 200) if ok else (jsonify(error="Not found."), 404)


if __name__ == "__main__":
    web.run(host="127.0.0.1", port=5000, debug=False)
