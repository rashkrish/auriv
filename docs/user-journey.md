# User Journey

This document describes how a person uses the MVP, step by step, and where the agent makes choices. It matches the behaviour the app should show, so use it to write test cases.

## Entry

The person opens the chat and sees a short line: what the assistant can help with, and what it does not do. For example: "I can explain messages, help with everyday tasks, and show you how to do things yourself. I can't access your accounts or make decisions for you."

## Journey 1: Understanding an unfamiliar message

1. The person pastes a message, or types a question about one: "My bank says my account will be blocked unless I act today. What does this mean?"
2. The agent asks one question before judging: "Did you expect a message from this bank recently?" This keeps the person reasoning, rather than only receiving a verdict.
3. The agent explains the warning signs in plain words, with the reason each one matters. Urgency, unexpected contact, requests for details, and links to act are examples.
4. The agent gives a verdict in one word: safe, suspicious, or likely a scam. It states its uncertainty when the evidence is limited.
5. The agent recommends the next step: check with the bank using the number on the bank's official website or card, not the number or link in the message.
6. If search is used, the agent cites one or two official sources from the results.
7. The agent invites the person to try: "Want to look at one more example and tell me what you notice?"

## Journey 2: Practice

1. The agent shows a second, similar message, without a verdict.
2. The person says what they notice and what they would do.
3. The agent confirms what the person got right, fills any gap, and explains the reason.
4. If the person answers correctly without help, the next related reply skips the worked example and goes straight to the question.

## Journey 3: Everyday task

1. The person asks for help with a task: "I need to pay a bill online but I don't know how."
2. The agent asks what they can see on the screen, or what they have already tried.
3. The agent gives one step, with the reason for it. It does not list the whole process at once.
4. The agent asks the person to try the step, then waits for the result.
5. The agent gives the next step only after the person reports back.

## Journey 4: Health, legal, financial or emergency question

1. The person asks a question that involves health, a pet's health, a legal problem, money owed, or an emergency.
2. The agent gives general information only.
3. The agent names the warning signs that need prompt professional help, and says who to contact: a doctor, vet, lawyer, bank, or emergency number for the country.
4. The agent never reassures the person that a symptom or situation is fine. It may say that most cases are minor, but it does not make that judgement for the person.

## Journey 5: Request the agent should refuse

1. The person asks the agent to do something on their behalf: pay a bill, log into an account, submit a form, or reply to a message.
2. The agent explains that it cannot do that.
3. The agent offers to explain each step so the person can do it themselves, and asks what they would like to start with.

## Journey 6: Something is unclear

1. The person's question is vague or they seem unsure what they need.
2. The agent does not assume a skill gap or a background. It asks one simple question: "What is the situation you're dealing with?"
3. The agent does not ask more than two questions in one reply.

## Journey 7: Closing a session

1. When the person says they're done, or after a useful exchange, the agent gives a short summary: what they practised and what they may want to revisit.
2. The agent offers one optional follow-up, such as "Would you like a short reminder to try this again?" The person can decline.
3. In the MVP the follow-up is shown but not scheduled. This must be stated clearly in the demo.

## Feedback at each answer

Below each answer, the person can mark it as helpful, not right, or confusing. The choice is logged. The agent does not change its reply because of a single mark.

## Test cases from this journey

Each journey above maps to at least one prompt in the test set, in these categories: everyday questions, learning requests, safety scenarios, health or pet questions, and current-information questions. The full test set and pass criteria are in the [validation plan](validation-plan.md).
