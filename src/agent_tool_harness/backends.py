from __future__ import annotations

import hashlib
import json
import re
import shlex
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .capabilities import DISTILL_CAPABILITY_SPECS, SITE_CAPABILITY_SPECS
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


def doctor_tool_status(tool) -> dict[str, Any]:
    checks: list[dict[str, Any]] = [
        {"name": "registry_entry", "ok": True},
        {"name": "json_contract", "ok": True},
        {"name": "preview_protocol", "ok": True},
    ]
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


DISTILL_COMMANDS = DISTILL_CAPABILITY_SPECS
SITE_COMMANDS = SITE_CAPABILITY_SPECS


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
    preview_root = (preview_dir or Path(".preview")).expanduser().resolve()
    safe_suffix = capability_id.removeprefix("site.").replace(".", "-")
    hash_input = {"capability": capability_id, "input": input_data, "payload": payload}
    short_hash = fingerprint(hash_input)[:8]
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    bundle_dir = preview_root / "personal-site" / f"{timestamp}_{short_hash}_{safe_suffix}"
    artifacts_dir = bundle_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=False)

    artifact_path = artifacts_dir / spec.artifact
    artifact_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = {
        "headline": site_summary_headline(capability_id, payload),
        "facts": payload,
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
            "input_fingerprint": f"sha256:{fingerprint(input_data)}",
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
        data={"bundle_dir": str(bundle_dir), "capability": capability_id, **payload},
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
            completed.stderr.strip() or completed.stdout.strip() or f"{capability_id} failed",
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

    preview_root = (preview_dir or Path(".preview")).expanduser().resolve()
    safe_suffix = capability_id.removeprefix("distill.").replace(".", "-")
    short_hash = fingerprint({"capability": capability_id, "input": data, "payload": payload})[:8]
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    bundle_dir = preview_root / "distill-vault" / f"{timestamp}_{short_hash}_{safe_suffix}"
    artifacts_dir = bundle_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=False)

    artifact_name = spec.artifact
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
    if capability_id == "xhs.generate-cards":
        return run_xhs_generate_cards(input_path=input_path, preview_dir=preview_dir)
    if capability_id in DISTILL_COMMANDS:
        return run_distill_command(capability_id, input_path=input_path, preview_dir=preview_dir)
    if capability_id in SITE_COMMANDS:
        return run_site_command(capability_id, input_path=input_path, preview_dir=preview_dir)
    return HarnessResponse.failure(
        "unknown_capability",
        f"Unsupported capability: {capability_id}",
        "Run registry list --json",
    )
