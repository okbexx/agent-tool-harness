from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from agent_tool_harness import backends
from agent_tool_harness.capabilities import DISTILL_CAPABILITY_SPECS
from agent_tool_harness.cli import app


def write_minimal_distill_vault(path: Path) -> None:
    (path / "知识" / "项目").mkdir(parents=True)
    (path / "输出").mkdir()
    (path / "运维").mkdir()
    (path / "系统").mkdir()
    (path / "distill.yaml").write_text(
        "knowledge_dirs: ['知识']\n"
        "output_dirs: ['输出']\n"
        "ops_dirs: ['运维']\n"
        "system_dirs: ['系统']\n",
        encoding="utf-8",
    )
    (path / "知识" / "项目" / "示例项目.md").write_text(
        "---\ntype: project\nstatus: active\n---\n# 示例项目\n",
        encoding="utf-8",
    )


runner = CliRunner()


def parse_json(result):
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


def test_registry_list_exposes_capability_metadata():
    result = runner.invoke(app, ["registry", "list", "--json"])

    payload = parse_json(result)

    assert payload["ok"] is True
    tools = payload["data"]["tools"]
    assert tools[0]["name"] == "xhs-image-cards"
    assert tools[0]["capabilities"][0]["id"] == "xhs.generate-cards"
    assert tools[0]["capabilities"][0]["side_effect"] == "local_files"
    assert tools[0]["capabilities"][0]["backend"]["kind"] == "python_function"
    assert tools[0]["capabilities"][0]["backend"]["target"] == "run_xhs_generate_cards"
    assert tools[0]["healthcheck"] == "agent-tool-harness doctor xhs-image-cards --json"
    distill_tool = tools[1]
    assert distill_tool["name"] == "distill-vault"
    distill_capabilities = {
        capability["id"]: capability for capability in distill_tool["capabilities"]
    }
    assert set(distill_capabilities) >= {
        "distill.status",
        "distill.health",
        "distill.capabilities",
        "distill.instance-doctor",
        "distill.upgrade-plan",
        "distill.lint-check",
        "distill.lint-fix",
        "distill.route",
        "distill.plan",
        "distill.search",
        "distill.promote-dry-run",
        "distill.promote-auto",
        "distill.pipeline-run",
        "distill.capture",
        "distill.apply",
    }
    assert distill_capabilities["distill.health"]["side_effect"] == "local_files"
    assert distill_capabilities["distill.lint-fix"]["side_effect"] == "external_write"
    assert distill_capabilities["distill.health"]["backend"]["target"] == "run_distill_command"


def test_doctor_all_reports_no_side_effect_checks():
    result = runner.invoke(app, ["doctor", "--all", "--json"])

    payload = parse_json(result)

    assert payload["ok"] is True
    status = payload["data"]["statuses"][0]
    assert status["name"] == "xhs-image-cards"
    assert status["ok"] is True
    assert status["side_effect"] == "none"
    assert {check["name"] for check in status["checks"]} >= {
        "registry_entry",
        "json_contract",
        "preview_protocol",
    }


def test_doctor_distill_vault_runs_deep_backend_checks():
    result = runner.invoke(app, ["doctor", "distill-vault", "--json"])

    payload = parse_json(result)
    status = payload["data"]["statuses"][0]
    assert status["name"] == "distill-vault"
    assert status["ok"] is True
    checks = {check["name"]: check for check in status["checks"]}
    assert checks["binary_available"]["ok"] is True
    assert checks["help_available"]["ok"] is True
    assert checks["external_write_gated"]["ok"] is True
    assert checks["registry_backend_consistency"]["ok"] is True
    assert checks["preview_protocol"]["ok"] is True


def test_doctor_distill_vault_reports_missing_binary(monkeypatch):
    monkeypatch.setattr(backends.shutil, "which", lambda _name: None)

    result = runner.invoke(app, ["doctor", "distill-vault", "--json"])

    payload = parse_json(result)
    status = payload["data"]["statuses"][0]
    assert status["ok"] is False
    checks = {check["name"]: check for check in status["checks"]}
    assert checks["binary_available"] == {
        "name": "binary_available",
        "ok": False,
        "detail": "distill not found on PATH",
    }
    assert checks["help_available"] == {
        "name": "help_available",
        "ok": False,
        "detail": "distill missing",
    }


def test_run_generate_cards_creates_preview_bundle(tmp_path):
    input_path = Path("examples/github-trending.json")
    preview_dir = tmp_path / "preview"

    result = runner.invoke(
        app,
        [
            "run",
            "xhs.generate-cards",
            str(input_path),
            "--preview-dir",
            str(preview_dir),
            "--json",
        ],
    )

    payload = parse_json(result)
    assert payload["ok"] is True
    assert payload["data"]["card_count"] == 3
    bundle_dir = Path(payload["artifacts"][0]["path"])
    assert bundle_dir.exists()
    manifest = json.loads((bundle_dir / "manifest.json").read_text(encoding="utf-8"))
    summary = json.loads((bundle_dir / "summary.json").read_text(encoding="utf-8"))
    assert manifest["protocol_version"] == "preview-bundle/v1"
    assert manifest["capability"] == "xhs.generate-cards"
    assert manifest["tool"] == "xhs-image-cards"
    assert [artifact["id"] for artifact in manifest["artifacts"]] == [
        "card-01",
        "card-02",
        "card-03",
    ]
    assert summary["headline"] == "Generated 3 preview cards"


def test_distill_health_creates_preview_bundle_for_vault(tmp_path):
    vault = tmp_path / "vault"
    write_minimal_distill_vault(vault)
    input_path = tmp_path / "distill-health-input.json"
    input_path.write_text(json.dumps({"vault": str(vault)}), encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "run",
            "distill.health",
            str(input_path),
            "--preview-dir",
            str(tmp_path / "preview"),
            "--json",
        ],
    )

    payload = parse_json(result)
    assert payload["ok"] is True
    assert payload["data"]["runtime_stage"]
    assert payload["data"]["total_objects"] >= 1
    bundle_dir = Path(payload["artifacts"][0]["path"])
    assert bundle_dir.exists()
    manifest = json.loads((bundle_dir / "manifest.json").read_text(encoding="utf-8"))
    summary = json.loads((bundle_dir / "summary.json").read_text(encoding="utf-8"))
    health = json.loads((bundle_dir / "artifacts" / "health.json").read_text(encoding="utf-8"))
    assert manifest["protocol_version"] == "preview-bundle/v1"
    assert manifest["tool"] == "distill-vault"
    assert manifest["capability"] == "distill.health"
    assert summary["headline"].startswith("distill.health:")
    assert health["runtime_stage"] == payload["data"]["runtime_stage"]
    inspect_payload = json.loads(
        runner.invoke(app, ["inspect", str(bundle_dir), "--json"]).output
    )
    assert inspect_payload["data"]["capability"] == "distill.health"
    assert inspect_payload["data"]["artifact_count"] == 1


def test_distill_command_capabilities_create_preview_bundles(tmp_path):
    vault = tmp_path / "vault"
    write_minimal_distill_vault(vault)
    cases = [
        ("distill.status", {"vault": str(vault)}, "status.json"),
        ("distill.capabilities", {"vault": str(vault)}, "capabilities.json"),
        ("distill.instance-doctor", {"vault": str(vault)}, "instance-doctor.json"),
        ("distill.upgrade-plan", {"vault": str(vault)}, "upgrade-plan.json"),
        ("distill.lint-check", {"vault": str(vault)}, "lint-check.json"),
        (
            "distill.route",
            {"vault": str(vault), "intent": "记录 agent-tool-harness 接入 distill"},
            "route.json",
        ),
        (
            "distill.plan",
            {"vault": str(vault), "intent": "记录 agent-tool-harness 接入 distill"},
            "plan.json",
        ),
        (
            "distill.search",
            {"vault": str(vault), "query": "示例项目", "limit": 3},
            "search.txt",
        ),
        ("distill.promote-dry-run", {"vault": str(vault)}, "promote-dry-run.txt"),
    ]

    for capability_id, input_data, artifact_file in cases:
        input_path = tmp_path / f"{capability_id}.json"
        input_path.write_text(json.dumps(input_data), encoding="utf-8")
        result = runner.invoke(
            app,
            [
                "run",
                capability_id,
                str(input_path),
                "--preview-dir",
                str(tmp_path / "preview"),
                "--json",
            ],
        )

        payload = parse_json(result)
        assert payload["ok"] is True, capability_id
        assert payload["data"]["capability"] == capability_id
        bundle_dir = Path(payload["artifacts"][0]["path"])
        assert (bundle_dir / "manifest.json").exists(), capability_id
        assert (bundle_dir / "summary.json").exists(), capability_id
        assert (bundle_dir / "artifacts" / artifact_file).exists(), capability_id
        inspect_payload = json.loads(
            runner.invoke(app, ["inspect", str(bundle_dir), "--json"]).output
        )
        assert inspect_payload["data"]["capability"] == capability_id
        assert inspect_payload["data"]["artifact_count"] == 1


def test_inspect_preview_bundle_returns_manifest_and_summary(tmp_path):
    input_path = Path("examples/github-trending.json")
    preview_dir = tmp_path / "preview"
    run_result = runner.invoke(
        app,
        [
            "run",
            "xhs.generate-cards",
            str(input_path),
            "--preview-dir",
            str(preview_dir),
            "--json",
        ],
    )
    run_payload = parse_json(run_result)
    bundle_dir = run_payload["artifacts"][0]["path"]

    inspect_result = runner.invoke(app, ["inspect", bundle_dir, "--json"])

    payload = parse_json(inspect_result)
    assert payload["ok"] is True
    assert payload["data"]["protocol_version"] == "preview-bundle/v1"
    assert payload["data"]["capability"] == "xhs.generate-cards"
    assert payload["data"]["headline"] == "Generated 3 preview cards"
    assert payload["data"]["artifact_count"] == 3
    assert payload["next_actions"] == [
        (
            "Wire this capability to baoyu-image-cards or gpt-image-2 when production "
            "image generation is needed."
        ),
        "Keep preview-bundle/v1 manifest + summary contract stable.",
    ]


def test_inspect_preview_bundle_rejects_missing_artifact_file(tmp_path):
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    (bundle_dir / "manifest.json").write_text(
        json.dumps(
            {
                "protocol_version": "preview-bundle/v1",
                "tool": "fake-tool",
                "capability": "fake.generate",
                "status": "ok",
                "summary_path": "summary.json",
                "artifacts": [
                    {"id": "missing", "kind": "text", "path": "artifacts/missing.txt"}
                ],
            }
        ),
        encoding="utf-8",
    )
    (bundle_dir / "summary.json").write_text(
        json.dumps({"headline": "Fake", "facts": {}, "warnings": [], "next_actions": []}),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["inspect", str(bundle_dir), "--json"])

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["error"] == {
        "type": "invalid_bundle",
        "message": "Preview bundle artifact path does not exist: artifacts/missing.txt",
        "fix": "Regenerate the preview bundle",
    }


def test_subprocess_backend_runs_declared_command_and_returns_bundle(tmp_path):
    script_path = tmp_path / "fake_backend.py"
    script_path.write_text(
        """
import json
import sys
from pathlib import Path

input_path = Path(sys.argv[1])
preview_root = Path(sys.argv[2])
data = json.loads(input_path.read_text())
bundle = preview_root / "fake-tool" / "bundle-001"
artifacts = bundle / "artifacts"
artifacts.mkdir(parents=True)
(artifacts / "result.md").write_text("# " + data["title"] + "\\n")
(bundle / "manifest.json").write_text(json.dumps({
    "protocol_version": "preview-bundle/v1",
    "tool": "fake-tool",
    "capability": "fake.generate",
    "status": "ok",
    "source": {"input_path": str(input_path)},
    "summary_path": "summary.json",
    "artifacts": [{"id": "result", "kind": "markdown-preview", "path": "artifacts/result.md"}],
}))
(bundle / "summary.json").write_text(json.dumps({
    "headline": "Fake backend generated preview",
    "facts": {"title": data["title"]},
    "warnings": [],
    "next_actions": ["Inspect generated fake bundle"],
}))
print(json.dumps({"bundle_dir": str(bundle)}))
""".strip(),
        encoding="utf-8",
    )
    input_path = tmp_path / "input.json"
    input_path.write_text(json.dumps({"title": "Hello subprocess"}), encoding="utf-8")
    backend = {
        "kind": "subprocess",
        "target": f"python3 {script_path} {{input}} {{preview_dir}}",
        "timeout_seconds": 10,
    }

    result = runner.invoke(
        app,
        [
            "run-backend",
            "fake.generate",
            str(input_path),
            "--preview-dir",
            str(tmp_path / "preview"),
            "--backend-json",
            json.dumps(backend),
            "--json",
        ],
    )

    payload = parse_json(result)
    assert payload["ok"] is True
    bundle_dir = Path(payload["artifacts"][0]["path"])
    assert payload["data"] == {"bundle_dir": str(bundle_dir), "backend_kind": "subprocess"}
    assert (bundle_dir / "manifest.json").exists()
    assert (bundle_dir / "summary.json").exists()
    inspect_payload = json.loads(
        runner.invoke(app, ["inspect", str(bundle_dir), "--json"]).output
    )
    assert inspect_payload["data"]["capability"] == "fake.generate"
    assert inspect_payload["data"]["artifact_count"] == 1


def test_subprocess_backend_requires_preview_bundle_artifact(tmp_path):
    script_path = tmp_path / "bad_backend.py"
    script_path.write_text('print("{}")', encoding="utf-8")
    input_path = tmp_path / "input.json"
    input_path.write_text("{}", encoding="utf-8")
    backend = {
        "kind": "subprocess",
        "target": f"python3 {script_path} {{input}} {{preview_dir}}",
        "timeout_seconds": 10,
    }

    result = runner.invoke(
        app,
        [
            "run-backend",
            "fake.generate",
            str(input_path),
            "--preview-dir",
            str(tmp_path / "preview"),
            "--backend-json",
            json.dumps(backend),
            "--json",
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["error"]["type"] == "invalid_backend_output"
    assert payload["error"]["fix"] == "Backend must print JSON with bundle_dir"


def test_registry_and_backend_distill_capabilities_share_same_specs():
    result = runner.invoke(app, ["registry", "list", "--json"])

    payload = parse_json(result)
    distill_tool = next(
        tool for tool in payload["data"]["tools"] if tool["name"] == "distill-vault"
    )
    registry_by_id = {
        capability["id"]: capability for capability in distill_tool["capabilities"]
    }

    assert set(registry_by_id) == set(DISTILL_CAPABILITY_SPECS)
    for capability_id, spec in DISTILL_CAPABILITY_SPECS.items():
        assert registry_by_id[capability_id]["side_effect"] == spec.side_effect
        assert registry_by_id[capability_id]["backend"]["target"] == "run_distill_command"


def test_external_write_capability_is_blocked_without_allow_flag(tmp_path):
    vault = tmp_path / "vault"
    write_minimal_distill_vault(vault)
    input_path = tmp_path / "distill-lint-fix-input.json"
    input_path.write_text(json.dumps({"vault": str(vault)}), encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "run",
            "distill.lint-fix",
            str(input_path),
            "--preview-dir",
            str(tmp_path / "preview"),
            "--json",
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["error"] == {
        "type": "unsafe_side_effect",
        "message": "Capability distill.lint-fix has side effect external_write",
        "fix": "Re-run with --allow-external-write only after explicit user approval",
    }
    assert not (tmp_path / "preview").exists()


def test_external_write_capability_runs_with_allow_flag(tmp_path):
    vault = tmp_path / "vault"
    write_minimal_distill_vault(vault)
    input_path = tmp_path / "distill-capture-input.json"
    input_path.write_text(
        json.dumps(
            {
                "vault": str(vault),
                "intent": "记录测试进展",
                "project": "示例项目",
            }
        ),
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        [
            "run",
            "distill.capture",
            str(input_path),
            "--preview-dir",
            str(tmp_path / "preview"),
            "--allow-external-write",
            "--json",
        ],
    )

    payload = parse_json(result)
    assert payload["ok"] is True
    assert payload["data"]["capability"] == "distill.capture"
    bundle_dir = Path(payload["artifacts"][0]["path"])
    assert (bundle_dir / "manifest.json").exists()
    assert (bundle_dir / "artifacts" / "capture.json").exists()


def test_lint_fix_with_prefixed_json_runs_with_allow_flag(tmp_path):
    vault = tmp_path / "vault"
    write_minimal_distill_vault(vault)
    input_path = tmp_path / "distill-lint-fix-input.json"
    input_path.write_text(json.dumps({"vault": str(vault)}), encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "run",
            "distill.lint-fix",
            str(input_path),
            "--preview-dir",
            str(tmp_path / "preview"),
            "--allow-external-write",
            "--json",
        ],
    )

    payload = parse_json(result)
    assert payload["ok"] is True
    assert payload["data"]["capability"] == "distill.lint-fix"
    bundle_dir = Path(payload["artifacts"][0]["path"])
    lint_fix = json.loads((bundle_dir / "artifacts" / "lint-fix.json").read_text(encoding="utf-8"))
    assert lint_fix["total_objects"] >= 1


def test_run_distill_missing_binary_returns_structured_error(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    write_minimal_distill_vault(vault)
    input_path = tmp_path / "distill-health-input.json"
    input_path.write_text(json.dumps({"vault": str(vault)}), encoding="utf-8")

    def raise_missing_binary(*_args, **_kwargs):
        raise FileNotFoundError("distill")

    monkeypatch.setattr(backends.subprocess, "run", raise_missing_binary)

    result = runner.invoke(app, ["run", "distill.health", str(input_path), "--json"])

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["error"] == {
        "type": "backend_launch_failed",
        "message": "distill",
        "fix": "Install distill or fix PATH before rerunning",
    }


def test_run_distill_timeout_returns_structured_error(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    write_minimal_distill_vault(vault)
    input_path = tmp_path / "distill-health-input.json"
    input_path.write_text(json.dumps({"vault": str(vault), "timeout_seconds": 7}), encoding="utf-8")

    def raise_timeout(*_args, **_kwargs):
        raise backends.subprocess.TimeoutExpired(cmd=["distill"], timeout=7)

    monkeypatch.setattr(backends.subprocess, "run", raise_timeout)

    result = runner.invoke(app, ["run", "distill.health", str(input_path), "--json"])

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["error"] == {
        "type": "backend_timeout",
        "message": "distill.health timed out after 7 seconds",
        "fix": "Increase timeout_seconds or run the distill command directly for details",
    }


def test_run_unknown_capability_returns_structured_error():
    result = runner.invoke(
        app,
        [
            "run",
            "missing.capability",
            "examples/github-trending.json",
            "--json",
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["error"] == {
        "type": "unknown_capability",
        "message": "Unsupported capability: missing.capability",
        "fix": "Run registry list --json",
    }


def test_skill_export_is_generated_from_metadata():
    result = runner.invoke(app, ["skill", "export", "xhs.generate-cards", "--json"])

    payload = parse_json(result)

    skill = payload["data"]["skill_md"]
    assert "name: xhs-image-cards" in skill
    assert "capability: xhs.generate-cards" in skill
    assert "## JSON output" in skill
    assert "## Artifacts" in skill
    assert "## Verification" in skill


def test_tool_skill_export_guides_distill_harness_usage():
    result = runner.invoke(app, ["skill", "export", "distill-vault", "--json"])

    payload = parse_json(result)
    skill = payload["data"]["skill_md"]
    assert "name: distill-vault-harness" in skill
    assert "ath doctor distill-vault --json" in skill
    assert "ath run distill.route" in skill
    assert "ath inspect" in skill
    assert "--allow-external-write" in skill
    assert "Do not run external_write capabilities without explicit user approval" in skill


def test_tool_skill_export_guides_personal_site_harness_usage():
    result = runner.invoke(app, ["skill", "export", "personal-site", "--json"])

    payload = parse_json(result)
    skill = payload["data"]["skill_md"]
    assert "name: personal-site-harness" in skill
    assert "ath doctor personal-site --json" in skill
    assert "ath run site.status" in skill
    assert "ath run site.check-links" in skill
    assert "ath run site.build" in skill
    assert "--allow-external-write" in skill
    assert "distill.route" not in skill


def test_capability_skill_export_guides_site_input_shape():
    result = runner.invoke(app, ["skill", "export", "site.status", "--json"])

    payload = parse_json(result)
    skill = payload["data"]["skill_md"]
    assert "capability: site.status" in skill
    assert "minimum useful shape contains `site`" in skill
    assert "trend_summary" not in skill
