# Trust, Autonomy and Boundaries

Personal Capability Agent: design principles, testable rules and proactivity levels.

## Core principle

Trust, autonomy and boundaries are core design principles, not a privacy setting. A personal agent that assesses people and initiates actions could become extremely helpful. It could also become intrusive or overconfident if designed poorly.

## Design questions and principles

| Design question | Recommended principle |
|---|---|
| What does it know about the user? | Keep a transparent, editable profile of relevant skills, preferences, and goals. |
| How does it assess capability? | Use evidence from tasks and ask when uncertain; never make permanent judgments from demographic traits. |
| When can it initiate help? | Only within user-approved categories, channels, and frequency limits. |
| Can it take action? | Start with explanations and guidance; require confirmation for consequential actions. |
| What if it is wrong? | Communicate uncertainty, verify important claims, and provide a way to reach human support. |
| How does it build independence? | Teach the reasoning behind tasks and gradually reduce unnecessary assistance. |

## Testable rules

Each principle is written as a rule that can be checked in code and in the test set.

| Principle | Testable rule | How it is checked |
|---|---|---|
| Transparent profile | Every stored field is visible and deletable from the app. | Profile view and delete endpoint work; a test confirms deletion removes the record. |
| Evidence-based assessment | The profile never records a trait about age, accent, education or location. | Code review of profile fields; a test rejects those keys. |
| Asks when uncertain | When the agent lacks evidence about the user's knowledge, its reply includes a question rather than an assumption. | Review of test replies for unsupported assumptions. |
| Limited initiation | Proactive messages happen only in categories the user approved, at most one per session. | Config check; a test confirms a declined category produces no follow-up. |
| No consequential action | The agent never claims to have performed an action on an account, payment or form. | Test prompts asking it to pay or submit; the reply must refuse and explain. |
| Uncertainty and human support | Every safety or health reply states its uncertainty and names a human route. | Safety subset of the 20-prompt test set. |
| Builds independence | Replies explain the reason, and the agent reduces guidance when the user has shown a skill. | Review of follow-up replies after a topic has been practised. |

## Proactivity levels

**Level A: contextual help (in scope).** The agent offers one explanation or next step within the conversation. This is the level to demonstrate.

**Level B: scheduled guidance (out of scope for the demo).** The simulated check-in button stays in the demo, but it is labelled as simulated. Do not describe it as working notifications until scheduling has been verified.

**Level C: risk-aware intervention (out of scope).** The current app can check a suspicious message when the user pastes it, but it does not intervene on its own. Describe this as a user-initiated risk check, not an intervention.

## Two gaps to close

**1. A mechanism for "what if it is wrong".** After each answer, the user can mark it as helpful, not right, or confusing. The choice is logged. This gives real evidence about errors and covers the "correct the system" measure from user testing.

**2. A trigger for independence.** Once the profile shows a topic was practised and answered unaided, the next reply on that topic gives the explanation but skips the worked example. Test this with two messages on the same topic.

## Wording for the write-up

> The agent never makes decisions on the user's behalf, never acts on accounts or payments, and never judges a person's capability from demographic traits. Every stored item is visible and deletable, and every proactive message is limited to categories the user has approved.

Point to the test that proves each claim. This turns a principle into evidence.
