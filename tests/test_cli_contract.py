from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from agent_tool_harness import backends
from agent_tool_harness.capabilities import DISTILL_CAPABILITY_SPECS, XHS_CAPABILITY_SPECS
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


def write_xhs_pending(path: Path, with_images: bool = False) -> list[str]:
    image_paths: list[str] = []
    if with_images:
        image_dir = path.parent / "cards"
        image_dir.mkdir()
        for name in [
            "01-cover.png",
            "02-content-top3.png",
            "03-content-mid.png",
            "04-ending-cta.png",
        ]:
            image_path = image_dir / name
            image_path.write_bytes(b"fake png")
            image_paths.append(str(image_path))
    path.write_text(
        json.dumps(
            {
                "title": "05月18日GitHub热榜🔥",
                "body": (
                    "📅 05月18日 GitHub Trending 日榜\n\n"
                    "🥇 openhuman\nAI project\nRust · 今日 +3,941⭐"
                ),
                "summary": "GitHub日榜: openhuman 等项目",
                "tags": ["GitHub", "开源项目"],
                "images": image_paths,
                "has_images": bool(image_paths),
                "trend_summary": {"date": "05月18日", "trend_keywords": "AI Agent"},
                "repos": [
                    {
                        "repo": "tinyhumansai/openhuman",
                        "desc": "Your Personal AI super intelligence.",
                        "lang": "Rust",
                        "today_stars": "3,941",
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return image_paths


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
    assert tools[0]["capabilities"][0]["backend"]["target"] == "run_xhs_command"
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


def test_doctor_xhs_image_cards_runs_script_and_gate_checks():
    result = runner.invoke(app, ["doctor", "xhs-image-cards", "--json"])

    payload = parse_json(result)
    status = payload["data"]["statuses"][0]
    assert status["name"] == "xhs-image-cards"
    assert status["ok"] is True
    checks = {check["name"]: check for check in status["checks"]}
    assert checks["script_generate_cards"]["ok"] is True
    assert checks["script_image_qa"]["ok"] is True
    assert checks["script_finalize_preview"]["ok"] is True
    assert checks["script_publish_xhs"]["ok"] is True
    assert checks["registry_backend_consistency"]["ok"] is True
    assert checks["external_write_gated"]["ok"] is True


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


def test_run_generate_cards_creates_preview_bundle(tmp_path, monkeypatch):
    pending = tmp_path / "pending.json"
    write_xhs_pending(pending, with_images=False)
    fake_script = tmp_path / "generate_xhs_cards.py"
    fake_script.write_text(
        """
import json
import sys
from pathlib import Path
pending = Path(sys.argv[1])
data = json.loads(pending.read_text(encoding='utf-8'))
out = pending.parent / 'generated-cards'
out.mkdir(exist_ok=True)
images = []
for name in ['01-cover.png', '02-content-top3.png', '03-content-mid.png', '04-ending-cta.png']:
    path = out / name
    path.write_bytes(b'fake png')
    images.append(str(path))
data['images'] = images
data['has_images'] = True
pending.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
print('---CARD_IMAGES---')
for image in images:
    print(image)
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setitem(backends.XHS_SCRIPT_PATHS, "script_generate_cards", fake_script)
    input_path = tmp_path / "xhs-generate-input.json"
    input_path.write_text(json.dumps({"pending_file": str(pending)}), encoding="utf-8")
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
    assert payload["data"]["image_count"] == 4
    assert payload["data"]["pending_file"] == str(pending.resolve())
    bundle_dir = Path(payload["artifacts"][0]["path"])
    manifest = json.loads((bundle_dir / "manifest.json").read_text(encoding="utf-8"))
    summary = json.loads((bundle_dir / "summary.json").read_text(encoding="utf-8"))
    artifact = json.loads(
        (bundle_dir / "artifacts" / "generate-cards.json").read_text(encoding="utf-8")
    )
    assert manifest["protocol_version"] == "preview-bundle/v1"
    assert manifest["capability"] == "xhs.generate-cards"
    assert summary["facts"]["image_count"] == 4
    assert artifact["images"] == json.loads(pending.read_text(encoding="utf-8"))["images"]


def test_xhs_image_qa_bundles_rule_result_even_when_blocked(tmp_path, monkeypatch):
    pending = tmp_path / "pending.json"
    write_xhs_pending(pending, with_images=True)
    fake_script = tmp_path / "xhs_image_qa.py"
    fake_script.write_text(
        """
import json
import sys
print(json.dumps({
    'ok': False,
    'artifact_dir': '/tmp/cards',
    'warnings': ['bottom_safe_padding_too_small'],
    'next_action': '先修复 warnings，再做视觉抽查',
    'target': sys.argv[1],
}, ensure_ascii=False))
sys.exit(1)
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setitem(backends.XHS_SCRIPT_PATHS, "script_image_qa", fake_script)
    input_path = tmp_path / "xhs-qa-input.json"
    input_path.write_text(json.dumps({"target": str(pending)}), encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "run",
            "xhs.image-qa",
            str(input_path),
            "--preview-dir",
            str(tmp_path / "preview"),
            "--json",
        ],
    )

    payload = parse_json(result)
    assert payload["ok"] is True
    assert payload["data"]["capability"] == "xhs.image-qa"
    assert payload["data"]["status"] == "needs_attention"
    assert payload["data"]["qa_exit_code"] == 1
    assert payload["warnings"] == ["bottom_safe_padding_too_small"]
    bundle_dir = Path(payload["artifacts"][0]["path"])
    artifact = json.loads((bundle_dir / "artifacts" / "image-qa.json").read_text(encoding="utf-8"))
    assert artifact["qa"]["warnings"] == ["bottom_safe_padding_too_small"]


def test_xhs_finalize_preview_bundles_blocked_preview(tmp_path, monkeypatch):
    pending = tmp_path / "pending.json"
    write_xhs_pending(pending, with_images=True)
    fake_script = tmp_path / "xhs_finalize_preview.py"
    fake_script.write_text(
        """
import json
import sys
print(json.dumps({
    'ok': True,
    'pending_file': sys.argv[1],
    'allow_preview': False,
    'block_text': 'QA 未通过，已拦截预览发送',
    'image_paths': [],
    'gate': {'reasons': ['missing_required_pngs']},
}, ensure_ascii=False))
sys.exit(1)
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setitem(backends.XHS_SCRIPT_PATHS, "script_finalize_preview", fake_script)
    input_path = tmp_path / "xhs-finalize-input.json"
    input_path.write_text(json.dumps({"pending_file": str(pending)}), encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "run",
            "xhs.finalize-preview",
            str(input_path),
            "--preview-dir",
            str(tmp_path / "preview"),
            "--json",
        ],
    )

    payload = parse_json(result)
    assert payload["ok"] is True
    assert payload["data"]["capability"] == "xhs.finalize-preview"
    assert payload["data"]["status"] == "blocked"
    assert payload["data"]["allow_preview"] is False
    bundle_dir = Path(payload["artifacts"][0]["path"])
    artifact = json.loads(
        (bundle_dir / "artifacts" / "finalize-preview.json").read_text(encoding="utf-8")
    )
    assert artifact["preview"]["block_text"] == "QA 未通过，已拦截预览发送"


def test_xhs_publish_is_external_write_blocked_by_default(tmp_path):
    pending = tmp_path / "pending.json"
    write_xhs_pending(pending, with_images=True)
    input_path = tmp_path / "publish-input.json"
    input_path.write_text(json.dumps({"pending_file": str(pending)}), encoding="utf-8")

    result = runner.invoke(app, ["run", "xhs.publish", str(input_path), "--json"])

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["error"]["type"] == "unsafe_side_effect"
    assert "--allow-external-write" in payload["error"]["fix"]


def test_xhs_bundle_redacts_sensitive_values_from_artifacts(tmp_path):
    input_path = tmp_path / "input.json"
    input_path.write_text(
        json.dumps({"api_key": "SECRETINPUT", "nested": {"token": "SECRETTOKEN"}}),
        encoding="utf-8",
    )

    response = backends.write_xhs_bundle(
        capability_id="xhs.image-qa",
        input_path=input_path,
        input_data={"api_key": "SECRETINPUT", "nested": {"token": "SECRETTOKEN"}},
        payload={
            "status": "needs_attention",
            "qa": {
                "authorization": "Bearer SECRETBEARER",
                "log": "api_key=SECRETINLINE token:SECRETCOLON",
            },
        },
        preview_dir=tmp_path / "preview",
    )

    assert response.ok is True
    bundle_dir = Path(response.artifacts[0].path)
    bundle_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in [
            bundle_dir / "manifest.json",
            bundle_dir / "summary.json",
            bundle_dir / "artifacts" / "image-qa.json",
        ]
    )
    assert "SECRETINPUT" not in bundle_text
    assert "SECRETTOKEN" not in bundle_text
    assert "SECRETBEARER" not in bundle_text
    assert "SECRETINLINE" not in bundle_text
    assert "SECRETCOLON" not in bundle_text
    assert "[REDACTED]" in bundle_text


def test_site_bundle_redacts_sensitive_values_from_artifacts(tmp_path):
    input_path = tmp_path / "site-input.json"
    input_path.write_text(json.dumps({"token": "SITETOKEN"}), encoding="utf-8")

    response = backends.write_site_bundle(
        capability_id="site.build",
        input_path=input_path,
        input_data={"token": "SITETOKEN"},
        payload={
            "returncode": 0,
            "stdout": "authorization: Bearer SITEBEARER",
            "stderr": "password=SITEPASSWORD",
        },
        preview_dir=tmp_path / "preview",
    )

    assert response.ok is True
    bundle_dir = Path(response.artifacts[0].path)
    bundle_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in [
            bundle_dir / "manifest.json",
            bundle_dir / "summary.json",
            bundle_dir / "artifacts" / "build.json",
        ]
    )
    assert "SITETOKEN" not in bundle_text
    assert "SITEBEARER" not in bundle_text
    assert "SITEPASSWORD" not in bundle_text
    assert "[REDACTED]" in bundle_text


def test_distill_bundle_redacts_sensitive_values_from_artifacts(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    write_minimal_distill_vault(vault)
    input_path = tmp_path / "distill-health-input.json"
    input_path.write_text(
        json.dumps({"vault": str(vault), "api_key": "DISTILLINPUT"}),
        encoding="utf-8",
    )

    def fake_run(*_args, **_kwargs):
        return backends.subprocess.CompletedProcess(
            args=["distill"],
            returncode=0,
            stdout=json.dumps(
                {
                    "runtime_stage": "ok",
                    "token": "DISTILLTOKEN",
                    "log": "secret=DISTILLSECRET",
                }
            ),
            stderr="",
        )

    monkeypatch.setattr(backends.subprocess, "run", fake_run)

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
    bundle_dir = Path(payload["artifacts"][0]["path"])
    bundle_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in [
            bundle_dir / "manifest.json",
            bundle_dir / "summary.json",
            bundle_dir / "artifacts" / "health.json",
        ]
    )
    assert "DISTILLINPUT" not in bundle_text
    assert "DISTILLTOKEN" not in bundle_text
    assert "DISTILLSECRET" not in bundle_text
    assert "[REDACTED]" in bundle_text


def test_xhs_select_pending_creates_preview_bundle(tmp_path):
    pending_dir = tmp_path / "pending"
    pending_dir.mkdir()
    old_pending = pending_dir / "20260518_old.json"
    write_xhs_pending(old_pending, with_images=True)
    target_pending = pending_dir / "20260519_new.json"
    write_xhs_pending(target_pending, with_images=False)
    input_path = tmp_path / "select-input.json"
    input_path.write_text(json.dumps({"pending_dir": str(pending_dir)}), encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "run",
            "xhs.select-pending",
            str(input_path),
            "--preview-dir",
            str(tmp_path / "preview"),
            "--json",
        ],
    )

    payload = parse_json(result)
    assert payload["ok"] is True
    assert payload["data"]["capability"] == "xhs.select-pending"
    assert payload["data"]["pending_file"] == str(target_pending)
    bundle_dir = Path(payload["artifacts"][0]["path"])
    assert (bundle_dir / "manifest.json").exists()
    assert (bundle_dir / "summary.json").exists()
    assert (bundle_dir / "artifacts" / "select-pending.json").exists()
    inspect_payload = json.loads(runner.invoke(app, ["inspect", str(bundle_dir), "--json"]).output)
    assert inspect_payload["data"]["capability"] == "xhs.select-pending"
    assert inspect_payload["data"]["artifact_count"] == 1


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
    inspect_payload = json.loads(runner.invoke(app, ["inspect", str(bundle_dir), "--json"]).output)
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
    pending_dir = tmp_path / "pending"
    pending_dir.mkdir()
    target_pending = pending_dir / "20260519_new.json"
    write_xhs_pending(target_pending, with_images=False)
    input_path = tmp_path / "select-input.json"
    input_path.write_text(json.dumps({"pending_dir": str(pending_dir)}), encoding="utf-8")
    preview_dir = tmp_path / "preview"
    run_result = runner.invoke(
        app,
        [
            "run",
            "xhs.select-pending",
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
    assert payload["data"]["capability"] == "xhs.select-pending"
    assert payload["data"]["headline"].startswith("xhs.select-pending: selected")
    assert payload["data"]["artifact_count"] == 1
    assert payload["next_actions"] == [
        "Run xhs.generate-cards for the selected pending_file before previewing."
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
                "artifacts": [{"id": "missing", "kind": "text", "path": "artifacts/missing.txt"}],
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
    inspect_payload = json.loads(runner.invoke(app, ["inspect", str(bundle_dir), "--json"]).output)
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


def test_subprocess_backend_failure_redacts_sensitive_output(tmp_path):
    script_path = tmp_path / "leaky_backend.py"
    script_path.write_text(
        """
import sys
print('token=BACKENDSTDOUT')
print('authorization: Bearer BACKENDSTDERR', file=sys.stderr)
sys.exit(1)
""".strip(),
        encoding="utf-8",
    )
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
    message = payload["error"]["message"]
    assert "BACKENDSTDOUT" not in message
    assert "BACKENDSTDERR" not in message
    assert "[REDACTED]" in message


def test_registry_and_backend_xhs_capabilities_share_same_specs():
    result = runner.invoke(app, ["registry", "list", "--json"])

    payload = parse_json(result)
    xhs_tool = next(tool for tool in payload["data"]["tools"] if tool["name"] == "xhs-image-cards")
    registry_by_id = {capability["id"]: capability for capability in xhs_tool["capabilities"]}

    assert set(registry_by_id) == set(XHS_CAPABILITY_SPECS)
    for capability_id, spec in XHS_CAPABILITY_SPECS.items():
        assert registry_by_id[capability_id]["side_effect"] == spec.side_effect
        assert registry_by_id[capability_id]["backend"]["target"] == "run_xhs_command"


def test_registry_and_backend_distill_capabilities_share_same_specs():
    result = runner.invoke(app, ["registry", "list", "--json"])

    payload = parse_json(result)
    distill_tool = next(
        tool for tool in payload["data"]["tools"] if tool["name"] == "distill-vault"
    )
    registry_by_id = {capability["id"]: capability for capability in distill_tool["capabilities"]}

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
