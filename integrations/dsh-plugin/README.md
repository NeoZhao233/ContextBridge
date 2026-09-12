# ContextBridge DSH adapter

This thin DeepSeek Harness plugin registers one model-facing tool:

```text
contextbridge_handoff(task, token_budget?)
```

The tool resolves the current DSH session workspace, invokes the installed Python ContextBridge
CLI in that directory, and returns a bounded Context Pack. The adapter owns no memory or storage;
those capabilities stay in the Python Core.

## Local installation

1. Install ContextBridge so the `contextbridge` command is on `PATH`.
2. From the ContextBridge repository root, install the local bundle into the DSH profile.
3. Restart the profile:

```bash
dsh plugin --profile web add ./integrations/dsh-plugin
dsh --profile web
```

If the executable is not named `contextbridge`, set `CONTEXTBRIDGE_COMMAND` before starting DSH.

The adapter follows DSH's public plugin shape: synchronous `apply(ctx)`, an explicit `tools`
service dependency, `ctx.tools.register()`, `defineTool()` argument validation, and cancellation via
the tool execution signal.

## Current scope

This is a DSH target adapter: DSH can consume memories previously synchronized from Claude Code or
Codex. Importing DSH's own session events back into ContextBridge is a separate future source plugin.

## Verification status

`tool.js` has executable contract tests covering workspace resolution, bounded CLI arguments, output
normalization, and cancellation-signal forwarding. The bundle also passes JavaScript syntax and
package-content checks. Full profile boot validation still requires a DSH checkout or npm release
whose complete dependency graph is publicly resolvable.
