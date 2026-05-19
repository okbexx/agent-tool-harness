from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from typer.testing import CliRunner

from agent_tool_harness import backends
from agent_tool_harness.cli import app

runner = CliRunner()


def parse_json(result):
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


def write_minimal_personal_site(path: Path) -> None:
    (path / "src" / "pages").mkdir(parents=True)
    (path / "dist").mkdir()
    (path / "package.json").write_text(
        json.dumps(
            {
                "name": "personal-site",
                "type": "module",
                "scripts": {"build": "astro build"},
                "dependencies": {"astro": "^6.1.8"},
            }
        ),
        encoding="utf-8",
    )
    (path / "src" / "pages" / "index.astro").write_text("<h1>Hello</h1>\n", encoding="utf-8")
    (path / "dist" / "index.html").write_text("<h1>Hello</h1>\n", encoding="utf-8")


def test_registry_list_exposes_personal_site_capabilities():
    result = runner.invoke(app, ["registry", "list", "--json"])

    payload = parse_json(result)
    personal_site = next(
        tool for tool in payload["data"]["tools"] if tool["name"] == "personal-site"
    )
    capabilities = {capability["id"]: capability for capability in personal_site["capabilities"]}

    assert set(capabilities) == {
        "site.status",
        "site.build",
        "site.check-links",
        "site.deploy",
    }
    assert capabilities["site.status"]["side_effect"] == "local_files"
    assert capabilities["site.build"]["side_effect"] == "external_write"
    assert capabilities["site.check-links"]["side_effect"] == "local_files"
    assert capabilities["site.deploy"]["side_effect"] == "external_write"
    assert capabilities["site.status"]["backend"]["target"] == "run_site_command"


def test_site_status_creates_preview_bundle(tmp_path):
    site = tmp_path / "personal-site"
    write_minimal_personal_site(site)
    input_path = tmp_path / "site-status-input.json"
    input_path.write_text(json.dumps({"site": str(site)}), encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "run",
            "site.status",
            str(input_path),
            "--preview-dir",
            str(tmp_path / "preview"),
            "--json",
        ],
    )

    payload = parse_json(result)
    assert payload["ok"] is True
    assert payload["data"]["capability"] == "site.status"
    assert payload["data"]["site"] == str(site.resolve())
    assert payload["data"]["package_name"] == "personal-site"
    bundle_dir = Path(payload["artifacts"][0]["path"])
    manifest = json.loads((bundle_dir / "manifest.json").read_text(encoding="utf-8"))
    summary = json.loads((bundle_dir / "summary.json").read_text(encoding="utf-8"))
    status = json.loads((bundle_dir / "artifacts" / "status.json").read_text(encoding="utf-8"))
    assert manifest["protocol_version"] == "preview-bundle/v1"
    assert manifest["tool"] == "personal-site"
    assert manifest["capability"] == "site.status"
    assert summary["headline"] == "site.status: personal-site ready"
    assert status["package_name"] == "personal-site"


def test_site_build_is_blocked_without_allow_flag(tmp_path):
    site = tmp_path / "personal-site"
    write_minimal_personal_site(site)
    input_path = tmp_path / "site-build-input.json"
    input_path.write_text(json.dumps({"site": str(site)}), encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "run",
            "site.build",
            str(input_path),
            "--preview-dir",
            str(tmp_path / "preview"),
            "--json",
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["error"] == {
        "type": "unsafe_side_effect",
        "message": "Capability site.build has side effect external_write",
        "fix": "Re-run with --allow-external-write only after explicit user approval",
    }
    assert not (tmp_path / "preview").exists()


def test_site_build_runs_npm_build_with_allow_flag_and_bundles_report(tmp_path, monkeypatch):
    site = tmp_path / "personal-site"
    write_minimal_personal_site(site)
    input_path = tmp_path / "site-build-input.json"
    input_path.write_text(json.dumps({"site": str(site)}), encoding="utf-8")
    calls = []

    def fake_run(command, **kwargs):
        calls.append({"command": command, "kwargs": kwargs})
        (site / "dist" / "built.txt").write_text("ok\n", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="built\n", stderr="")

    monkeypatch.setattr(backends.subprocess, "run", fake_run)

    result = runner.invoke(
        app,
        [
            "run",
            "site.build",
            str(input_path),
            "--preview-dir",
            str(tmp_path / "preview"),
            "--allow-external-write",
            "--json",
        ],
    )

    payload = parse_json(result)
    assert payload["ok"] is True
    assert payload["data"]["capability"] == "site.build"
    assert payload["data"]["returncode"] == 0
    assert calls[0]["command"] == ["npm", "run", "build"]
    assert calls[0]["kwargs"]["cwd"] == site
    bundle_dir = Path(payload["artifacts"][0]["path"])
    build_report = json.loads((bundle_dir / "artifacts" / "build.json").read_text(encoding="utf-8"))
    summary = json.loads((bundle_dir / "summary.json").read_text(encoding="utf-8"))
    assert build_report["stdout"] == "built\n"
    assert build_report["dist_exists"] is True
    assert summary["headline"] == "site.build: build passed"


def test_site_check_links_reports_missing_local_targets(tmp_path):
    site = tmp_path / "personal-site"
    write_minimal_personal_site(site)
    (site / "dist" / "about").mkdir()
    (site / "dist" / "about" / "index.html").write_text("<h1>About</h1>\n", encoding="utf-8")
    (site / "dist" / "index.html").write_text(
        '<a href="/about/">About</a>\n'
        '<a href="/missing/">Missing</a>\n'
        '<a href="#intro">Anchor</a>\n'
        '<a href="https://example.com">External</a>\n',
        encoding="utf-8",
    )
    input_path = tmp_path / "site-check-links-input.json"
    input_path.write_text(json.dumps({"site": str(site)}), encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "run",
            "site.check-links",
            str(input_path),
            "--preview-dir",
            str(tmp_path / "preview"),
            "--json",
        ],
    )

    payload = parse_json(result)
    assert payload["ok"] is True
    assert payload["data"]["capability"] == "site.check-links"
    assert payload["data"]["broken_link_count"] == 1
    bundle_dir = Path(payload["artifacts"][0]["path"])
    report = json.loads((bundle_dir / "artifacts" / "check-links.json").read_text(encoding="utf-8"))
    summary = json.loads((bundle_dir / "summary.json").read_text(encoding="utf-8"))
    assert report["checked_link_count"] == 2
    assert report["broken_links"] == [
        {
            "source": "index.html",
            "href": "/missing/",
            "target": "missing/index.html",
        }
    ]
    assert summary["headline"] == "site.check-links: 1 broken local link(s)"


def test_site_check_links_resolves_relative_links_from_source_dir(tmp_path):
    site = tmp_path / "personal-site"
    write_minimal_personal_site(site)
    (site / "dist" / "blog").mkdir()
    (site / "dist" / "about").mkdir()
    (site / "dist" / "about" / "index.html").write_text("<h1>About</h1>\n", encoding="utf-8")
    (site / "dist" / "blog" / "index.html").write_text(
        '<a href="../about/">About</a>\n',
        encoding="utf-8",
    )
    input_path = tmp_path / "site-check-links-input.json"
    input_path.write_text(json.dumps({"site": str(site)}), encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "run",
            "site.check-links",
            str(input_path),
            "--preview-dir",
            str(tmp_path / "preview"),
            "--json",
        ],
    )

    payload = parse_json(result)
    assert payload["data"]["broken_link_count"] == 0
    bundle_dir = Path(payload["artifacts"][0]["path"])
    report = json.loads((bundle_dir / "artifacts" / "check-links.json").read_text(encoding="utf-8"))
    assert report["checked_links"] == [
        {
            "source": "blog/index.html",
            "href": "../about/",
            "target": "about/index.html",
        }
    ]


def test_site_deploy_is_blocked_without_allow_flag(tmp_path):
    site = tmp_path / "personal-site"
    write_minimal_personal_site(site)
    input_path = tmp_path / "site-deploy-input.json"
    input_path.write_text(json.dumps({"site": str(site)}), encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "run",
            "site.deploy",
            str(input_path),
            "--preview-dir",
            str(tmp_path / "preview"),
            "--json",
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["error"] == {
        "type": "unsafe_side_effect",
        "message": "Capability site.deploy has side effect external_write",
        "fix": "Re-run with --allow-external-write only after explicit user approval",
    }
    assert not (tmp_path / "preview").exists()


def test_site_deploy_pushes_dist_to_gh_pages_with_allow_flag(tmp_path, monkeypatch):
    site = tmp_path / "personal-site"
    write_minimal_personal_site(site)
    input_path = tmp_path / "site-deploy-input.json"
    input_path.write_text(json.dumps({"site": str(site)}), encoding="utf-8")
    calls = []

    def fake_run(command, **kwargs):
        calls.append({"command": command, "kwargs": kwargs})
        if command == ["git", "remote", "get-url", "origin"]:
            return SimpleNamespace(
                returncode=0,
                stdout="https://okbexx:secret-token@github.com/okbexx/okbexx.github.io.git\n",
                stderr="",
            )
        return SimpleNamespace(returncode=0, stdout="ok\n", stderr="")

    monkeypatch.setattr(backends.subprocess, "run", fake_run)

    result = runner.invoke(
        app,
        [
            "run",
            "site.deploy",
            str(input_path),
            "--preview-dir",
            str(tmp_path / "preview"),
            "--allow-external-write",
            "--json",
        ],
    )

    payload = parse_json(result)
    assert payload["ok"] is True
    assert payload["data"]["capability"] == "site.deploy"
    assert payload["data"]["remote"] == "https://okbexx:[REDACTED]@github.com/okbexx/okbexx.github.io.git"
    commands = [call["command"] for call in calls]
    assert commands == [
        ["git", "remote", "get-url", "origin"],
        ["git", "init"],
        ["git", "add", "."],
        ["git", "commit", "-m", "deploy: personal-site"],
        [
            "git",
            "push",
            "-f",
            "https://okbexx:secret-token@github.com/okbexx/okbexx.github.io.git",
            "HEAD:gh-pages",
        ],
    ]
    bundle_dir = Path(payload["artifacts"][0]["path"])
    report = json.loads((bundle_dir / "artifacts" / "deploy.json").read_text(encoding="utf-8"))
    assert report["remote"] == "https://okbexx:[REDACTED]@github.com/okbexx/okbexx.github.io.git"
    assert "secret-token" not in json.dumps(report)
