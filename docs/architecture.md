# Architecture

## Overview

The MVP is a single Python application that runs a chat loop in the terminal. It calls a Nemotron model through the Nebius Token Factory API, optionally calls the Tavily search API for current or verifiable information, and writes a log line for every model call.

The design keeps prompts and settings out of the code, so wording and configuration can change without editing the logic.

## Components

| Component | File | Responsibility |
|---|---|---|
| Chat loop | `app.py` | Reads input, decides whether to search, calls the model, prints the answer and sources. |
| Settings | `config.yaml` | Model ID, token limit, temperature, thinking setting, search keywords, leak patterns. |
| Instructions | `prompts/*.md` | System prompt, search-context template, retry instruction, fallback reply. |
| Search | `app.py` (Tavily) | Returns a limited number of results, each with title, URL and a short snippet. |
| Model client | `app.py` (OpenAI-compatible client) | Sends messages to the Token Factory endpoint and reads the reply. |
| Answer check | `app.py` | Extracts the reply from the answer tags and rejects replies that contain leaked reasoning. |
| Call log | `logs/calls.jsonl` | One JSON line per model call, for evaluation. |
| Design documents | `docs/` | Scope, journey, architecture, boundaries, validation. |

## Request flow

1. The person types a message.
2. The app checks the message against the search signals in `config.yaml`. If one matches, it calls Tavily and keeps up to four results, each trimmed to a set length.
3. The app builds the message list: the system prompt from `prompts/system.md`, the person's message, and, if searched, the results wrapped in the search-context template and labelled as untrusted data.
4. The app calls the model with the configured settings and logs the call.
5. The app extracts the text between the answer tags. If the tags are missing, the text is empty, or a leak pattern matches, the reply is rejected.
6. A rejected reply is added to the conversation with the retry instruction, and the model is called again. This repeats up to the configured number of attempts.
7. If every attempt fails, the fallback reply in `prompts/fallback.md` is shown.
8. The answer and any sources are printed. The log records the outcome.

## Safety design in the code

- **Structured output**: the reply must sit inside answer tags. Text outside the tags is discarded.
- **Leak detection**: narrow patterns for reasoning markers. Ordinary words such as "draft" or "constraints" are not blocked, because they are normal in replies.
- **Bounded retries**: a fixed number of attempts, with an explicit correction on each retry, rather than resending the same request.
- **Safe fallback**: a neutral reply is shown instead of a failed or leaked one.
- **Untrusted search content**: search results are labelled as data in the prompt. The system prompt tells the model not to follow instructions found in web pages.
- **No actions**: the app has no code path that logs into services, sends messages, or submits forms.

## Configuration

```yaml
model: "<exact model ID from the Token Factory model list>"
max_tokens: 800
temperature: 0.3
max_attempts: 3
enable_thinking: false   # test with false, then remove the line to compare
```

The thinking setting is an experiment. Test it, record the result in the log, and keep whichever setting produces clean replies. Confirm that Token Factory accepts the parameter for the chosen model before relying on it.

## Data

- **Stored:** the call log. It contains the model name, settings, finish reason, token counts, latency, and whether the output was clean. It does not store the person's message or the reply, unless the feedback control is used (planned).
- **Not stored:** personal details, account information, device data, or any profile in the MVP.
- **Sent to third parties:** the person's message and any search query go to Nebius Token Factory and Tavily to produce the reply. This must be stated in the consent text and the README.

## Logging for evaluation

Each log line records:

- timestamp
- model ID and thinking setting
- attempt number
- finish reason
- completion token count
- latency in seconds
- whether the reply was clean
- whether the fallback was used

Feedback marks (helpful, not right, confusing) will be added as a separate log entry type.

## Constraints and known limits

- Terminal interface only in the MVP.
- Model latency and availability depend on Nebius Token Factory.
- Context size must stay within the model's limit. Search snippets are truncated to keep the prompt short.
- Credits are limited. The log shows token use per call so the budget can be tracked.

## Planned extensions (not built)

- Web or mobile interface with voice input and output.
- Saved, consented, editable profile.
- Scheduled check-ins with notification controls.
- A separate evaluation script that runs the test set and writes a results file.
