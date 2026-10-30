# Auriv – your guide

**A voice-first, multilingual personal AI for the everyday tasks that the internet wasn't built to make easy.**
Auriv listens in your language, keeps you safe from scams and bad advice, plans your goals and schedules with real dates, and teaches you new skills step by step. It runs on **NVIDIA Nemotron** models served by **Nebius Token Factory**.

Built for the **Nebius x NVIDIA Global AI Hackathon** (Personal AI track).

---

## Try it

- **Live demo:** `https://<your-app>.onrender.com` *(replace with your Render link)*
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

**Safety is built into the code, not just requested from the model**
- Emergencies get a fixed reply with **verified emergency numbers for your country** (UK 999, India 112, US 911 and more), before any AI is called.
- Message checks always start with **SCAM / SUSPICIOUS / LOOKS OK**, never send the pasted message to web search, and end with your country's **official reporting route** (UK 7726, India 1930 · cybercrime.gov.in, US reportfraud.ftc.gov).
- Official questions (passports, tax, benefits, law, health) use **official government sources for your country**; social media and video sites are blocked as sources.
- Phone numbers that are not in the sources are removed, so the model cannot invent a helpline.
- Checked recent changes override the model's memory (for example, England abolished Section 21 evictions on 1 May 2026).
- Auriv never pays, sends, books or logs in for you. It shows you how, step by step.

**Plans with real dates, and it remembers**
- Dates like "next Monday", "5 days after that", "in 3 months" or "13 नवंबर" are **worked out in code**, not by the model.
- Schedules come back as a dated table with clashes pointed out.
- Goals are **drafted and saved automatically** from the conversation (title, due date, checklist), with Undo. Step dates are spread evenly up to the deadline.
- **Saved lessons, schedules and goals**: tap a card to continue any of them later, with the whole conversation restored.
- A reminder appears only when a deadline is today or tomorrow.

**Made for people who don't type well**
- Voice-first: speak at your own pace, fix any word by typing, then send.
- 20 languages, with the person's country shaping the advice. In Hindi, key English terms appear in brackets, and Auriv uses the feminine grammar that matches its voice.
- Requests are recognised in any language: phrase rules first, then a one-word classification by the fast Nemotron model.
- Adjustable speaking speed, and answers read aloud in the right voice for each language.

**Teaches you to speak, not just read**
- Language lessons wrap each practice phrase so it is read in the right voice, with a 🎤 button that listens to you and checks each word.
- Hands-on skills (badminton, yoga, cooking) get the basics in words plus links to good videos, because Auriv cannot watch you.

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
