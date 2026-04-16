# Phase 18 — Cloud Integrations, Kubernetes, AIOps, Specialized Products
Status: PENDING

## Goal
Migrate cloud-vendor integrations and Dynatrace-platform-specialized products: AWS/Azure/GCP, K8s, AIOps incident flows, Vulnerability Management, NPM, AI Monitoring.

## Tasks
- [ ] **`transformers/cloud_integration_transformer.py`**
  - AWS: enumerate NR AWS link account config → emit DT AWS integration Settings 2.0 (`builtin:cloud.aws`) + IAM role policy scaffolds
  - Azure: NR Azure link → `builtin:cloud.azure`
  - GCP: NR GCP link → `builtin:cloud.gcp`
  - Per-service mapping table: RDS/DynamoDB/EC2/EKS/Azure SQL/VMs/App Service/AKS/Cloud SQL/GKE/BigQuery
- [ ] **`transformers/kubernetes_transformer.py`**
  - NR Kubernetes integration config (cluster name, namespaces, labels) → DynaKube CR
  - Emits Helm values.yaml or kubectl manifest
  - Handles node-level vs pod-level scope
- [ ] **`transformers/aiops_transformer.py`**
  - NR AI Workflows → DT Workflows (with explicit rename to avoid naming clash)
  - Destinations (webhook targets) → Workflow tasks (delegates to `NotificationTransformer`)
  - Enrichments (NRQL context injection) → Workflow enrichment steps
  - Anomaly-detection settings → Davis anomaly detector payloads
- [ ] **`transformers/vulnerability_transformer.py`** — NR Vulnerability Management → DT Application Security (Runtime Vulnerability Analytics)
  - Extracts NR vulnerability rules / mute lists
  - Emits DT RVA settings + suppression rules
- [ ] **`transformers/npm_transformer.py`** — NR Network Performance Monitoring → DT Network monitoring
  - Device/flow config scaffold
- [ ] **`transformers/ai_monitoring_transformer.py`** — NR Model Performance / AI Monitoring → DT AI Observability
  - Model registry mapping
  - Inference event source mapping
- [ ] **`transformers/prometheus_transformer.py`** — NR Prometheus Agent config → DT Prometheus remote-write config

## Acceptance Criteria
- Cloud integration transformers produce Settings 2.0 payloads verified against real schemas
- Kubernetes transformer output installs cleanly in a minikube test environment (integration test, env-var gated)
- All new modules have ≥ 10 unit tests each
- Coverage doc updated; every §16 row ≥ 🟡

## Decisions Made This Phase
(append as you go)
