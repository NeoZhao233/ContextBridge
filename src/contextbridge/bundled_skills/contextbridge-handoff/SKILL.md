---
name: contextbridge-handoff
description: Capture the current coding task for continuation in another agent. Use when the user asks to hand off, switch agents, preserve context, or continue elsewhere.
---

# Create a ContextBridge handoff

Work from the repository root.

1. Derive a concrete continuation task from the user's request and the current conversation. Include
   the unfinished outcome, not a generic phrase such as "continue working."
2. Run `contextbridge capture --task <task> --output .contextbridge/handoff.md`. Pass the task as one
   safely quoted argument. If `CONTEXTBRIDGE_API_KEY`, `CONTEXTBRIDGE_MODEL`, and
   `CONTEXTBRIDGE_BASE_URL` are configured, add `--extractor llm`; never print their values.
3. Read the generated pack. Check that it contains the current task and repository state and does not
   expose a secret. Correct the task and regenerate when it is misleading.
4. Tell the user where the pack was written and that the receiving agent can invoke
   `contextbridge-resume` from the same repository.

Do not commit `.contextbridge/handoff.md`; it is local handoff state. If the command is unavailable,
explain that ContextBridge must be installed instead of fabricating a successful handoff.
