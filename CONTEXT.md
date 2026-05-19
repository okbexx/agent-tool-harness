# Agent Tool Harness Context

A small contract layer for turning internal tools into agent-usable capabilities.

## Language

**Harness**:
A thin command contract that lets an agent discover, validate, run, and inspect a tool without learning the tool's private workflow.
_Avoid_: Framework, platform, monorepo

**Capability**:
A single agent-callable action exposed by a tool, identified by a stable dotted id such as `xhs.generate-cards`.
_Avoid_: Function, command, feature

**Preview Bundle**:
A local directory artifact containing `manifest.json`, `summary.json`, and generated preview files for a run.
_Avoid_: Output folder, temp directory

**Skill Export**:
A generated `SKILL.md` document that teaches an agent when and how to use a capability.
_Avoid_: Docs dump, README copy

## Relationships

- A **Harness** exposes one or more **Capabilities**.
- A **Capability** may produce one **Preview Bundle**.
- A **Skill Export** is generated from capability metadata, not handwritten per run.
