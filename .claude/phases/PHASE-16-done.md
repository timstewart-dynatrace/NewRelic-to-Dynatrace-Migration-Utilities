# Phase 16 — Close P0 Gaps: Agents, RUM, Custom Instrumentation, Lambda
Status: PENDING

## Goal
Add four transformer/orchestrator modules that each address a P0 hold-up gap from `docs/migration-coverage.md`. After this phase every customer-critical migration surface has at least a scaffold.

## Tasks
- [ ] **`agents/` module** — per-language APM-agent orchestrator (Java, .NET, Node.js, Python, Ruby, PHP, Go)
  - Interface: `uninstall_nr()`, `install_oneagent()`, `install_otel_fallback()`, `verify()`
  - `migrate.py agents --language <L> [--dry-run]` subcommand
  - Rollback manifest: restore NR agent per host
  - Mocks for package-manager + filesystem in unit tests
- [ ] **`transformers/browser_rum_transformer.py`** — NR Browser app → DT RUM application
  - Map snippet install → OneAgent auto-inject directive (or manual snippet payload)
  - Core Web Vitals metric mapping (LCP/FID/CLS/INP/TTFB/FCP)
  - Source-mapping table: `PageView`, `BrowserInteraction`, `AjaxRequest`, `JavaScriptError`
  - Emit Settings 2.0 envelope `builtin:rum.web.app-config` (verify schema)
- [ ] **`transformers/mobile_rum_transformer.py`** — NR Mobile → DT Mobile app
  - Per-platform SDK swap guidance (Android, iOS, React Native, Flutter)
  - Event mapping: `MobileSession`, `MobileCrash`, `MobileRequest`, handled exceptions
  - Symbolication asset migration helper (dSYM, ProGuard/R8)
  - Emit Settings 2.0 envelope `builtin:mobile-application`
- [ ] **`transformers/custom_instrumentation_translator.py`** — AST translator for `newrelic.*()` calls
  - Per-language adapters: Java, .NET, Node.js, Python
  - Maps `recordCustomEvent` → `bizevent.ingest`, `addCustomAttribute` → OneAgent SDK attribute, `recordMetric` → OTel Meter, `noticeError` → span event, `setTransactionName` → request-naming rule, `startSegment`/`endSegment` → OTel span
  - Diff-mode output: show suggested replacement per call site
- [ ] **`transformers/lambda_transformer.py`** — NR Lambda → DT Lambda extension
  - Input: AWS integration export (role, function inventory)
  - Output: Lambda layer ARN insertion instructions + DT env vars + tracing config
  - Linked to `CloudIntegrationTransformer` (Phase 17) for AWS-wide config

## Acceptance Criteria
- Each new module has ≥ 20 unit tests covering happy path + 2 failure modes per language/platform
- `python migrate.py agents --language java --dry-run` completes on a fixture
- `migration-coverage.md` updated — matching rows flip 🔴 → ✅ or 🟡 (partial/scaffold)
- `COVERAGE-MATRIX.md` rows in the notebooks repo *also* flagged for update (cross-repo PR)
- No regressions: full `pytest tests/ -q` stays green

## Decisions Made This Phase
(append as you go)
