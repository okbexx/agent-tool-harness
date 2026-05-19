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
- `run xhs.generate-cards <input.json> --preview-dir <dir> --json`: generate a preview bundle
- `skill export xhs.generate-cards --json`: generate an agent-readable `SKILL.md`

The current backend intentionally emits Markdown preview artifacts. The production image backend can replace it later while keeping the JSON and `preview-bundle/v1` contract stable.

## Install

```bash
cd ~/agent-tool-harness
python3 -m pip install -e '.[dev]'
```

## Quickstart

```bash
agent-tool-harness registry list --json
agent-tool-harness doctor --all --json
agent-tool-harness run xhs.generate-cards examples/github-trending.json --preview-dir /tmp/ath-preview --json
agent-tool-harness skill export xhs.generate-cards --json
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
    ├── card-01.md
    ├── card-02.md
    └── card-03.md
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
- real backends added incrementally behind stable capability IDs
