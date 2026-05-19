# ADR 0001: Keep Agent Tool Harness as a Small Contract Layer

We will build `agent-tool-harness` as a narrow CLI contract layer rather than a generated monorepo or broad automation framework. The harness exposes stable JSON envelopes, no-side-effect health checks, preview bundles, and generated skills; production tool backends can evolve behind those contracts without changing how agents discover or call capabilities.
