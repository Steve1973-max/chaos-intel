# Integration Contracts

This directory contains human-readable documentation and proposals for inter-subsystem communication.
The canonical machine-readable JSON schemas are located in `packages/schemas/`.

## Person 3 (Platform) ↔ Person 1 (Application Intelligence) Boundary

For this foundation phase, the communication between Person 3 and Person 1 is designed as a **clean service interface** (e.g., Python function calls or a simple HTTP endpoint), rather than relying on complex message queues (Redis/Celery) or gRPC. This allows the execution mechanism to be easily swapped later without rewriting the Application Intelligence domain.

### Intended Future Flow

1. **Trigger:**
   Person 3 (Platform) initiates an Application Analysis Job when a new application is onboarded.
2. **Job Execution:**
   The Job invokes Person 1 (Application Intelligence) via the service interface, providing the application source path or repository URL.
3. **Intelligence Processing:**
   Person 1 ingests the source, detects technologies, analyzes dependencies, and builds the architecture graph.
4. **Data Contract Return:**
   Person 1 returns a structured `ApplicationModel` (valid against `application.schema.json` and its sub-schemas) back to the calling job.
5. **Storage:**
   Person 3 persists the ApplicationModel in the PostgreSQL database for the frontend (Person 4) to consume.

```text
Person 3
   ↓
Application Analysis Job
   ↓
Person 1 Application Intelligence
   ↓
ApplicationModel
   ↓
Person 3
```
