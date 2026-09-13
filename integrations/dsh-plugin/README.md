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

## Source and target roles

This JavaScript package is the target adapter: DSH can consume memories synchronized from any
supported agent. The Python package also includes the matching DSH source adapter, so later Claude
Code, Codex, or DSH sessions can resume work that started in DSH. Configure
`CONTEXTBRIDGE_DSH_SESSION_ROOT` for discovery, or pass `--source dsh --path ...` explicitly. DSH's
default `.jsonl.zstd` persistence requires `pip install 'contextbridge[dsh]'`.

## Verification status

`tool.js` has executable contract tests covering workspace resolution, bounded CLI arguments, output
normalization, and cancellation-signal forwarding. The bundle also passes JavaScript syntax and
package-content checks. Full profile boot validation still requires a DSH checkout or npm release
whose complete dependency graph is publicly resolvable.
