# MVP Scope

## Purpose

The Personal Capability Agent helps people handle unfamiliar information and everyday tasks, and builds the skills to do more for themselves. The MVP tests one claim: an accessible agent that explains the reason behind each step helps people handle unfamiliar digital situations with more confidence than a generic chatbot.

## Audience

A broad audience of people who find the modern world hard to keep up with. The MVP does not target a specific education level, age group, location or language, and it does not assume any skill gap from those characteristics.

## Core loop

1. **Understand**: find out what the person is asking and what they already know, by asking.
2. **Anticipate**: notice a likely risk or next step in the situation.
3. **Guide**: explain the situation and offer one next step.
4. **Build capability**: explain the reason, then invite the user to try the next part.
5. **Adapt**: respond to the user's answer, and stop guiding once they have the idea.

## Layers in the MVP

| Layer | In MVP? | What the MVP does |
|---|---|---|
| 1. Personal understanding | Light | Asks ordinary questions in the conversation; no formal assessment. Profile storage is planned, not built. |
| 2. World understanding | No | Roadmap. Only explanations that arise naturally from a user's question. |
| 3. Safety and wellbeing | Yes | Checks suspicious messages; refers health, legal, financial and emergency questions to professionals. |
| 4. Daily-life navigator | Yes | Explains messages and terms; gives one step at a time with the reason. |
| 5. Personal growth | No | Roadmap. |
| 6. Proactive agent | One feature | One permission-based follow-up offered at the end of a session. |

## Features in scope

- **Text chat** in a simple interface with large, readable text.
- **Explain, show, invite, check** response pattern for guidance.
- **Suspicious-message check** for pasted text, with the warning signs and the official verification route.
- **Search with sources** for current or verifiable questions, using Tavily. Every cited source must come from the search results.
- **Professional referral rule** for health, legal, financial and emergency questions.
- **Uncertainty statements** when the agent lacks evidence.
- **One follow-up offer** at the end of a session, which the user can accept or decline.
- **Feedback control** on each answer: helpful, not right, or confusing. Logged for evaluation.
- **Call log** for every model call, used for evaluation.

## Features out of scope

- Voice input and output.
- Languages other than the one used for testing.
- Saved user profile across sessions (planned next milestone).
- Scheduled reminders or real notifications.
- Access to bank accounts, government portals, email, messages or devices.
- Making payments, submitting forms, or acting on the user's behalf.
- Monitoring or inferring anything about the user from their device or behaviour.
- Emotional-support or therapy-like conversations.
- Personal growth courses and world-understanding modules.

## Success criteria

System criteria, measured with the test sets in the validation plan:

- Clean-output rate of 95% or higher across the 20-prompt test set.
- Every health, legal, financial and emergency prompt includes a referral to a professional or official service.
- Every cited source appears in the search results for that query.
- No reply claims an action was taken on an account, payment or form.

User criteria, measured in short sessions with three to five participants:

- The participant completes a task they found hard before, with less help than they asked for at the start.
- The participant can explain the reason behind a recommendation in their own words.
- The participant identifies a common warning sign in a new example.

## Known constraints

- Model output can vary. Logs and the test set show how often it does.
- Search results depend on the source and country. The MVP names the country it covers.
- The MVP makes no claim about long-term behaviour change, because it does not test over weeks.
