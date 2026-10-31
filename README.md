# Auriv – your guide

**A voice-first, multilingual personal AI for the everyday tasks that the internet wasn't built to make easy.**
Auriv listens in your language, keeps you safe from scams and bad advice, plans your goals and schedules with real dates, and teaches you new skills step by step. It runs on **NVIDIA Nemotron** models served by **Nebius Token Factory**.

Built for the **Nebius x NVIDIA Global AI Hackathon** (Personal AI track).

---

## Try it

- **Live demo:** https://auriv.onrender.com
- Works best in **Chrome or Edge** (voice typing). Safari and Samsung Internet also work. In other browsers you can type, and Auriv still reads answers aloud.
- First screen: pick your country and language. Then tap the microphone, or tap one of the four cards.

**Things to try**

| Card | Try saying |
|---|---|
| Organise my schedule | "Monday 9 to 11 lab, Monday 10:30 call with my supervisor, Wednesday 2pm dentist" |
| Work toward a goal | "My goal is to get comfortable speaking in public in 3 weeks" |
| Learn something | "Can you teach me Hindi?" then tap 🎤 next to a phrase and say it |
| Stay safe | "I got a text: your bank account is blocked, verify now at http://bit.ly/abc. Is it real?" |
| In Hindi | "मुझे अपनी प्रेजेंटेशन के लिए अंग्रेज़ी की प्रैक्टिस करनी है जो अगले हफ्ते है" |

---

## What makes Auriv different

**Easy for everyone, by voice or text**

- **Talk or type:** speak at your own pace, correct any word by typing, and send when ready.
- **Your language, your country:** 20 languages, with advice that fits where you live. In Hindi, familiar English terms appear in brackets.
- **Understands everyday wording:** whether you say "my goal is…", "I have to prepare for…" or the same in Hindi, French or Japanese, Auriv recognises what kind of help you need.
- **Comfortable listening:** answers are read aloud for each language, at the speed you choose.

**Safety comes first, and it is enforced in code**

- **Emergencies:** an instant reply with verified emergency numbers for your country (UK 999, India 112, US 911 and more), shown before any AI model is involved.
- **Scam checks:** a clear verdict first (**SCAM**, **SUSPICIOUS** or **LOOKS OK**), the warning signs, and your country's official reporting route (UK 7726, India 1930). The message you paste is never sent to web search.
- **Trustworthy sources:** questions about passports, tax, benefits, law or health are answered from official government sources for your country, never from social media.
- **No invented helplines:** any phone number not found in a trusted source is removed before you see it.
- **Up to date where it matters:** checked recent changes, such as new housing law, take priority over what the model learned in training.
- **You stay in control:** Auriv never pays, books, sends or logs in for you. It shows you how, step by step.

**Plans with real dates, and it remembers**

- **Accurate dates:** "next Monday", "five days after that" or "13 नवंबर" are turned into exact calendar dates, so plans are never off by a day.
- **Clear schedules:** meetings and classes become a dated table, with clashes pointed out.
- **Goals that save themselves:** mention a goal and Auriv creates it, with a due date and a checklist spread across the time you have. One tap undoes it.
- **Pick up where you left off:** lessons, schedules and goals are saved, and continuing one restores the whole conversation.
- **Reminders only when needed:** a reminder appears only when a deadline is today or tomorrow.

**Learning you can practise, not just read**

- **Speaking practice:** each phrase in a language lesson is spoken in a native voice, and a microphone button listens to you and checks every word.
- **Real-world skills:** for sports, yoga or cooking, Auriv explains the basics, gives a simple practice plan, and links to good video guides, because it cannot watch you.

---

## How it uses NVIDIA Nemotron on Nebius

| Model | Used for |
|---|---|
| `nvidia/Nemotron-3_5-Lightning` | Everyday replies, schedules, goals, scam checks, goal drafting (fast) |
| `nvidia/Nemotron-3-Ultra-550b-a55b` | Concepts (for example MHD and helicity), research comparisons, and lessons in Hindi and other non-English languages |
| `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` | One-word request classification for non-English messages |

All models are called through Nebius Token Factory's OpenAI-compatible API. Thinking is switched off for speed; most replies arrive in 1 to 7 seconds. If an extra model fails, Auriv falls back to the main model.

---

## How it works

```
Browser (static/index.html)        voice in/out, cards, saved lessons and schedules (in the browser)
      │
server.py (Flask)                   API routes, per-visitor usage limit
      │
orchestrator.py                     routing → safety gates → skill prompt → model → quality checks → tidy
      │
app.py                              Nebius client, Tavily web search (blocked domains), prompt loading, logs
memory.py                           SQLite: goals and their checklists, to-dos (per browser id)
helplines.yaml                      verified emergency numbers and scam-report routes, with sources
prompts/                            system, language, skills and help-level prompts
```

**Quality checks after every reply** (in code): no self-description as a model, no notes about how to answer, reply in the right language and script, no invented phone numbers, schedules as tables, place lessons without language phrases, and a short rescue attempt before any "couldn't finish" message.

---

## Run it yourself

Requirements: Python 3.10+, a [Nebius Token Factory](https://tokenfactory.nebius.com) API key, and a [Tavily](https://tavily.com) API key.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate      macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements.txt

# Windows
set NEBIUS_API_KEY=your-key
set TAVILY_API_KEY=your-key
# macOS/Linux
export NEBIUS_API_KEY=your-key
export TAVILY_API_KEY=your-key

python main.py
```

Open http://127.0.0.1:5000 in Chrome or Edge.

### Deploy on Render (free)

1. Push this repository to GitHub.
2. On [render.com](https://render.com): **New → Blueprint**, choose the repository (it reads `render.yaml`).
3. Enter `NEBIUS_API_KEY` and `TAVILY_API_KEY` when asked, then deploy.

On the free plan the app sleeps when unused, so the first visit can take about a minute. Saved goals on the server reset when it restarts; lessons and schedules are kept in each visitor's browser.

---

## Tests

```bash
python tests/run_tests.py                       # routing, no API calls
python tests/run_calibration.py                 # 65 real conversations, writes tests/calibration.csv
python tests/run_calibration.py multilingual    # the same kind of help in 8 other languages
```

---

## Privacy

- Messages are sent to Nebius (model) and Tavily (search) to produce an answer. Pasted scam messages are never sent to search.
- Goals and to-dos are stored per browser and can be deleted at any time (Settings → Delete all my data, or "Clear all data").
- Lessons and schedules are stored only in your browser.
- Logs record timings and reason codes, not your messages.

## Licence

MIT © 2026 Rashmi Sarwal
