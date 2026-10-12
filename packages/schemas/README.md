# CHAOS-INTEL Shared Contracts

This directory contains the canonical, machine-readable JSON schemas defining the cross-boundary data contracts for all CHAOS-INTEL subsystems.

## Principles
1. **Single Source of Truth:** Do NOT duplicate these schemas as Pydantic models in multiple services without adhering exactly to these definitions. Use these schemas to generate or validate your internal models.
2. **Backward Compatibility:** Once an API or queue relies on a schema, do not introduce breaking changes without team coordination.
3. **No Silos:** Person 1, Person 2, Person 3, and Person 4 all depend on these contracts for integration.

## Implemented Schemas (Foundation Phase)
- `application.schema.json`
- `service.schema.json`
- `dependency.schema.json`
- `architecture.schema.json`

## Planned Schemas (Future Phases)
- `test-candidate.schema.json`
- `experiment-candidate.schema.json`
- `test-run.schema.json`
- `experiment.schema.json`
- `experiment-run.schema.json`
- `finding.schema.json`
- `recommendation.schema.json`
