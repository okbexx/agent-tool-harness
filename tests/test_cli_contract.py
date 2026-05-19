from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from agent_tool_harness.cli import app

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
    assert tools[0]["healthcheck"] == "agent-tool-harness doctor xhs-image-cards --json"


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


def test_skill_export_is_generated_from_metadata():
    result = runner.invoke(app, ["skill", "export", "xhs.generate-cards", "--json"])

    payload = parse_json(result)

    skill = payload["data"]["skill_md"]
    assert "name: xhs-image-cards" in skill
    assert "capability: xhs.generate-cards" in skill
    assert "## JSON output" in skill
    assert "## Artifacts" in skill
    assert "## Verification" in skill
