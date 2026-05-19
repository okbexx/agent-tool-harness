from __future__ import annotations

import hashlib
import json
import shlex
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .models import Artifact, BackendSpec, HarnessResponse
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


def next_action_text(action: Any) -> str:
    if isinstance(action, str):
        return action
    if isinstance(action, dict):
        label = action.get("label") or action.get("title") or action.get("action")
        command = action.get("command")
        if label and command and command != label:
            return f"{label}: {command}"
        if label:
            return str(label)
        if command:
            return str(command)
    return json.dumps(action, ensure_ascii=False, sort_keys=True)


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


DISTILL_COMMANDS: dict[str, dict[str, Any]] = {
    "distill.status": {
        "args": ["status", "--format", "json"],
        "artifact": "status.json",
        "output": "json",
        "side_effect": "local_files",
    },
    "distill.health": {
        "args": ["health", "--format", "json"],
        "artifact": "health.json",
        "output": "json",
        "side_effect": "local_files",
    },
    "distill.capabilities": {
        "args": ["capabilities", "--format", "json"],
        "artifact": "capabilities.json",
        "output": "json",
        "side_effect": "local_files",
    },
    "distill.instance-doctor": {
        "args": ["doctor", "--instance-upgrade", "--format", "json"],
        "artifact": "instance-doctor.json",
        "output": "json",
        "side_effect": "local_files",
    },
    "distill.upgrade-plan": {
        "args": ["upgrade-plan", "--format", "json"],
        "artifact": "upgrade-plan.json",
        "output": "json",
        "side_effect": "local_files",
    },
    "distill.lint-check": {
        "args": ["lint", "--format", "json"],
        "artifact": "lint-check.json",
        "output": "json",
        "side_effect": "local_files",
    },
    "distill.lint-fix": {
        "args": ["lint", "--fix", "--format", "json"],
        "artifact": "lint-fix.json",
        "output": "json",
        "side_effect": "external_write",
    },
    "distill.promote-dry-run": {
        "args": ["promote", "--dry-run", "--format", "json"],
        "artifact": "promote-dry-run.txt",
        "output": "json_or_stdout",
        "side_effect": "local_files",
    },
    "distill.promote-auto": {
        "args": ["promote", "--auto", "--format", "json"],
        "artifact": "promote-auto.json",
        "output": "json",
        "side_effect": "external_write",
    },
    "distill.pipeline-run": {
        "args": ["run", "--format", "json"],
        "artifact": "pipeline-run.json",
        "output": "json",
        "side_effect": "local_files",
    },
    "distill.route": {
        "artifact": "route.json",
        "output": "json",
        "side_effect": "local_files",
    },
    "distill.plan": {
        "artifact": "plan.json",
        "output": "json",
        "side_effect": "local_files",
    },
    "distill.capture": {
        "artifact": "capture.json",
        "output": "json",
        "side_effect": "external_write",
    },
    "distill.apply": {
        "artifact": "apply.json",
        "output": "json",
        "side_effect": "external_write",
    },
    "distill.search": {
        "artifact": "search.txt",
        "output": "text",
        "side_effect": "local_files",
    },
}


def distill_command_args(capability_id: str, data: dict[str, Any]) -> list[str]:
    if capability_id in {"distill.route", "distill.plan", "distill.capture", "distill.apply"}:
        intent = str(data.get("intent") or "").strip()
        if not intent:
            raise ValueError("Input JSON must contain non-empty intent")
        command = capability_id.removeprefix("distill.")
        args = [command, intent, "--format", "json"]
        project = str(data.get("project") or "").strip()
        if project:
            args.extend(["--project", project])
        return args
    if capability_id == "distill.search":
        query = str(data.get("query") or "").strip()
        if not query:
            raise ValueError("Input JSON must contain non-empty query")
        args = ["search", query]
        if data.get("limit") is not None:
            args.extend(["--limit", str(data["limit"])])
        if data.get("type"):
            args.extend(["--type", str(data["type"])])
        if data.get("mode"):
            args.extend(["--mode", str(data["mode"])])
        return args
    spec = DISTILL_COMMANDS.get(capability_id)
    if not spec:
        raise KeyError(capability_id)
    args = list(spec.get("args") or [])
    if capability_id == "distill.pipeline-run":
        if data.get("incremental"):
            args.append("--incremental")
        if data.get("worker_mode"):
            args.extend(["--worker-mode", str(data["worker_mode"])])
        if data.get("workers") is not None:
            args.extend(["--workers", str(data["workers"])])
    return args


def distill_summary_headline(capability_id: str, payload: Any) -> str:
    if isinstance(payload, dict):
        if payload.get("runtime_stage"):
            total = payload.get("total_objects")
            if total is not None:
                return f"{capability_id}: {payload['runtime_stage']} ({total} objects)"
            return f"{capability_id}: {payload['runtime_stage']}"
        if payload.get("status") and payload.get("action"):
            return f"{capability_id}: {payload['action']} {payload['status']}"
        if payload.get("adoption_status"):
            return f"{capability_id}: {payload['adoption_status']}"
    if isinstance(payload, list):
        return f"{capability_id}: {len(payload)} item(s)"
    if isinstance(payload, str):
        first_line = payload.splitlines()[0] if payload.splitlines() else "completed"
        return f"{capability_id}: {first_line[:120]}"
    return f"{capability_id}: completed"


def distill_next_actions(payload: Any) -> list[str]:
    if isinstance(payload, dict):
        raw_actions = payload.get("next_steps") or payload.get("recommended_actions") or []
        if isinstance(raw_actions, list):
            return [next_action_text(action) for action in raw_actions]
    return []


def run_distill_command(
    capability_id: str,
    input_path: Path,
    preview_dir: Path | None = None,
) -> HarnessResponse:
    spec = DISTILL_COMMANDS.get(capability_id)
    if not spec:
        return HarnessResponse.failure(
            "unknown_capability",
            f"Unsupported capability: {capability_id}",
            "Run registry list --json",
        )
    data = load_json(input_path)
    vault_raw = data.get("vault") or "."
    vault = Path(str(vault_raw)).expanduser().resolve()
    if not vault.exists():
        return HarnessResponse.failure(
            "invalid_input",
            f"Vault path does not exist: {vault}",
            "Pass input JSON with an existing vault path",
        )
    try:
        distill_args = distill_command_args(capability_id, data)
    except ValueError as exc:
        return HarnessResponse.failure("invalid_input", str(exc))
    except KeyError:
        return HarnessResponse.failure(
            "unknown_capability",
            f"Unsupported capability: {capability_id}",
            "Run registry list --json",
        )

    completed = subprocess.run(
        ["distill", "-v", str(vault), *distill_args],
        capture_output=True,
        text=True,
        timeout=int(data.get("timeout_seconds") or 300),
        check=False,
    )
    if completed.returncode != 0:
        return HarnessResponse.failure(
            "backend_failed",
            completed.stderr.strip() or completed.stdout.strip() or f"{capability_id} failed",
            "Run the distill command directly for details",
        )

    output_kind = str(spec.get("output") or "json")
    if output_kind in {"json", "json_or_stdout"}:
        try:
            payload: Any = json.loads(completed.stdout)
        except json.JSONDecodeError:
            if output_kind == "json_or_stdout":
                payload = completed.stdout
                output_kind = "text"
            else:
                return HarnessResponse.failure(
                    "invalid_backend_output",
                    "distill command did not return valid JSON",
                    "Check distill CLI output",
                )
    else:
        payload = completed.stdout

    preview_root = (preview_dir or Path(".preview")).expanduser().resolve()
    safe_suffix = capability_id.removeprefix("distill.").replace(".", "-")
    short_hash = fingerprint({"capability": capability_id, "input": data, "payload": payload})[:8]
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    bundle_dir = preview_root / "distill-vault" / f"{timestamp}_{short_hash}_{safe_suffix}"
    artifacts_dir = bundle_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=False)

    artifact_name = str(spec["artifact"])
    artifact_path = artifacts_dir / artifact_name
    if output_kind == "json":
        artifact_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    else:
        artifact_path.write_text(str(payload), encoding="utf-8")

    facts: dict[str, Any] = {"vault": str(vault), "capability": capability_id}
    if isinstance(payload, dict):
        for key in (
            "runtime_stage",
            "total_objects",
            "broken_links",
            "true_orphans",
            "has_checkpoint",
            "task_kind",
            "confidence",
            "status",
            "action",
            "adoption_status",
            "issue_count",
        ):
            if key in payload:
                facts[key] = payload[key]
    elif isinstance(payload, list):
        facts["item_count"] = len(payload)
    elif isinstance(payload, str):
        facts["line_count"] = len(payload.splitlines())

    summary = {
        "headline": distill_summary_headline(capability_id, payload),
        "facts": facts,
        "warnings": [],
        "next_actions": distill_next_actions(payload),
    }
    manifest = {
        "protocol_version": "preview-bundle/v1",
        "tool": "distill-vault",
        "capability": capability_id,
        "status": "ok",
        "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "source": {
            "input_path": str(input_path.expanduser().resolve()),
            "input_fingerprint": f"sha256:{fingerprint(data)}",
        },
        "summary_path": "summary.json",
        "artifacts": [
            {
                "id": artifact_name.removesuffix(".json").removesuffix(".txt"),
                "kind": output_kind,
                "role": "distill_result",
                "path": str(artifact_path.relative_to(bundle_dir)),
                "label": artifact_name,
            }
        ],
    }
    (bundle_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (bundle_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    return HarnessResponse.success(
        data={
            "bundle_dir": str(bundle_dir),
            "capability": capability_id,
            **facts,
        },
        artifacts=[Artifact(kind="preview_bundle", path=str(bundle_dir), role="output")],
        warnings=summary["warnings"],
        next_actions=summary["next_actions"],
    )


def run_distill_health(input_path: Path, preview_dir: Path | None = None) -> HarnessResponse:
    return run_distill_command("distill.health", input_path=input_path, preview_dir=preview_dir)


def inspect_preview_bundle(bundle_dir: Path) -> HarnessResponse:
    manifest_path = bundle_dir / "manifest.json"
    summary_path = bundle_dir / "summary.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        return HarnessResponse.failure(
            "invalid_bundle",
            f"Preview bundle is missing required file: {exc.filename}",
            "Pass a directory containing manifest.json and summary.json",
        )
    except json.JSONDecodeError as exc:
        return HarnessResponse.failure(
            "invalid_bundle",
            f"Preview bundle contains invalid JSON: {exc}",
            "Regenerate the preview bundle",
        )

    artifacts = manifest.get("artifacts") or []
    if not isinstance(artifacts, list):
        return HarnessResponse.failure(
            "invalid_bundle",
            "manifest.json artifacts must be a list",
            "Regenerate the preview bundle",
        )

    return HarnessResponse.success(
        data={
            "protocol_version": manifest.get("protocol_version"),
            "tool": manifest.get("tool"),
            "capability": manifest.get("capability"),
            "status": manifest.get("status"),
            "headline": summary.get("headline"),
            "facts": summary.get("facts") or {},
            "artifact_count": len(artifacts),
        },
        warnings=summary.get("warnings") or [],
        next_actions=summary.get("next_actions") or [],
    )


def render_backend_command(backend: BackendSpec, input_path: Path, preview_dir: Path) -> list[str]:
    rendered = backend.target.format(
        input=shlex.quote(str(input_path.expanduser().resolve())),
        preview_dir=shlex.quote(str(preview_dir.expanduser().resolve())),
    )
    return shlex.split(rendered)


def run_subprocess_backend(
    capability_id: str,
    input_path: Path,
    preview_dir: Path | None,
    backend: BackendSpec,
) -> HarnessResponse:
    if backend.kind != "subprocess":
        return HarnessResponse.failure(
            "unsupported_backend",
            f"Unsupported backend kind: {backend.kind}",
            "Use a subprocess backend spec",
        )

    preview_root = (preview_dir or Path(".preview")).expanduser().resolve()
    preview_root.mkdir(parents=True, exist_ok=True)
    command = render_backend_command(backend, input_path=input_path, preview_dir=preview_root)
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=backend.timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return HarnessResponse.failure(
            "backend_timeout",
            f"Backend timed out after {backend.timeout_seconds} seconds",
            "Increase timeout_seconds or make the backend faster",
        )
    except OSError as exc:
        return HarnessResponse.failure(
            "backend_launch_failed",
            str(exc),
            "Check backend target command",
        )

    if completed.returncode != 0:
        return HarnessResponse.failure(
            "backend_failed",
            completed.stderr.strip() or completed.stdout.strip() or "Backend command failed",
            "Fix backend command and rerun",
        )

    try:
        output = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return HarnessResponse.failure(
            "invalid_backend_output",
            "Backend stdout must be JSON",
            "Backend must print JSON with bundle_dir",
        )
    bundle_dir_raw = output.get("bundle_dir") if isinstance(output, dict) else None
    if not bundle_dir_raw:
        return HarnessResponse.failure(
            "invalid_backend_output",
            "Backend output is missing bundle_dir",
            "Backend must print JSON with bundle_dir",
        )

    bundle_dir = Path(str(bundle_dir_raw)).expanduser().resolve()
    inspection = inspect_preview_bundle(bundle_dir)
    if not inspection.ok:
        return inspection

    if inspection.data.get("capability") != capability_id:
        return HarnessResponse.failure(
            "invalid_backend_output",
            f"Preview bundle capability does not match requested capability: {capability_id}",
            "Backend manifest capability must match requested capability",
        )

    return HarnessResponse.success(
        data={"bundle_dir": str(bundle_dir), "backend_kind": "subprocess"},
        artifacts=[Artifact(kind="preview_bundle", path=str(bundle_dir), role="output")],
        warnings=inspection.warnings,
        next_actions=inspection.next_actions,
    )


def run_capability(
    capability_id: str,
    input_path: Path,
    preview_dir: Path | None = None,
) -> HarnessResponse:
    if capability_id == "xhs.generate-cards":
        return run_xhs_generate_cards(input_path=input_path, preview_dir=preview_dir)
    if capability_id in DISTILL_COMMANDS:
        return run_distill_command(capability_id, input_path=input_path, preview_dir=preview_dir)
    return HarnessResponse.failure(
        "unknown_capability",
        f"Unsupported capability: {capability_id}",
        "Run registry list --json",
    )
