from __future__ import annotations

import hashlib
import json
import re
import shlex
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .capabilities import DISTILL_CAPABILITY_SPECS, SITE_CAPABILITY_SPECS, XHS_CAPABILITY_SPECS
from .models import Artifact, BackendSpec, HarnessResponse
from .registry import DEFAULT_TOOLS

XHS_PIPELINE_DIR = Path.home() / ".hermes/scripts/xhs-pipeline"
XHS_SCRIPT_PATHS = {
    "script_select_pending": XHS_PIPELINE_DIR / "select_latest_pending_without_images.py",
    "script_generate_cards": XHS_PIPELINE_DIR / "generate_xhs_cards.py",
    "script_image_qa": XHS_PIPELINE_DIR / "xhs_image_qa.py",
    "script_preview_gate": XHS_PIPELINE_DIR / "xhs_preview_gate.py",
    "script_finalize_preview": XHS_PIPELINE_DIR / "xhs_finalize_preview.py",
    "script_publish_xhs": XHS_PIPELINE_DIR / "publish_xhs.py",
}
SENSITIVE_TEXT_REPLACEMENTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?i)\b(Bearer\s+)[A-Za-z0-9._~+/=-]+"), r"\1[REDACTED]"),
    (
        re.compile(
            r"(?i)\b(api[_-]?key|token|secret|password|cookie|authorization|credential|session)"
            r"(\s*[:=]\s*)([^\s,;]+)"
        ),
        r"\1\2[REDACTED]",
    ),
    (re.compile(r"(https://[^:/@\s]+:)[^@\s]+(@)"), r"\1[REDACTED]\2"),
)


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


def redact_sensitive_text(text: str) -> str:
    redacted = text
    for pattern, replacement in SENSITIVE_TEXT_REPLACEMENTS:
        redacted = pattern.sub(replacement, redacted)
    return redacted


def redact_sensitive_data(value: Any) -> Any:
    if isinstance(value, str):
        return redact_sensitive_text(value)
    if isinstance(value, list):
        return [redact_sensitive_data(item) for item in value]
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            sensitive_key = re.search(
                r"(?i)(api[_-]?key|token|secret|password|cookie|authorization|credential|session)",
                str(key),
            )
            if sensitive_key:
                redacted[str(key)] = "[REDACTED]"
            else:
                redacted[str(key)] = redact_sensitive_data(item)
        return redacted
    return value


def tool_for_capability(capability_id: str):
    for tool in DEFAULT_TOOLS:
        for capability in tool.capabilities:
            if capability.id == capability_id:
                return tool, capability
    raise KeyError(capability_id)


def doctor_tool_status(tool) -> dict[str, Any]:
    checks: list[dict[str, Any]] = [
        {"name": "registry_entry", "ok": True},
        {"name": "json_contract", "ok": True},
        {"name": "preview_protocol", "ok": True},
    ]
    if tool.name == "xhs-image-cards":
        for check_name, script_path in XHS_SCRIPT_PATHS.items():
            checks.append(
                {
                    "name": check_name,
                    "ok": script_path.exists(),
                    "detail": str(script_path),
                }
            )
        registry_by_id = {capability.id: capability for capability in tool.capabilities}
        checks.append(
            {
                "name": "registry_backend_consistency",
                "ok": set(registry_by_id) == set(XHS_CAPABILITY_SPECS)
                and all(
                    capability.backend is not None
                    and capability.backend.target == "run_xhs_command"
                    for capability in registry_by_id.values()
                ),
                "detail": (
                    f"{len(registry_by_id)} registry capabilities; "
                    f"{len(XHS_CAPABILITY_SPECS)} specs"
                ),
            }
        )
        external_write_ids = sorted(
            capability.id
            for capability in tool.capabilities
            if capability.side_effect == "external_write"
        )
        checks.append(
            {
                "name": "external_write_gated",
                "ok": external_write_ids == ["xhs.publish"],
                "detail": ", ".join(external_write_ids),
            }
        )
        return {
            "name": tool.name,
            "ok": all(check["ok"] for check in checks),
            "side_effect": tool.side_effects.get("doctor", "none"),
            "checks": checks,
        }

    if tool.name != "distill-vault":
        return {
            "name": tool.name,
            "ok": True,
            "side_effect": tool.side_effects.get("doctor", "none"),
            "checks": checks,
        }

    distill_path = shutil.which("distill")
    checks.append(
        {
            "name": "binary_available",
            "ok": bool(distill_path),
            "detail": distill_path or "distill not found on PATH",
        }
    )
    if distill_path:
        try:
            help_result = subprocess.run(
                [distill_path, "--help"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            checks.append(
                {
                    "name": "help_available",
                    "ok": help_result.returncode == 0,
                    "detail": (help_result.stderr or help_result.stdout).strip()[:240],
                }
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            checks.append({"name": "help_available", "ok": False, "detail": str(exc)})
    else:
        checks.append({"name": "help_available", "ok": False, "detail": "distill missing"})

    registry_by_id = {capability.id: capability for capability in tool.capabilities}
    checks.append(
        {
            "name": "registry_backend_consistency",
            "ok": set(registry_by_id) == set(DISTILL_CAPABILITY_SPECS)
            and all(
                capability.backend is not None
                and capability.backend.target == "run_distill_command"
                for capability in registry_by_id.values()
            ),
            "detail": (
                f"{len(registry_by_id)} registry capabilities; "
                f"{len(DISTILL_CAPABILITY_SPECS)} specs"
            ),
        }
    )
    external_write_ids = sorted(
        capability.id
        for capability in tool.capabilities
        if capability.side_effect == "external_write"
    )
    checks.append(
        {
            "name": "external_write_gated",
            "ok": bool(external_write_ids),
            "detail": ", ".join(external_write_ids),
        }
    )

    return {
        "name": tool.name,
        "ok": all(check["ok"] for check in checks),
        "side_effect": tool.side_effects.get("doctor", "none"),
        "checks": checks,
    }


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


DISTILL_COMMANDS = DISTILL_CAPABILITY_SPECS
SITE_COMMANDS = SITE_CAPABILITY_SPECS
XHS_COMMANDS = XHS_CAPABILITY_SPECS


def xhs_pending_file_from_input(data: dict[str, Any]) -> Path:
    pending_raw = data.get("pending_file")
    if not pending_raw:
        raise ValueError("Input JSON must include pending_file")
    pending_file = Path(str(pending_raw)).expanduser().resolve()
    if not pending_file.exists():
        raise ValueError(f"Pending file does not exist: {pending_file}")
    if pending_file.suffix.lower() != ".json":
        raise ValueError(f"Pending file must be a JSON file: {pending_file}")
    return pending_file


def xhs_target_from_input(data: dict[str, Any]) -> Path:
    target_raw = data.get("target") or data.get("pending_file")
    if not target_raw:
        raise ValueError("Input JSON must include target or pending_file")
    target = Path(str(target_raw)).expanduser().resolve()
    if not target.exists():
        raise ValueError(f"XHS target does not exist: {target}")
    return target


def xhs_pending_dir_from_input(data: dict[str, Any]) -> Path:
    pending_raw = data.get("pending_dir") or (XHS_PIPELINE_DIR / "pending")
    return Path(str(pending_raw)).expanduser().resolve()


def select_xhs_pending_without_images(pending_dir: Path) -> dict[str, Any]:
    if not pending_dir.exists():
        raise ValueError(f"Pending directory does not exist: {pending_dir}")
    for path in sorted(
        pending_dir.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True
    ):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        images = data.get("images") or []
        if images:
            continue
        return {
            "status": "selected",
            "pending_file": str(path),
            "title": data.get("title", ""),
            "summary": data.get("summary", ""),
            "tags": data.get("tags", []),
            "created_at": data.get("created_at", ""),
            "has_images": False,
            "image_count": 0,
        }
    return {"status": "empty", "pending_file": None, "pending_dir": str(pending_dir)}


def run_xhs_script(
    script_key: str, args: list[str], timeout_seconds: int
) -> subprocess.CompletedProcess[str]:
    script_path = XHS_SCRIPT_PATHS[script_key]
    if not script_path.exists():
        raise FileNotFoundError(str(script_path))
    return subprocess.run(
        [sys.executable, str(script_path), *args],
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )


def parse_json_or_text(raw: str) -> dict[str, Any]:
    text = redact_sensitive_text(raw.strip())
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {"raw_output": text}
    parsed_data = parsed if isinstance(parsed, dict) else {"value": parsed}
    return redact_sensitive_data(parsed_data)


def run_xhs_json_script(
    script_key: str,
    args: list[str],
    timeout_seconds: int,
) -> tuple[subprocess.CompletedProcess[str], dict[str, Any]]:
    completed = run_xhs_script(script_key, args, timeout_seconds)
    raw = completed.stdout.strip() or completed.stderr.strip()
    return completed, parse_json_or_text(raw)


def run_xhs_generate_cards_script(pending_file: Path, timeout_seconds: int) -> dict[str, Any]:
    completed = run_xhs_script("script_generate_cards", [str(pending_file)], timeout_seconds)
    if completed.returncode != 0:
        raise RuntimeError(
            completed.stderr.strip() or completed.stdout.strip() or "xhs.generate-cards failed"
        )
    pending_data = json.loads(pending_file.read_text(encoding="utf-8"))
    images = [str(Path(image).expanduser().resolve()) for image in pending_data.get("images", [])]
    return {
        "status": "generated",
        "success": True,
        "pending_file": str(pending_file),
        "title": pending_data.get("title", ""),
        "images": images,
        "image_count": len(images),
        "has_images": bool(images),
        "returncode": completed.returncode,
        "stdout": redact_sensitive_text(completed.stdout),
        "stderr": redact_sensitive_text(completed.stderr),
    }


def xhs_summary_headline(capability_id: str, payload: dict[str, Any]) -> str:
    if capability_id == "xhs.select-pending":
        if payload.get("pending_file"):
            return f"xhs.select-pending: selected {payload.get('title') or payload['pending_file']}"
        return "xhs.select-pending: no pending item without images"
    if payload.get("allow_preview") is False:
        return f"{capability_id}: blocked"
    if payload.get("success") is False:
        return f"{capability_id}: failed"
    return f"{capability_id}: completed"


def write_xhs_bundle(
    capability_id: str,
    input_path: Path,
    input_data: dict[str, Any],
    payload: dict[str, Any],
    preview_dir: Path | None,
    warnings: list[str] | None = None,
    next_actions: list[str] | None = None,
) -> HarnessResponse:
    spec = XHS_COMMANDS[capability_id]
    safe_payload = redact_sensitive_data(payload)
    safe_input_data = redact_sensitive_data(input_data)
    safe_warnings = redact_sensitive_data(warnings or [])
    safe_next_actions = redact_sensitive_data(next_actions or [])
    preview_root = (preview_dir or Path(".preview")).expanduser().resolve()
    safe_suffix = capability_id.removeprefix("xhs.").replace(".", "-")
    short_hash = fingerprint(
        {"capability": capability_id, "input": safe_input_data, "payload": safe_payload}
    )[:8]
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    bundle_dir = preview_root / "xhs-image-cards" / f"{timestamp}_{short_hash}_{safe_suffix}"
    artifacts_dir = bundle_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=False)

    artifact_path = artifacts_dir / spec.artifact
    artifact_path.write_text(
        json.dumps(safe_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    status = safe_payload.get("status") or (
        "ok" if safe_payload.get("ok", True) else "failed"
    )
    facts = {
        "capability": capability_id,
        "status": status,
    }
    for key in (
        "pending_file",
        "pending_dir",
        "title",
        "has_images",
        "image_count",
        "allow_preview",
        "qa_exit_code",
        "returncode",
        "success",
    ):
        if key in safe_payload:
            facts[key] = safe_payload[key]
    summary = {
        "headline": xhs_summary_headline(capability_id, safe_payload),
        "facts": facts,
        "warnings": safe_warnings,
        "next_actions": safe_next_actions,
    }
    manifest = {
        "protocol_version": "preview-bundle/v1",
        "tool": "xhs-image-cards",
        "capability": capability_id,
        "status": "ok",
        "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "source": {
            "input_path": str(input_path.expanduser().resolve()),
            "input_fingerprint": f"sha256:{fingerprint(safe_input_data)}",
        },
        "summary_path": "summary.json",
        "artifacts": [
            {
                "id": spec.artifact.removesuffix(".json"),
                "kind": "json",
                "role": "xhs_result",
                "path": str(artifact_path.relative_to(bundle_dir)),
                "label": spec.artifact,
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
        data={"bundle_dir": str(bundle_dir), **facts},
        artifacts=[Artifact(kind="preview_bundle", path=str(bundle_dir), role="output")],
        warnings=summary["warnings"],
        next_actions=summary["next_actions"],
    )


def run_xhs_command(
    capability_id: str,
    input_path: Path,
    preview_dir: Path | None = None,
) -> HarnessResponse:
    if capability_id not in XHS_COMMANDS:
        return HarnessResponse.failure(
            "unknown_capability",
            f"Unsupported capability: {capability_id}",
            "Run registry list --json",
        )
    data = load_json(input_path)
    if capability_id == "xhs.select-pending":
        try:
            payload = select_xhs_pending_without_images(xhs_pending_dir_from_input(data))
        except ValueError as exc:
            return HarnessResponse.failure("invalid_input", str(exc))
        return write_xhs_bundle(
            capability_id=capability_id,
            input_path=input_path,
            input_data=data,
            payload=payload,
            preview_dir=preview_dir,
            next_actions=[
                "Run xhs.generate-cards for the selected pending_file before previewing."
                if payload.get("pending_file")
                else "No pending item without images was found."
            ],
        )
    if capability_id == "xhs.generate-cards":
        try:
            pending_file = xhs_pending_file_from_input(data)
            payload = run_xhs_generate_cards_script(
                pending_file,
                timeout_seconds=int(data.get("timeout_seconds") or 600),
            )
        except ValueError as exc:
            return HarnessResponse.failure("invalid_input", str(exc))
        except FileNotFoundError as exc:
            return HarnessResponse.failure(
                "missing_dependency",
                f"XHS script not found: {exc}",
                "Check ~/.hermes/scripts/xhs-pipeline installation",
            )
        except subprocess.TimeoutExpired:
            return HarnessResponse.failure(
                "backend_timeout",
                "xhs.generate-cards timed out",
                "Increase timeout_seconds or run the generator directly",
            )
        except RuntimeError as exc:
            return HarnessResponse.failure(
                "backend_failed", str(exc), "Fix card generation and rerun"
            )
        return write_xhs_bundle(
            capability_id=capability_id,
            input_path=input_path,
            input_data=data,
            payload=payload,
            preview_dir=preview_dir,
            warnings=[
                "Pillow generator is a fallback; run QA and visual inspection before preview."
            ],
            next_actions=["Run xhs.image-qa then xhs.finalize-preview before publishing."],
        )
    if capability_id == "xhs.image-qa":
        try:
            target = xhs_target_from_input(data)
            completed, qa = run_xhs_json_script(
                "script_image_qa",
                [str(target)],
                timeout_seconds=int(data.get("timeout_seconds") or 120),
            )
        except ValueError as exc:
            return HarnessResponse.failure("invalid_input", str(exc))
        except FileNotFoundError as exc:
            return HarnessResponse.failure(
                "missing_dependency",
                f"XHS script not found: {exc}",
                "Check ~/.hermes/scripts/xhs-pipeline installation",
            )
        except subprocess.TimeoutExpired:
            return HarnessResponse.failure(
                "backend_timeout",
                "xhs.image-qa timed out",
                "Inspect the target path and rerun QA directly",
            )
        qa_ok = completed.returncode == 0 and qa.get("ok") is True
        warnings = [str(item) for item in qa.get("warnings", [])]
        payload = {
            "status": "passed" if qa_ok else "needs_attention",
            "success": qa_ok,
            "target": str(target),
            "qa_exit_code": completed.returncode,
            "qa": qa,
            "warnings": warnings,
        }
        return write_xhs_bundle(
            capability_id=capability_id,
            input_path=input_path,
            input_data=data,
            payload=payload,
            preview_dir=preview_dir,
            warnings=warnings,
            next_actions=[str(qa.get("next_action") or "Do visual inspection before preview.")],
        )
    if capability_id in {"xhs.preview-gate", "xhs.finalize-preview"}:
        try:
            pending_file = xhs_pending_file_from_input(data)
            script_key = (
                "script_preview_gate"
                if capability_id == "xhs.preview-gate"
                else "script_finalize_preview"
            )
            completed, result = run_xhs_json_script(
                script_key,
                [str(pending_file)],
                timeout_seconds=int(data.get("timeout_seconds") or 120),
            )
        except ValueError as exc:
            return HarnessResponse.failure("invalid_input", str(exc))
        except FileNotFoundError as exc:
            return HarnessResponse.failure(
                "missing_dependency",
                f"XHS script not found: {exc}",
                "Check ~/.hermes/scripts/xhs-pipeline installation",
            )
        except subprocess.TimeoutExpired:
            return HarnessResponse.failure(
                "backend_timeout",
                f"{capability_id} timed out",
                "Inspect the pending file and rerun the preview script directly",
            )
        allow_preview = completed.returncode == 0 and result.get("allow_preview") is True
        reasons = (
            result.get("reasons")
            or (result.get("gate") or {}).get("reasons")
            or result.get("warnings")
            or []
        )
        warnings = [] if allow_preview else [str(item) for item in reasons]
        payload = {
            "status": "ready" if allow_preview else "blocked",
            "success": allow_preview,
            "pending_file": str(pending_file),
            "allow_preview": allow_preview,
            "image_count": len(result.get("image_paths", [])),
            "returncode": completed.returncode,
            "preview": result,
        }
        return write_xhs_bundle(
            capability_id=capability_id,
            input_path=input_path,
            input_data=data,
            payload=payload,
            preview_dir=preview_dir,
            warnings=warnings,
            next_actions=[
                "Send preview_text and image_paths only after inspect confirms allow_preview=true."
                if allow_preview
                else "Fix QA warnings before sending Telegram preview."
            ],
        )
    if capability_id == "xhs.publish":
        try:
            script_args: list[str] = []
            if data.get("pending_file"):
                script_args.extend(["--file", str(xhs_pending_file_from_input(data))])
            elif data.get("title"):
                script_args.extend(["--title", str(data["title"])])
            else:
                raise ValueError("Input JSON must include pending_file or title")
            if data.get("headed"):
                script_args.append("--headed")
            if data.get("dry_run"):
                script_args.append("--dry-run")
            completed, parsed = run_xhs_json_script(
                "script_publish_xhs",
                script_args,
                timeout_seconds=int(data.get("timeout_seconds") or 900),
            )
        except ValueError as exc:
            return HarnessResponse.failure("invalid_input", str(exc))
        except FileNotFoundError as exc:
            return HarnessResponse.failure(
                "missing_dependency",
                f"XHS script not found: {exc}",
                "Check ~/.hermes/scripts/xhs-pipeline installation",
            )
        except subprocess.TimeoutExpired:
            return HarnessResponse.failure(
                "backend_timeout",
                "xhs.publish timed out",
                "Inspect social-auto-upload logs before retrying",
            )
        if completed.returncode != 0:
            return HarnessResponse.failure(
                "backend_failed",
                redact_sensitive_text(completed.stderr.strip() or completed.stdout.strip())
                or "xhs.publish failed",
                "Check cookie/login state and publish manually if needed",
            )
        payload = {
            "status": "published" if not data.get("dry_run") else "dry_run",
            "success": True,
            "returncode": completed.returncode,
            "publish": parsed,
            "stdout": redact_sensitive_text(completed.stdout),
            "stderr": redact_sensitive_text(completed.stderr),
        }
        return write_xhs_bundle(
            capability_id=capability_id,
            input_path=input_path,
            input_data=data,
            payload=payload,
            preview_dir=preview_dir,
            next_actions=["Verify the published note manually in Xiaohongshu."],
        )
    return HarnessResponse.failure(
        "unknown_capability",
        f"Unsupported capability: {capability_id}",
        "Run registry list --json",
    )


def site_path_from_input(data: dict[str, Any]) -> Path:
    site_raw = data.get("site") or "."
    site = Path(str(site_raw)).expanduser().resolve()
    if not site.exists():
        raise ValueError(f"Site path does not exist: {site}")
    if not (site / "package.json").exists():
        raise ValueError(f"Site path is missing package.json: {site}")
    return site


def collect_site_status(site: Path) -> dict[str, Any]:
    package_json = json.loads((site / "package.json").read_text(encoding="utf-8"))
    return {
        "site": str(site),
        "package_name": package_json.get("name"),
        "has_package_json": True,
        "has_node_modules": (site / "node_modules").exists(),
        "has_dist": (site / "dist").exists(),
        "build_script": (package_json.get("scripts") or {}).get("build"),
    }


def site_summary_headline(capability_id: str, payload: dict[str, Any]) -> str:
    if capability_id == "site.status":
        package_name = payload.get("package_name") or "site"
        state = "ready" if payload.get("has_package_json") else "not ready"
        return f"{capability_id}: {package_name} {state}"
    if capability_id == "site.build":
        state = "passed" if payload.get("returncode") == 0 else "failed"
        return f"{capability_id}: build {state}"
    if capability_id == "site.check-links":
        broken = payload.get("broken_link_count", 0)
        return f"{capability_id}: {broken} broken local link(s)"
    if capability_id == "site.deploy":
        return f"{capability_id}: pushed dist to gh-pages"
    return f"{capability_id}: completed"


def write_site_bundle(
    capability_id: str,
    input_path: Path,
    input_data: dict[str, Any],
    payload: dict[str, Any],
    preview_dir: Path | None,
) -> HarnessResponse:
    spec = SITE_COMMANDS[capability_id]
    safe_payload = redact_sensitive_data(payload)
    safe_input_data = redact_sensitive_data(input_data)
    preview_root = (preview_dir or Path(".preview")).expanduser().resolve()
    safe_suffix = capability_id.removeprefix("site.").replace(".", "-")
    hash_input = {"capability": capability_id, "input": safe_input_data, "payload": safe_payload}
    short_hash = fingerprint(hash_input)[:8]
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    bundle_dir = preview_root / "personal-site" / f"{timestamp}_{short_hash}_{safe_suffix}"
    artifacts_dir = bundle_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=False)

    artifact_path = artifacts_dir / spec.artifact
    artifact_path.write_text(
        json.dumps(safe_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    summary = {
        "headline": site_summary_headline(capability_id, safe_payload),
        "facts": safe_payload,
        "warnings": [],
        "next_actions": [],
    }
    manifest = {
        "protocol_version": "preview-bundle/v1",
        "tool": "personal-site",
        "capability": capability_id,
        "status": "ok",
        "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "source": {
            "input_path": str(input_path.expanduser().resolve()),
            "input_fingerprint": f"sha256:{fingerprint(safe_input_data)}",
        },
        "summary_path": "summary.json",
        "artifacts": [
            {
                "id": spec.artifact.removesuffix(".json"),
                "kind": "json",
                "role": "site_result",
                "path": str(artifact_path.relative_to(bundle_dir)),
                "label": spec.artifact,
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
        data={"bundle_dir": str(bundle_dir), "capability": capability_id, **safe_payload},
        artifacts=[Artifact(kind="preview_bundle", path=str(bundle_dir), role="output")],
    )


HREF_RE = re.compile(r"href=[\"']([^\"']+)[\"']")


def local_href_target(dist_dir: Path, source_file: Path, href: str) -> Path | None:
    if href.startswith("#") or href.startswith("mailto:") or href.startswith("tel:"):
        return None
    parsed = urlsplit(href)
    if parsed.scheme or parsed.netloc:
        return None
    raw_path = parsed.path
    if not raw_path:
        return None
    base_dir = dist_dir if raw_path.startswith("/") else source_file.parent
    relative = raw_path.lstrip("/") if raw_path.startswith("/") else raw_path
    target = (base_dir / relative).resolve()
    if raw_path.endswith("/") or not target.suffix:
        target = target / "index.html"
    return target


def collect_site_link_report(site: Path) -> dict[str, Any]:
    dist_dir = site / "dist"
    if not dist_dir.exists():
        raise ValueError(f"Site dist directory does not exist: {dist_dir}")
    checked_links: list[dict[str, str]] = []
    broken_links: list[dict[str, str]] = []
    html_paths = sorted(dist_dir.rglob("*.html"))
    for html_path in html_paths:
        source = html_path.relative_to(dist_dir).as_posix()
        html = html_path.read_text(encoding="utf-8")
        for href in HREF_RE.findall(html):
            target = local_href_target(dist_dir, html_path, href)
            if target is None:
                continue
            if not target.is_relative_to(dist_dir.resolve()):
                broken_links.append({"source": source, "href": href, "target": "<outside-dist>"})
                checked_links.append({"source": source, "href": href})
                continue
            target_rel = target.relative_to(dist_dir).as_posix()
            checked_links.append({"source": source, "href": href, "target": target_rel})
            if not target.exists():
                broken_links.append({"source": source, "href": href, "target": target_rel})
    return {
        "site": str(site),
        "dist": str(dist_dir),
        "html_file_count": len(html_paths),
        "checked_link_count": len(checked_links),
        "broken_link_count": len(broken_links),
        "checked_links": checked_links,
        "broken_links": broken_links,
    }


def mask_remote_url(remote: str) -> str:
    return re.sub(r"(https://[^:/@]+:)[^@]+(@)", r"\1***\2", remote)


def run_site_subprocess(
    command: list[str],
    cwd: Path,
    timeout_seconds: int,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )


def deploy_site_dist(site: Path, timeout_seconds: int) -> dict[str, Any]:
    dist_dir = site / "dist"
    if not dist_dir.exists():
        raise ValueError(f"Site dist directory does not exist: {dist_dir}")
    remote_result = run_site_subprocess(
        ["git", "remote", "get-url", "origin"],
        cwd=site,
        timeout_seconds=timeout_seconds,
    )
    if remote_result.returncode != 0:
        raise RuntimeError(remote_result.stderr.strip() or "Could not read origin remote")
    remote = remote_result.stdout.strip()
    commands = [
        ["git", "init"],
        ["git", "add", "."],
        ["git", "commit", "-m", "deploy: personal-site"],
        ["git", "push", "-f", remote, "HEAD:gh-pages"],
    ]
    command_reports: list[dict[str, Any]] = []
    git_dir = dist_dir / ".git"
    if git_dir.exists():
        shutil.rmtree(git_dir)
    try:
        for command in commands:
            completed = run_site_subprocess(command, cwd=dist_dir, timeout_seconds=timeout_seconds)
            command_reports.append(
                {
                    "command": [mask_remote_url(part) for part in command],
                    "returncode": completed.returncode,
                    "stdout": mask_remote_url(completed.stdout),
                    "stderr": mask_remote_url(completed.stderr),
                }
            )
            if completed.returncode != 0:
                message = (
                    completed.stderr.strip()
                    or completed.stdout.strip()
                    or f"Command failed: {command[0]}"
                )
                raise RuntimeError(message)
    finally:
        if git_dir.exists():
            shutil.rmtree(git_dir)
    return {
        "site": str(site),
        "dist": str(dist_dir),
        "remote": mask_remote_url(remote),
        "branch": "gh-pages",
        "commands": command_reports,
    }


def run_site_command(
    capability_id: str,
    input_path: Path,
    preview_dir: Path | None = None,
) -> HarnessResponse:
    if capability_id not in SITE_COMMANDS:
        return HarnessResponse.failure(
            "unknown_capability",
            f"Unsupported capability: {capability_id}",
            "Run registry list --json",
        )
    data = load_json(input_path)
    try:
        site = site_path_from_input(data)
    except ValueError as exc:
        return HarnessResponse.failure("invalid_input", str(exc))
    if capability_id == "site.status":
        return write_site_bundle(
            capability_id=capability_id,
            input_path=input_path,
            input_data=data,
            payload=collect_site_status(site),
            preview_dir=preview_dir,
        )
    if capability_id == "site.build":
        timeout_seconds = int(data.get("timeout_seconds") or 300)
        try:
            completed = subprocess.run(
                ["npm", "run", "build"],
                cwd=site,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return HarnessResponse.failure(
                "backend_timeout",
                f"site.build timed out after {timeout_seconds} seconds",
                "Increase timeout_seconds or run npm run build directly for details",
            )
        except OSError as exc:
            return HarnessResponse.failure(
                "backend_launch_failed",
                str(exc),
                "Install npm dependencies or fix PATH before rerunning",
            )
        if completed.returncode != 0:
            return HarnessResponse.failure(
                "backend_failed",
                completed.stderr.strip() or completed.stdout.strip() or "site.build failed",
                "Run npm run build in the site repository for details",
            )
        payload = {
            "site": str(site),
            "command": "npm run build",
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "dist_exists": (site / "dist").exists(),
        }
        return write_site_bundle(
            capability_id=capability_id,
            input_path=input_path,
            input_data=data,
            payload=payload,
            preview_dir=preview_dir,
        )
    if capability_id == "site.check-links":
        try:
            payload = collect_site_link_report(site)
        except ValueError as exc:
            return HarnessResponse.failure("invalid_input", str(exc))
        return write_site_bundle(
            capability_id=capability_id,
            input_path=input_path,
            input_data=data,
            payload=payload,
            preview_dir=preview_dir,
        )
    if capability_id == "site.deploy":
        timeout_seconds = int(data.get("timeout_seconds") or 300)
        try:
            payload = deploy_site_dist(site, timeout_seconds=timeout_seconds)
        except ValueError as exc:
            return HarnessResponse.failure("invalid_input", str(exc))
        except RuntimeError as exc:
            return HarnessResponse.failure(
                "backend_failed",
                mask_remote_url(str(exc)),
                "Run the deploy commands manually in the site repository for details",
            )
        except subprocess.TimeoutExpired:
            return HarnessResponse.failure(
                "backend_timeout",
                f"site.deploy timed out after {timeout_seconds} seconds",
                "Increase timeout_seconds or deploy the site manually",
            )
        except OSError as exc:
            return HarnessResponse.failure(
                "backend_launch_failed",
                str(exc),
                "Install git or fix PATH before rerunning",
            )
        return write_site_bundle(
            capability_id=capability_id,
            input_path=input_path,
            input_data=data,
            payload=payload,
            preview_dir=preview_dir,
        )
    return HarnessResponse.failure(
        "unknown_capability",
        f"Unsupported capability: {capability_id}",
        "Run registry list --json",
    )


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
    args = list(spec.args)
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


def parse_distill_json_output(stdout: str) -> Any:
    try:
        return json.loads(stdout)
    except json.JSONDecodeError as original_exc:
        decoder = json.JSONDecoder()
        for idx, char in enumerate(stdout):
            if char not in "[{":
                continue
            try:
                payload, _end = decoder.raw_decode(stdout[idx:])
                return payload
            except json.JSONDecodeError:
                continue
        raise original_exc


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

    timeout_seconds = int(data.get("timeout_seconds") or 300)
    try:
        completed = subprocess.run(
            ["distill", "-v", str(vault), *distill_args],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return HarnessResponse.failure(
            "backend_timeout",
            f"{capability_id} timed out after {timeout_seconds} seconds",
            "Increase timeout_seconds or run the distill command directly for details",
        )
    except OSError as exc:
        return HarnessResponse.failure(
            "backend_launch_failed",
            str(exc),
            "Install distill or fix PATH before rerunning",
        )
    if completed.returncode != 0:
        return HarnessResponse.failure(
            "backend_failed",
            redact_sensitive_text(
                completed.stderr.strip() or completed.stdout.strip() or f"{capability_id} failed"
            ),
            "Run the distill command directly for details",
        )

    output_kind = spec.output
    if output_kind in {"json", "json_or_stdout"}:
        try:
            payload: Any = parse_distill_json_output(completed.stdout)
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

    safe_payload = redact_sensitive_data(payload)
    safe_input_data = redact_sensitive_data(data)

    preview_root = (preview_dir or Path(".preview")).expanduser().resolve()
    safe_suffix = capability_id.removeprefix("distill.").replace(".", "-")
    short_hash = fingerprint(
        {"capability": capability_id, "input": safe_input_data, "payload": safe_payload}
    )[:8]
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    bundle_dir = preview_root / "distill-vault" / f"{timestamp}_{short_hash}_{safe_suffix}"
    artifacts_dir = bundle_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=False)

    artifact_name = spec.artifact
    artifact_path = artifacts_dir / artifact_name
    if output_kind == "json":
        artifact_path.write_text(
            json.dumps(safe_payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    else:
        artifact_path.write_text(str(safe_payload), encoding="utf-8")

    facts: dict[str, Any] = {"vault": str(vault), "capability": capability_id}
    if isinstance(safe_payload, dict):
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
            if key in safe_payload:
                facts[key] = safe_payload[key]
    elif isinstance(safe_payload, list):
        facts["item_count"] = len(safe_payload)
    elif isinstance(safe_payload, str):
        facts["line_count"] = len(safe_payload.splitlines())

    summary = {
        "headline": distill_summary_headline(capability_id, safe_payload),
        "facts": facts,
        "warnings": [],
        "next_actions": distill_next_actions(safe_payload),
    }
    manifest = {
        "protocol_version": "preview-bundle/v1",
        "tool": "distill-vault",
        "capability": capability_id,
        "status": "ok",
        "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "source": {
            "input_path": str(input_path.expanduser().resolve()),
            "input_fingerprint": f"sha256:{fingerprint(safe_input_data)}",
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
    bundle_root = bundle_dir.expanduser().resolve()
    for artifact in artifacts:
        if not isinstance(artifact, dict) or not artifact.get("path"):
            return HarnessResponse.failure(
                "invalid_bundle",
                "manifest.json artifact entries must include path",
                "Regenerate the preview bundle",
            )
        artifact_relpath = str(artifact["path"])
        artifact_path = (bundle_root / artifact_relpath).resolve()
        if not artifact_path.is_relative_to(bundle_root):
            return HarnessResponse.failure(
                "invalid_bundle",
                f"Preview bundle artifact path escapes bundle: {artifact_relpath}",
                "Regenerate the preview bundle",
            )
        if not artifact_path.exists():
            return HarnessResponse.failure(
                "invalid_bundle",
                f"Preview bundle artifact path does not exist: {artifact_relpath}",
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
            redact_sensitive_text(
                completed.stderr.strip() or completed.stdout.strip() or "Backend command failed"
            ),
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
    allow_external_write: bool = False,
) -> HarnessResponse:
    try:
        _, capability = tool_for_capability(capability_id)
    except KeyError:
        return HarnessResponse.failure(
            "unknown_capability",
            f"Unsupported capability: {capability_id}",
            "Run registry list --json",
        )
    if capability.side_effect == "external_write" and not allow_external_write:
        return HarnessResponse.failure(
            "unsafe_side_effect",
            f"Capability {capability_id} has side effect external_write",
            "Re-run with --allow-external-write only after explicit user approval",
        )
    if capability_id in XHS_COMMANDS:
        return run_xhs_command(capability_id, input_path=input_path, preview_dir=preview_dir)
    if capability_id in DISTILL_COMMANDS:
        return run_distill_command(capability_id, input_path=input_path, preview_dir=preview_dir)
    if capability_id in SITE_COMMANDS:
        return run_site_command(capability_id, input_path=input_path, preview_dir=preview_dir)
    return HarnessResponse.failure(
        "unknown_capability",
        f"Unsupported capability: {capability_id}",
        "Run registry list --json",
    )
