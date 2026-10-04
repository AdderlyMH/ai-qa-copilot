Read AGENTS.md and HANDOFF.md first; they are authoritative.

Project: AI Quality Engineering Copilot (FastAPI + Next.js, uv + npm workspaces).
Run checks with: python scripts/tasks.py ci
Current task: add Anthropic Claude as a second model provider alongside OpenAI (default stays OpenAI). Do not change existing B1/v1 OpenAI behavior or evidence.
Rules: no model tool-calling loop, no secrets in code or logs, small commits, report real command output.