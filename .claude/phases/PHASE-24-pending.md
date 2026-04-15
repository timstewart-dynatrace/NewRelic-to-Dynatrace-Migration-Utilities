# Phase 24 — Second-Wave nrql-engine Parity
Status: PENDING (release-hold also applies)

## Goal
Port the 8 transformer candidates surfaced in the second-pass
nrql-engine audit (`docs/nrql-engine-sync-audit.md` second-pass section)
that aren't covered by Phases 16–23.

Each task: verify the TS module exists in source (initial audit was
overstated), then port to Python with the same shape as Phase 16-18
transformers (Settings 2.0 envelopes + runbook + warnings + tests).

## Tasks
- [ ] Verify each TS module exists in `nrql-engine/src/transformers/` before porting
- [ ] `transformers/database_monitoring_transformer.py` — NR DB monitoring → DT DB extensions (MySQL/Postgres/Mongo/Redis/MSSQL/Oracle/Cassandra/MariaDB/DB2/SAP HANA)
- [ ] `transformers/on_host_integration_transformer.py` — NR on-host integrations (NGINX/HAProxy/Kafka/RabbitMQ/Elasticsearch/Memcached/Couchbase/Consul/Apache/etcd) → DT extension config
- [ ] `transformers/security_signals_transformer.py` — NR Security Signals/IAST → DT Security Investigator (`builtin:appsec.security-signals`)
- [ ] `transformers/custom_entity_transformer.py` — NR custom entities → DT custom-device API (`/api/v2/entities/custom`)
- [ ] `transformers/log_archive_transformer.py` — NR Log Live Archive + Streaming Export → Grail bucket + OpenPipeline egress with compliance tags
- [ ] `transformers/metric_normalization_transformer.py` — NR metric normalization rules → DT metric processor rules (rename/aggregate/drop)
- [ ] `transformers/synthetic_specialized_transformer.py` — Cert-check and broken-links synthetic monitors (specialization beyond `SyntheticTransformer`)
- [ ] `transformers/saved_filter_notebook_transformer.py` — NR Saved Filters / Data App widgets → DT Notebooks (Document API `type=='notebook'`)
- [ ] Register in `transformers/__init__.py` + orchestrator
- [ ] ≥ 8 unit tests per transformer
- [ ] Update coverage matrix

## Acceptance Criteria
- Coverage matrix gains rows for these 8 surfaces (status ✅ once tested)
- Full pytest suite stays green
- `docs/nrql-engine-sync-audit.md` second-pass section updated to
  reflect parity for each ported item
