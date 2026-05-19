# Contract Reference

## JSON envelope

Success:

```json
{
  "ok": true,
  "data": {},
  "artifacts": [],
  "warnings": [],
  "next_actions": []
}
```

Failure:

```json
{
  "ok": false,
  "error": {
    "type": "invalid_input",
    "message": "Input JSON must contain non-empty repos list",
    "fix": "Optional remediation hint"
  }
}
```

## Commands

### `registry list --json`

Returns registered harness tools and their capabilities.

### `doctor [TOOL] --json`

Runs health checks that must not write files, call paid APIs, publish content, or mutate remote systems.

### `run CAPABILITY INPUT --preview-dir DIR --json`

Runs one capability. File-producing capabilities should emit `artifacts[]` pointing to a preview bundle.

### `run-backend CAPABILITY INPUT --backend-json JSON --preview-dir DIR --json`

Runs one capability through an explicit backend adapter before promoting that adapter into the registry. This is useful for testing real CLIs behind the harness contract.

For `subprocess` backends, `target` is a command template. The harness renders:

- `{input}` as the absolute JSON input path
- `{preview_dir}` as the absolute preview root

The subprocess must create a valid `preview-bundle/v1` and print JSON to stdout:

```json
{ "bundle_dir": "/absolute/path/to/bundle" }
```

The harness calls `inspect` internally and only returns success when the bundle is valid and its manifest capability matches the requested capability.

### `inspect BUNDLE_DIR --json`

Reads `manifest.json` and `summary.json` from a generated preview bundle and returns a compact review payload. Agents should inspect before publishing, committing, or handing off generated artifacts.

### `skill export CAPABILITY --json`

Generates a `SKILL.md` from capability metadata so agents can use the tool without hand-written instructions.

### Distill capability family

The harness exposes the local `distill` CLI as agent-callable capabilities. Every capability takes a JSON object with `vault`; route/plan/capture/apply also take `intent`; search takes `query`.

Read/preview-oriented capabilities:

```text
distill.status
distill.health
distill.capabilities
distill.instance-doctor
distill.upgrade-plan
distill.lint-check
distill.route
distill.plan
distill.search
distill.promote-dry-run
distill.pipeline-run
```

Write-capable capabilities:

```text
distill.lint-fix
distill.promote-auto
distill.capture
distill.apply
```

Each run writes a `preview-bundle/v1` under `.preview/distill-vault/` with a command-specific artifact (`status.json`, `health.json`, `route.json`, `search.txt`, etc.). The bundle can then be reviewed through `inspect`.

Example:

```json
{
  "vault": "/home/jarl/all_in_one",
  "intent": "记录 agent-tool-harness 接入 distill 能力"
}
```

### `distill.health`

Runs `distill -v <vault> health --format json` and wraps the result in a `preview-bundle/v1`:

```json
{
  "vault": "/home/jarl/all_in_one"
}
```

Returned bundle shape:

```text
.preview/distill-vault/<timestamp>_<hash>_health/
├── manifest.json
├── summary.json
└── artifacts/
    └── health.json
```

The harness keeps the vault read-only for this capability; the side effect is only writing the preview bundle.

## Capability backend metadata

Each capability may declare an explicit backend record so agents can distinguish stable public contract from replaceable implementation detail:

```json
{
  "backend": {
    "kind": "python_function",
    "target": "run_xhs_generate_cards",
    "timeout_seconds": 300
  }
}
```

`kind` is intentionally narrow today: `python_function` for in-process MVP backends and `subprocess` for adapters around existing CLIs. Subprocess targets may use `{input}` and `{preview_dir}` placeholders; they are rendered as absolute paths before execution.

## Preview bundle v1

Required files:

- `manifest.json`: protocol, tool, capability, source fingerprint, artifact records
- `summary.json`: human/agent-readable headline, facts, warnings, next actions
- `artifacts/*`: produced files

Required manifest keys:

```json
{
  "protocol_version": "preview-bundle/v1",
  "tool": "xhs-image-cards",
  "capability": "xhs.generate-cards",
  "status": "ok",
  "created_at": "2026-05-19T03:00:00Z",
  "source": {
    "input_path": "...",
    "input_fingerprint": "sha256:..."
  },
  "summary_path": "summary.json",
  "artifacts": []
}
```
