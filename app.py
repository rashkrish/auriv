import os
import re
import json
import time
from datetime import datetime
from pathlib import Path
from string import Template

import yaml

# Use the computer's own certificate store (Windows, macOS), so secure connections work on networks
# with security software that inspects HTTPS. Optional: pip install truststore
try:
    import truststore
    truststore.inject_into_ssl()
except Exception:
    pass

from openai import OpenAI
from tavily import TavilyClient

BASE = Path(__file__).parent
CFG = yaml.safe_load((BASE / "config.yaml").read_text(encoding="utf-8"))
LOG_DIR = BASE / "logs"
LOG_DIR.mkdir(exist_ok=True)

ai = OpenAI(
    api_key=os.environ["NEBIUS_API_KEY"].strip().strip('"'),   # spaces or quotes from "set" break the request
    base_url="https://api.tokenfactory.nebius.com/v1/",
    timeout=90,      # a stuck call fails after 90 seconds instead of 10 minutes
    max_retries=1,
)
web = TavilyClient(api_key=os.environ["TAVILY_API_KEY"].strip().strip('"'))


def load_prompt(name, **values):
    """Read prompts/<name>.md and fill $placeholders."""
    text = (BASE / "prompts" / f"{name}.md").read_text(encoding="utf-8")
    return Template(text).safe_substitute(**values).strip()


def log_call(record):
    """Append one JSON line per model call. This is your evidence for the write-up."""
    record["time"] = datetime.now().isoformat(timespec="seconds")
    with open(LOG_DIR / "calls.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def extract_answer(text):
    match = re.search(r"<answer>(.*?)</answer>", text, re.DOTALL | re.IGNORECASE)
    body = match.group(1) if match else text
    body = body.replace("<answer>", "").replace("</answer>", "").strip()
    if not body:
        return None
    for pattern in CFG["leak_patterns"]:
        if re.search(pattern, body, re.IGNORECASE | re.MULTILINE):
            return None
    return body


def needs_search(question):
    q = question.lower()
    return any(signal in q for signal in CFG["search"]["signals"])


# Never used as sources: social media, video and question-and-answer sites.
BLOCKED_DOMAINS = [
    "facebook.com", "fb.com", "instagram.com", "youtube.com", "youtu.be", "tiktok.com", "x.com", "twitter.com",
    "reddit.com", "quora.com", "pinterest.com", "linkedin.com", "threads.net", "whatsapp.com", "t.me",
    "telegram.org", "scribd.com", "snapchat.com", "sharechat.com", "moj.app",
]


VIDEO_DOMAINS = {"youtube.com", "youtu.be"}


def _blocked(url, allow_video=False):
    host = re.sub(r"^https?://", "", url or "").split("/")[0].split(":")[0].lower()
    blocked = [d for d in BLOCKED_DOMAINS if not (allow_video and d in VIDEO_DOMAINS)]
    if any(host == d or host.endswith("." + d) for d in blocked):
        return True
    # The same sites under other country endings, for example pinterest.ca or facebook.co.in.
    labels = host.split(".")
    names = {d.split(".")[0] for d in blocked if len(d.split(".")[0]) > 3}
    return any(label in names for label in labels[:-1])


def search_web(question, include_domains=None, allow_video=False):
    """Search with Tavily. Social media and video sites are always excluded.
    include_domains limits the search to the given sites (used for official questions)."""
    s = CFG["search"]
    excluded = [d for d in BLOCKED_DOMAINS if not (allow_video and d in VIDEO_DOMAINS)]
    kwargs = dict(query=question, max_results=s["max_results"], search_depth="basic", exclude_domains=excluded)
    if include_domains:
        kwargs["include_domains"] = include_domains
    response = web.search(**kwargs)
    results, sources = [], []
    for item in response.get("results", []):
        title = item.get("title", "Untitled")
        url = item.get("url", "")
        if not url or _blocked(url, allow_video):
            continue
        content = item.get("content", "")[: s["snippet_chars"]]
        results.append(f"Title: {title}\nURL: {url}\nContent: {content}")
        sources.append((title, url))
    return "\n\n".join(results), sources


def get_answer(question, context=""):
    user_content = question
    if context:
        user_content += "\n\n" + load_prompt("search_context", results=context)

    messages = [
        {"role": "system", "content": load_prompt("system")},
        {"role": "user", "content": user_content},
    ]

    for attempt in range(CFG["max_attempts"]):
        kwargs = dict(
            model=CFG["model"],
            messages=messages,
            max_tokens=CFG["max_tokens"],
            temperature=CFG["temperature"],
        )
        if "enable_thinking" in CFG:
            kwargs["extra_body"] = {"enable_thinking": CFG["enable_thinking"]}

        started = time.time()
        response = ai.chat.completions.create(**kwargs)
        choice = response.choices[0]
        text = choice.message.content or ""

        answer = extract_answer(text)
        log_call({
            "model": CFG["model"],
            "thinking": CFG.get("enable_thinking"),
            "attempt": attempt,
            "finish_reason": choice.finish_reason,
            "completion_tokens": response.usage.completion_tokens,
            "latency_s": round(time.time() - started, 2),
            "clean": answer is not None,
        })

        if answer and choice.finish_reason == "stop":
            return answer

        # Correct the model with an explicit instruction, not a repeat of the same request.
        messages.append({"role": "assistant", "content": text})
        messages.append({"role": "user", "content": load_prompt("format_retry")})

    log_call({"model": CFG["model"], "fallback": True})
    return load_prompt("fallback")


def main():
    print("=== Personal Capability Agent ===")
    print("Ask anything, or type 'exit' to quit.")
    print("For web research, ask for current information or sources.\n")

    while True:
        question = input("You: ").strip()
        if question.lower() == "exit":
            print("Goodbye!")
            break
        if not question:
            continue

        context, sources = "", []
        if needs_search(question):
            try:
                print("Searching the web...")
                context, sources = search_web(question)
            except Exception as error:
                print("Web search unavailable; answering without it.")
                print("Search error:", error)

        try:
            answer = get_answer(question, context)
            print("\nGuide:", answer, "\n")
            if sources:
                print("Sources:")
                for title, url in sources:
                    print(f"- {title}: {url}")
                print()
        except Exception as error:
            print("Request failed:", error)


if __name__ == "__main__":
    main()