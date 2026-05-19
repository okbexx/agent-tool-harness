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

### `skill export CAPABILITY --json`

Generates a `SKILL.md` from capability metadata so agents can use the tool without hand-written instructions.

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
