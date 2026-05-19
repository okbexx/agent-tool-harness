# XHS Harness Runbook

This runbook is for Jarl's self-use Xiaohongshu pipeline through `agent-tool-harness` / `ath`.

The harness is the contract layer only. Business logic stays in local scripts under:

```text
/home/jarl/.hermes/scripts/xhs-pipeline/
```

## Capability set

Read / local preview capabilities:

```text
xhs.select-pending
xhs.generate-cards
xhs.image-qa
xhs.preview-gate
xhs.finalize-preview
```

External write capability:

```text
xhs.publish
```

`xhs.publish` is blocked by default. Do not run it unless Jarl explicitly approves publishing in the current task. When approval is present, add `--allow-external-write`.

## Required flow

1. Check the tool wiring:

```bash
ath doctor xhs-image-cards --json
```

2. Select the newest pending item that still needs images:

```bash
cat > /tmp/xhs-select-input.json <<'JSON'
{"pending_dir":"/home/jarl/.hermes/scripts/xhs-pipeline/pending"}
JSON
ath run xhs.select-pending /tmp/xhs-select-input.json --preview-dir .preview --json
ath inspect <bundle-dir> --json
```

3. Generate local card images for the selected pending file:

```bash
cat > /tmp/xhs-generate-input.json <<'JSON'
{"pending_file":"/home/jarl/.hermes/scripts/xhs-pipeline/pending/<file>.json"}
JSON
ath run xhs.generate-cards /tmp/xhs-generate-input.json --preview-dir .preview --json
ath inspect <bundle-dir> --json
```

4. Run image QA:

```bash
ath run xhs.image-qa /tmp/xhs-generate-input.json --preview-dir .preview --json
ath inspect <bundle-dir> --json
```

5. Finalize preview only after QA:

```bash
ath run xhs.finalize-preview /tmp/xhs-generate-input.json --preview-dir .preview --json
ath inspect <bundle-dir> --json
```

Only use the preview payload if `allow_preview=true` in the bundled artifact and the inspect summary has no blocking warnings.

6. Publish only after explicit approval:

```bash
ath run xhs.publish /tmp/xhs-generate-input.json --preview-dir .preview --allow-external-write --json
```

## Bundle outputs

Every capability returns the stable harness envelope and writes a `preview-bundle/v1`:

```text
.preview/xhs-image-cards/<timestamp>_<hash>_<capability>/
├── manifest.json
├── summary.json
└── artifacts/
    └── <capability-artifact>.json
```

Artifacts:

- `xhs.select-pending` -> `select-pending.json`
- `xhs.generate-cards` -> `generate-cards.json`
- `xhs.image-qa` -> `image-qa.json`
- `xhs.preview-gate` -> `preview-gate.json`
- `xhs.finalize-preview` -> `finalize-preview.json`
- `xhs.publish` -> `publish.json`

## Safety boundaries

- `doctor` must be no-side-effect.
- Local/preview capabilities may create preview bundles and local generated images only.
- `xhs.publish` may publish to Xiaohongshu and may remove the pending file after success; it is `external_write`.
- Never store cookies, tokens, credentials, or browser session data in repo docs, tests, or bundles. Treat any such value as `[REDACTED]`.
- Do not run a real publish smoke test without explicit user approval.

## Troubleshooting

- `missing_dependency`: check that scripts exist under `~/.hermes/scripts/xhs-pipeline/`.
- `invalid_input`: check `pending_file`, `pending_dir`, or `target` paths.
- `backend_timeout`: run the underlying script directly or increase `timeout_seconds` in the input JSON.
- `unsafe_side_effect`: this is expected for `xhs.publish` unless `--allow-external-write` is present.
