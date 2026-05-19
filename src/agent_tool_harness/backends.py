from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .models import Artifact, HarnessResponse
from .registry import DEFAULT_TOOLS


def canonical_json(data: Any) -> bytes:
    raw = json.dumps(
        data,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return raw.encode("utf-8")


def fingerprint(data: Any) -> str:
    return hashlib.sha256(canonical_json(data)).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"Input file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Input must be JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("Input JSON must be an object")
    return data


def tool_for_capability(capability_id: str):
    for tool in DEFAULT_TOOLS:
        for capability in tool.capabilities:
            if capability.id == capability_id:
                return tool, capability
    raise KeyError(capability_id)


def write_card_artifact(path: Path, title: str, body: str) -> None:
    path.write_text(f"# {title}\n\n{body}\n", encoding="utf-8")


def run_xhs_generate_cards(input_path: Path, preview_dir: Path | None = None) -> HarnessResponse:
    data = load_json(input_path)
    repos = data.get("repos")
    if not isinstance(repos, list) or not repos:
        return HarnessResponse.failure(
            "invalid_input",
            "Input JSON must contain non-empty repos list",
        )

    preview_root = (preview_dir or Path(".preview")).expanduser().resolve()
    short_hash = fingerprint(data)[:8]
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    bundle_dir = preview_root / "xhs-image-cards" / f"{timestamp}_{short_hash}_generate-cards"
    artifacts_dir = bundle_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=False)

    artifact_records: list[dict[str, str]] = []
    for idx, repo in enumerate(repos[:3], start=1):
        if not isinstance(repo, dict):
            return HarnessResponse.failure("invalid_input", "Each repo entry must be an object")
        repo_name = str(repo.get("name") or f"repo-{idx}")
        artifact_path = artifacts_dir / f"card-{idx:02d}.md"
        write_card_artifact(
            artifact_path,
            f"Card {idx}: {repo_name}",
            str(repo.get("why") or data.get("trend_summary") or "No summary."),
        )
        artifact_records.append(
            {
                "id": f"card-{idx:02d}",
                "kind": "markdown-preview",
                "role": "preview",
                "path": str(artifact_path.relative_to(bundle_dir)),
                "label": repo_name,
            }
        )

    manifest = {
        "protocol_version": "preview-bundle/v1",
        "tool": "xhs-image-cards",
        "capability": "xhs.generate-cards",
        "status": "ok",
        "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "source": {
            "input_path": str(input_path.expanduser().resolve()),
            "input_fingerprint": f"sha256:{fingerprint(data)}",
        },
        "summary_path": "summary.json",
        "artifacts": artifact_records,
    }
    summary = {
        "headline": f"Generated {len(artifact_records)} preview cards",
        "facts": {
            "card_count": len(artifact_records),
            "trend_summary": str(data.get("trend_summary", "")),
            "format": "markdown-preview artifact",
        },
        "warnings": ["MVP backend emits Markdown previews; replace with image backend later."],
        "next_actions": [
            "Wire this capability to baoyu-image-cards or gpt-image-2 when production "
            "image generation is needed.",
            "Keep preview-bundle/v1 manifest + summary contract stable.",
        ],
    }
    (bundle_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (bundle_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    return HarnessResponse.success(
        data={"bundle_dir": str(bundle_dir), "card_count": len(artifact_records)},
        artifacts=[Artifact(kind="preview_bundle", path=str(bundle_dir), role="output")],
        warnings=summary["warnings"],
        next_actions=summary["next_actions"],
    )


def run_capability(
    capability_id: str,
    input_path: Path,
    preview_dir: Path | None = None,
) -> HarnessResponse:
    if capability_id == "xhs.generate-cards":
        return run_xhs_generate_cards(input_path=input_path, preview_dir=preview_dir)
    return HarnessResponse.failure(
        "unknown_capability",
        f"Unsupported capability: {capability_id}",
        "Run registry list --json",
    )
