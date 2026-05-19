# Distill Vault Harness Runbook

Use this runbook when an agent needs to access `distill-vault` through `agent-tool-harness` / `ath`.

## Required flow

1. Discover capabilities when unsure:

```bash
ath registry list --json
```

2. Run the deep no-side-effect doctor:

```bash
ath doctor distill-vault --json
```

3. Write a JSON input file.
4. Run one capability with a preview directory:

```bash
ath run distill.route input.json --preview-dir .preview --json
```

5. Read `artifacts[0].path` from the response and inspect the bundle:

```bash
ath inspect <bundle-dir> --json
```

6. Use the inspected `headline`, `facts`, `warnings`, and `next_actions` before continuing.

## Safe read / preview capabilities

- `distill.status`
- `distill.health`
- `distill.capabilities`
- `distill.instance-doctor`
- `distill.upgrade-plan`
- `distill.lint-check`
- `distill.promote-dry-run`
- `distill.pipeline-run`
- `distill.route`
- `distill.plan`
- `distill.search`

## Write-capable capabilities

These are blocked by default:

- `distill.lint-fix`
- `distill.promote-auto`
- `distill.capture`
- `distill.apply`

Do not run write-capable capabilities without explicit user approval.
When approval is present, add `--allow-external-write`:

```bash
ath run distill.capture input.json --preview-dir .preview --allow-external-write --json
```

Without that flag, `ath run` returns `unsafe_side_effect` and does not invoke the backend.

## Example: route a knowledge task

```bash
cat > /tmp/distill-route-input.json <<'JSON'
{"vault":"/home/jarl/all_in_one","intent":"记录一个最小进展"}
JSON
ath run distill.route /tmp/distill-route-input.json --preview-dir .preview --json
ath inspect <bundle-dir> --json
```

## Example: search the vault

```bash
cat > /tmp/distill-search-input.json <<'JSON'
{"vault":"/home/jarl/all_in_one","query":"agent-tool-harness","limit":5}
JSON
ath run distill.search /tmp/distill-search-input.json --preview-dir .preview --json
ath inspect <bundle-dir> --json
```

## Generated skill

Generate the matching agent skill text with:

```bash
ath skill export distill-vault --json
```

The generated skill is intentionally not auto-installed; install it into a runtime-specific skill directory only when the operator wants that persistent behavior.
