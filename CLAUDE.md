# SummarizeAudio — Claude Instructions

## Model Selection

Prefer **Haiku** (`claude-haiku-4-5-20251001`) for low-reasoning work. Use `/model haiku` at session start when the task is primarily bash commands, file searches, or web scanning.

For mechanical tasks (running bash commands, reading logs, checking files, running tests, web searches), **dispatch a Haiku subagent** using the Agent tool with `model: "haiku"` instead of running directly.

Reserve Sonnet and Opus for tasks that require understanding, planning, or generation.
