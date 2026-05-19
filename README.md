# agent-tool-harness

`agent-tool-harness` is a small Python CLI contract for making internal tools discoverable, runnable, inspectable, and skill-exportable by AI agents.

It keeps the useful part of `CLI-Anything` — agent-facing tool contracts — without adopting a giant generated monorepo.

## Contract

Every command that an agent calls should return a stable JSON envelope:

```json
{ "ok": true, "data": {}, "artifacts": [], "warnings": [], "next_actions": [] }
```

Failures return:

```json
{ "ok": false, "error": { "type": "invalid_input", "message": "...", "fix": "..." } }
```

## MVP capabilities

- `registry list --json`: discover registered tools and capabilities
- `doctor --all --json`: run no-side-effect health checks
- `run xhs.<surface> <input.json> --preview-dir <dir> --json`: operate the local Xiaohongshu pending/cards/QA/preview pipeline and bundle outputs
- `run distill.<surface> <input.json> --preview-dir <dir> --json`: run distill-vault CLI surfaces and bundle their outputs
- `run site.<surface> <input.json> --preview-dir <dir> --json`: operate the personal Astro site and bundle status/build/link/deploy reports
- `inspect <preview-bundle-dir> --json`: summarize a generated preview bundle for review
- `run-backend <capability> <input.json> --backend-json <BackendSpec> --json`: run an explicit backend adapter
- `skill export <capability-or-tool> --json`: generate an agent-readable `SKILL.md`

The current XHS backend wraps Jarl's local `~/.hermes/scripts/xhs-pipeline` scripts: select pending items, generate local cards, run image QA, finalize the Telegram preview, and gate publishing. `xhs.publish` is marked `external_write` and is blocked unless `--allow-external-write` is supplied. Distill capabilities are a real self-use backend family: they shell out to the local `distill` CLI and bundle outputs for inspection.

### XHS capabilities

Read/preview-oriented capabilities:

```text
xhs.select-pending
xhs.generate-cards
xhs.image-qa
xhs.preview-gate
xhs.finalize-preview
```

Write-capable capabilities:

```text
xhs.publish
```

Typical self-use flow:

```bash
cat > /tmp/xhs-select-input.json <<'JSON'
{"pending_dir":"/home/jarl/.hermes/scripts/xhs-pipeline/pending"}
JSON
ath run xhs.select-pending /tmp/xhs-select-input.json --preview-dir .preview --json
ath inspect <bundle-dir> --json

cat > /tmp/xhs-generate-input.json <<'JSON'
{"pending_file":"/home/jarl/.hermes/scripts/xhs-pipeline/pending/<file>.json"}
JSON
ath run xhs.generate-cards /tmp/xhs-generate-input.json --preview-dir .preview --json
ath run xhs.image-qa /tmp/xhs-generate-input.json --preview-dir .preview --json
ath run xhs.finalize-preview /tmp/xhs-generate-input.json --preview-dir .preview --json
```

Only after explicit approval:

```bash
ath run xhs.publish /tmp/xhs-generate-input.json --preview-dir .preview --allow-external-write --json
```

Every XHS run writes an `xhs-image-cards` preview bundle with a command-specific JSON artifact such as `select-pending.json`, `generate-cards.json`, or `finalize-preview.json`. See `docs/xhs-harness-runbook.md` for the self-use runbook.

### Distill capabilities

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

All distill inputs include a vault path:

```json
{ "vault": "/home/jarl/all_in_one" }
```

Route/plan/capture/apply also require `intent`; search requires `query`.

The harness runs the corresponding `distill` command and writes a `distill-vault` preview bundle with a command-specific artifact such as `health.json`, `route.json`, or `search.txt`. Capabilities marked `external_write` are blocked by default; run them only after explicit approval with `--allow-external-write`.

Distill capability metadata lives in `src/agent_tool_harness/capabilities.py` and is reused by both the registry and backend dispatch to avoid drift. See `docs/distill-vault-harness-runbook.md` for the self-use runbook.

### Personal site capabilities

Read/preview-oriented capabilities:

```text
site.status
site.check-links
```

Write-capable capabilities:

```text
site.build
site.deploy
```

All site inputs include a site path:

```json
{ "site": "/home/jarl/personal-site" }
```

`site.status` bundles repository/build readiness metadata. `site.check-links` scans generated `dist/**/*.html` local links and reports missing targets. `site.build` runs `npm run build`; `site.deploy` pushes `dist/` to `gh-pages` through the direct dist deploy path. Build/deploy are marked `external_write` and are blocked unless `--allow-external-write` is supplied.

## Backend adapters

`run-backend` is the low-level adapter path for testing a backend without adding it to the registry yet:

```bash
agent-tool-harness run-backend fake.generate input.json \
  --preview-dir /tmp/ath-preview \
  --backend-json '{"kind":"subprocess","target":"python3 backend.py {input} {preview_dir}","timeout_seconds":300}' \
  --json
```

Subprocess backends must:

1. accept the rendered `{input}` and `{preview_dir}` arguments,
2. create a valid `preview-bundle/v1`, and
3. print JSON to stdout with `bundle_dir`:

```json
{ "bundle_dir": "/tmp/ath-preview/tool/bundle-001" }
```

The harness validates the bundle with `inspect` before returning success.

## Install

```bash
cd ~/agent-tool-harness
python3 -m pip install -e '.[dev]'
```

## Quickstart

```bash
agent-tool-harness registry list --json
agent-tool-harness doctor --all --json
printf '{"pending_dir":"/home/jarl/.hermes/scripts/xhs-pipeline/pending"}' > /tmp/xhs-select-input.json
agent-tool-harness run xhs.select-pending /tmp/xhs-select-input.json --preview-dir /tmp/ath-preview --json
printf '{"vault":"/home/jarl/all_in_one"}' > /tmp/distill-health-input.json
agent-tool-harness run distill.health /tmp/distill-health-input.json --preview-dir /tmp/ath-preview --json
printf '{"site":"/home/jarl/personal-site"}' > /tmp/site-input.json
agent-tool-harness run site.status /tmp/site-input.json --preview-dir /tmp/ath-preview --json
agent-tool-harness run site.check-links /tmp/site-input.json --preview-dir /tmp/ath-preview --json
agent-tool-harness inspect /tmp/ath-preview/xhs-image-cards/<bundle-name> --json
agent-tool-harness skill export xhs.generate-cards --json
agent-tool-harness skill export distill-vault --json
```

Alias:

```bash
ath registry list --json
```

## Preview bundle layout

A file-producing run emits a bundle like:

```text
/tmp/ath-preview/xhs-image-cards/20260519T030000Z_a09a928c_generate-cards/
├── manifest.json
├── summary.json
└── artifacts/
    └── generate-cards.json
```

`manifest.json` is for machines. `summary.json` is for agents and humans deciding the next action.

## Development

```bash
python3 -m pytest tests/ -q
ruff check src tests
```

## Project stance

This is not an all-purpose automation framework. It is a narrow harness layer:

- small, explicit contract
- no side effects during `doctor`
- file-producing work writes preview bundles
- skill docs generated from metadata
- backend metadata is explicit in each capability record
- preview bundles are inspectable before any publish/commit step
- real backends added incrementally behind stable capability IDs
