# Application Intelligence (Person 1)

This subsystem is responsible for ingesting unknown applications, parsing their source/configurations, and generating a structured `ApplicationModel` and `Architecture Graph`.

## Domain Boundaries
- **Input:** Source code path or repository URL (triggered by Person 3 Platform).
- **Output:** Structured JSON adhering to `packages/schemas/` contracts.

## Current Stage: Foundation
Only the core ingestion, detection, and models are being scaffolded. Risk engines, strategy generators, and LLM integrations are strictly deferred to future phases.
