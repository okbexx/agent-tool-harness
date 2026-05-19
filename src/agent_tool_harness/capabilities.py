from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

SideEffect = Literal["none", "local_files", "network", "external_write"]
OutputKind = Literal["json", "json_or_stdout", "text"]


@dataclass(frozen=True)
class DistillCapabilitySpec:
    id: str
    name: str
    summary: str
    artifact: str
    output: OutputKind = "json"
    side_effect: SideEffect = "local_files"
    args: tuple[str, ...] = field(default_factory=tuple)
    required_extra: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class SiteCapabilitySpec:
    id: str
    name: str
    summary: str
    artifact: str
    side_effect: SideEffect = "local_files"


DISTILL_CAPABILITY_SPECS: dict[str, DistillCapabilitySpec] = {
    "distill.status": DistillCapabilitySpec(
        id="distill.status",
        name="status",
        summary="Run distill status and bundle the JSON report.",
        args=("status", "--format", "json"),
        artifact="status.json",
    ),
    "distill.health": DistillCapabilitySpec(
        id="distill.health",
        name="health",
        summary="Run distill health and bundle the JSON report.",
        args=("health", "--format", "json"),
        artifact="health.json",
    ),
    "distill.capabilities": DistillCapabilitySpec(
        id="distill.capabilities",
        name="capabilities",
        summary="Show engine capability surface and bundle the JSON report.",
        args=("capabilities", "--format", "json"),
        artifact="capabilities.json",
    ),
    "distill.instance-doctor": DistillCapabilitySpec(
        id="distill.instance-doctor",
        name="instance_doctor",
        summary="Audit engine-to-instance runtime adoption.",
        args=("doctor", "--instance-upgrade", "--format", "json"),
        artifact="instance-doctor.json",
    ),
    "distill.upgrade-plan": DistillCapabilitySpec(
        id="distill.upgrade-plan",
        name="upgrade_plan",
        summary="Build the instance upgrade plan.",
        args=("upgrade-plan", "--format", "json"),
        artifact="upgrade-plan.json",
    ),
    "distill.lint-check": DistillCapabilitySpec(
        id="distill.lint-check",
        name="lint_check",
        summary="Run distill lint without fixes.",
        args=("lint", "--format", "json"),
        artifact="lint-check.json",
    ),
    "distill.lint-fix": DistillCapabilitySpec(
        id="distill.lint-fix",
        name="lint_fix",
        summary="Run distill lint with automatic fixes.",
        args=("lint", "--fix", "--format", "json"),
        artifact="lint-fix.json",
        side_effect="external_write",
    ),
    "distill.promote-dry-run": DistillCapabilitySpec(
        id="distill.promote-dry-run",
        name="promote_dry_run",
        summary="Preview promotion queue.",
        args=("promote", "--dry-run", "--format", "json"),
        artifact="promote-dry-run.txt",
        output="json_or_stdout",
    ),
    "distill.promote-auto": DistillCapabilitySpec(
        id="distill.promote-auto",
        name="promote_auto",
        summary="Auto-promote low-risk promotion queue items.",
        args=("promote", "--auto", "--format", "json"),
        artifact="promote-auto.json",
        output="json_or_stdout",
        side_effect="external_write",
    ),
    "distill.pipeline-run": DistillCapabilitySpec(
        id="distill.pipeline-run",
        name="pipeline_run",
        summary="Run the distill pipeline and bundle the JSON report.",
        args=("run", "--format", "json"),
        artifact="pipeline-run.json",
    ),
    "distill.route": DistillCapabilitySpec(
        id="distill.route",
        name="route",
        summary="Plan the minimal read/write surface for an intent.",
        artifact="route.json",
        required_extra=("intent",),
    ),
    "distill.plan": DistillCapabilitySpec(
        id="distill.plan",
        name="plan",
        summary="Return the full action plan for an intent.",
        artifact="plan.json",
        required_extra=("intent",),
    ),
    "distill.capture": DistillCapabilitySpec(
        id="distill.capture",
        name="capture",
        summary="Apply the minimal progress-capture path for an intent.",
        artifact="capture.json",
        side_effect="external_write",
        required_extra=("intent",),
    ),
    "distill.apply": DistillCapabilitySpec(
        id="distill.apply",
        name="apply",
        summary="Alias for the minimal progress-capture write path.",
        artifact="apply.json",
        side_effect="external_write",
        required_extra=("intent",),
    ),
    "distill.search": DistillCapabilitySpec(
        id="distill.search",
        name="search",
        summary="Search vault objects and bundle the text results.",
        artifact="search.txt",
        output="text",
        required_extra=("query",),
    ),
}


SITE_CAPABILITY_SPECS: dict[str, SiteCapabilitySpec] = {
    "site.status": SiteCapabilitySpec(
        id="site.status",
        name="status",
        summary="Inspect the personal Astro site repository and bundle status metadata.",
        artifact="status.json",
    ),
    "site.build": SiteCapabilitySpec(
        id="site.build",
        name="build",
        summary="Run the personal site build and bundle the build report.",
        artifact="build.json",
        side_effect="external_write",
    ),
    "site.check-links": SiteCapabilitySpec(
        id="site.check-links",
        name="check_links",
        summary="Check generated personal site links and bundle the link report.",
        artifact="check-links.json",
    ),
    "site.deploy": SiteCapabilitySpec(
        id="site.deploy",
        name="deploy",
        summary="Deploy the built personal site to GitHub Pages.",
        artifact="deploy.json",
        side_effect="external_write",
    ),
}
