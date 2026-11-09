# CHAOS-INTEL Security Policy, Assumptions & Known Limitations

## Security Model & Safeguards

### 1. Live Chaos Execution Ban (Hard Fenced)
- In accordance with platform reliability policies, **live chaos execution against running infrastructure is hard-disabled**.
- Attempting to pass `dry_run: false` to `/api/v1/chaos/executions` returns an immediate `400 Bad Request`.
- All fault simulations are modeled mathematically through steady-state evaluation, blast-radius propagation, and dry-run state machine transitions.

### 2. Causation Guardrail
- Inferred failure causes are mathematical hypotheses calculated via Bayesian confidence scores and multi-signal time-series correlation.
- The platform strictly enforces `is_causation_proven: false` on all root-cause outputs. Inferred hypotheses are never presented as proven facts.

### 3. Archive Upload Defense
- **Path Traversal / ZipSlip Protection**: Every file path inside uploaded archives is strictly checked to guarantee it resolves within the designated staging sandbox.
- **Decompression Bomb Protection**: Quotas enforce maximum uncompressed size (150 MB) and maximum file count (500 files).
- **Sanitized Filenames**: Basenames are stripped and regex-sanitized to prevent directory traversal in file headers.

### 4. RBAC & Key Comparison
- Constant-time string comparison (`secrets.compare_digest`) prevents timing attacks on API keys.
- Role hierarchy strictly gates write, execution, and approval capabilities.

---

## Known Limitations

1. **Static AST Analysis Language Scope**: Static discovery focuses on Python (FastAPI, Flask, Django) and Node.js (Express, Next.js). Other language runtimes are cataloged via generic manifest detection.
2. **PostgreSQL Integration Tests in CI vs Local**: PostgreSQL integration tests require Docker (`testcontainers`). On environments without Docker daemon access, these tests are skipped locally and enforced in the dedicated GitHub Actions runner.
3. **Telemetry Integration Adapters**: Real-time streaming adapters for OpenTelemetry Collector, Prometheus, and Grafana Loki are prepared with standardized ingestion contracts; full live cluster scraping stacks are not deployed locally.
4. **Browser Testing in Headless Mode**: Playwright browser execution requires local browser binaries installed (`playwright install`). When uninstalled, UI adapter runs in sandboxed mock verification mode.

