"""Personal memory: goals the person chooses to save, kept in a local SQLite file.

Rules:
- Nothing is saved unless the person presses Save.
- Each browser has its own owner id, so visitors to a shared server never see each other's goals.
- The person can list, edit, mark steps done, delete one goal, or clear everything.
- Do not use this to store health, money or account details (the page says so).
"""

import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
DB_PATH = DATA_DIR / "memory.db"
MAX_TITLE = 120
MAX_NEXT_STEP = 300
MAX_STEPS = 10
MAX_STEP_TEXT = 200
VALID_STATUS = {"open", "done"}


def _connect():
    DATA_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """CREATE TABLE IF NOT EXISTS goals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner TEXT NOT NULL,
            title TEXT NOT NULL,
            next_step TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'open',
            steps_done INTEGER NOT NULL DEFAULT 0,
            created TEXT NOT NULL,
            updated TEXT NOT NULL)"""
    )
    # Goals made before steps existed get a due-date column; each goal can have a checklist of steps.
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(goals)")}
    if "due" not in cols:
        conn.execute("ALTER TABLE goals ADD COLUMN due TEXT NOT NULL DEFAULT ''")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS goal_steps (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            goal_id INTEGER NOT NULL,
            owner TEXT NOT NULL,
            position INTEGER NOT NULL,
            text TEXT NOT NULL,
            due TEXT NOT NULL DEFAULT '',
            done INTEGER NOT NULL DEFAULT 0)"""
    )
    # Goals marked done before this rule existed: tick their steps too.
    conn.execute("UPDATE goal_steps SET done = 1 WHERE done = 0 AND goal_id IN (SELECT id FROM goals WHERE status = 'done')")
    conn.commit()
    return conn


def _now():
    return datetime.now().isoformat(timespec="seconds")


def _clean(text, limit):
    return (text or "").strip()[:limit]


def _as_dict(row):
    return {k: row[k] for k in row.keys() if k != "owner"}


def _clean_date(text):
    text = _clean(text, 10)
    try:
        datetime.strptime(text, "%Y-%m-%d")
        return text
    except ValueError:
        return ""


def add_goal(owner, title, next_step="", due="", steps=None):
    title = _clean(title, MAX_TITLE)
    if not title:
        raise ValueError("A goal needs a title.")
    clean_steps = []
    for step in (steps or [])[:MAX_STEPS]:
        if isinstance(step, dict):
            text = _clean(step.get("text"), MAX_STEP_TEXT)
            if text:
                clean_steps.append((text, _clean_date(step.get("due"))))
    if clean_steps and not next_step:
        next_step = clean_steps[0][0]
    now = _now()
    with closing(_connect()) as conn, conn:
        cur = conn.execute(
            "INSERT INTO goals (owner, title, next_step, due, created, updated) VALUES (?, ?, ?, ?, ?, ?)",
            (owner, title, _clean(next_step, MAX_NEXT_STEP), _clean_date(due), now, now),
        )
        gid = cur.lastrowid
        conn.executemany(
            "INSERT INTO goal_steps (goal_id, owner, position, text, due) VALUES (?, ?, ?, ?, ?)",
            [(gid, owner, i, text, step_due) for i, (text, step_due) in enumerate(clean_steps)],
        )
        return gid


def list_goals(owner):
    with closing(_connect()) as conn:
        rows = conn.execute(
            "SELECT * FROM goals WHERE owner = ? ORDER BY (status = 'open') DESC, updated DESC",
            (owner,),
        ).fetchall()
        steps = conn.execute(
            "SELECT id, goal_id, text, due, done FROM goal_steps WHERE owner = ? ORDER BY goal_id, position",
            (owner,),
        ).fetchall()
    by_goal = {}
    for st in steps:
        by_goal.setdefault(st["goal_id"], []).append(
            {"id": st["id"], "text": st["text"], "due": st["due"], "done": bool(st["done"])})
    goals = []
    for r in rows:
        g = _as_dict(r)
        g["steps"] = by_goal.get(g["id"], [])
        if g["steps"]:
            g["steps_done"] = sum(1 for st in g["steps"] if st["done"])
            pending = [st for st in g["steps"] if not st["done"]]
            g["next_step"] = pending[0]["text"] if pending else ""
        goals.append(g)
    return goals


def toggle_step(owner, gid, sid):
    """Tick or untick one step. When every step is done the goal is marked done, and reopened if one is unticked."""
    with closing(_connect()) as conn, conn:
        cur = conn.execute(
            "UPDATE goal_steps SET done = 1 - done WHERE owner = ? AND goal_id = ? AND id = ?", (owner, gid, sid))
        if cur.rowcount != 1:
            return False
        left = conn.execute(
            "SELECT COUNT(*) FROM goal_steps WHERE owner = ? AND goal_id = ? AND done = 0", (owner, gid)).fetchone()[0]
        conn.execute("UPDATE goals SET status = ?, updated = ? WHERE owner = ? AND id = ?",
                     ("open" if left else "done", _now(), owner, gid))
        return True


def update_goal(owner, gid, title=None, next_step=None, status=None):
    fields, values = [], []
    if title is not None:
        cleaned = _clean(title, MAX_TITLE)
        if not cleaned:
            raise ValueError("A goal needs a title.")
        fields.append("title = ?")
        values.append(cleaned)
    if next_step is not None:
        fields.append("next_step = ?")
        values.append(_clean(next_step, MAX_NEXT_STEP))
    if status is not None:
        if status not in VALID_STATUS:
            raise ValueError("Status must be open or done.")
        fields.append("status = ?")
        values.append(status)
    if not fields:
        return False
    fields.append("updated = ?")
    values.append(_now())
    values += [owner, gid]
    # The column names above are fixed in this file, so the query text is safe.
    sql = f"UPDATE goals SET {', '.join(fields)} WHERE owner = ? AND id = ?"
    with closing(_connect()) as conn, conn:
        cur = conn.execute(sql, values)
        if cur.rowcount == 1 and status == "done":
            # A finished goal has all its steps ticked, so the card never says "done" and "0 steps" at once.
            conn.execute("UPDATE goal_steps SET done = 1 WHERE owner = ? AND goal_id = ?", (owner, gid))
        return cur.rowcount == 1


def mark_step_done(owner, gid):
    with closing(_connect()) as conn, conn:
        cur = conn.execute(
            "UPDATE goals SET steps_done = steps_done + 1, updated = ? WHERE owner = ? AND id = ?",
            (_now(), owner, gid),
        )
        return cur.rowcount == 1


def delete_goal(owner, gid):
    with closing(_connect()) as conn, conn:
        cur = conn.execute("DELETE FROM goals WHERE owner = ? AND id = ?", (owner, gid))
        conn.execute("DELETE FROM goal_steps WHERE owner = ? AND goal_id = ?", (owner, gid))
        return cur.rowcount == 1


def clear_all(owner):
    with closing(_connect()) as conn, conn:
        conn.execute("DELETE FROM goals WHERE owner = ?", (owner,))
        conn.execute("DELETE FROM goal_steps WHERE owner = ?", (owner,))


# ---------- To-do list (routine tasks, added only by the person) ----------

MAX_TODO = 200


def _ensure_todos(conn):
    conn.execute(
        """CREATE TABLE IF NOT EXISTS todos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner TEXT NOT NULL,
            text TEXT NOT NULL,
            due TEXT NOT NULL DEFAULT '',
            done INTEGER NOT NULL DEFAULT 0,
            created TEXT NOT NULL)"""
    )


def add_todo(owner, text, due=""):
    text = _clean(text, MAX_TODO)
    if not text:
        raise ValueError("A to-do needs some text.")
    with closing(_connect()) as conn, conn:
        _ensure_todos(conn)
        cur = conn.execute(
            "INSERT INTO todos (owner, text, due, created) VALUES (?, ?, ?, ?)",
            (owner, text, _clean(due, 10), _now()),
        )
        return cur.lastrowid


def list_todos(owner):
    with closing(_connect()) as conn:
        _ensure_todos(conn)
        rows = conn.execute(
            "SELECT id, text, due, done, created FROM todos WHERE owner = ? "
            "ORDER BY done ASC, CASE WHEN due = '' THEN 1 ELSE 0 END, due ASC, id DESC",
            (owner,),
        ).fetchall()
    return [dict(r) for r in rows]


def toggle_todo(owner, tid):
    with closing(_connect()) as conn, conn:
        _ensure_todos(conn)
        cur = conn.execute("UPDATE todos SET done = 1 - done WHERE owner = ? AND id = ?", (owner, tid))
        return cur.rowcount == 1


def delete_todo(owner, tid):
    with closing(_connect()) as conn, conn:
        _ensure_todos(conn)
        cur = conn.execute("DELETE FROM todos WHERE owner = ? AND id = ?", (owner, tid))
        return cur.rowcount == 1


def delete_everything(owner):
    """Remove every goal, step and to-do saved for this browser."""
    with closing(_connect()) as conn, conn:
        conn.execute("DELETE FROM goal_steps WHERE owner = ?", (owner,))
        conn.execute("DELETE FROM goals WHERE owner = ?", (owner,))
        _ensure_todos(conn)
        conn.execute("DELETE FROM todos WHERE owner = ?", (owner,))
