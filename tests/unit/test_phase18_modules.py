"""Tests for Phase 18 modules: Cloud (AWS/Azure/GCP), Kubernetes, AIOps,
Vulnerability Mgmt, NPM, AI Monitoring, Prometheus."""


from transformers import (
    AIMonitoringTransformer,
    AIOpsTransformer,
    CloudIntegrationTransformer,
    KubernetesTransformer,
    NPMTransformer,
    PrometheusTransformer,
    VulnerabilityTransformer,
)

# ---------------------------------------------------------------------------
# CloudIntegrationTransformer
# ---------------------------------------------------------------------------


class TestCloudIntegration:
    def test_aws_envelope_has_supporting_services(self):
        r = CloudIntegrationTransformer().transform({
            "provider": "aws",
            "name": "prod-aws",
            "awsAccountId": "123456789012",
            "regions": ["us-east-1", "us-west-2"],
            "services": ["ec2", "rds", "lambda", "dynamodb"],
        })
        assert r.success
        assert r.envelope["schemaId"] == "builtin:cloud.aws"
        svcs = r.envelope["value"]["supportingServicesToMonitor"]
        assert {s["name"] for s in svcs} >= {"ec2", "rds", "lambda", "dynamodb"}
        assert r.envelope["value"]["regions"] == ["us-east-1", "us-west-2"]

    def test_aws_unknown_service_warns(self):
        r = CloudIntegrationTransformer().transform({
            "provider": "aws", "name": "x", "awsAccountId": "1",
            "services": ["mysterious-service"],
        })
        assert any("no direct DT mapping" in w for w in r.warnings)

    def test_azure_envelope(self):
        r = CloudIntegrationTransformer().transform({
            "provider": "azure",
            "name": "prod-azure",
            "subscriptionId": "sub-123",
            "tenantId": "tenant-xyz",
            "services": ["vms", "sql", "aks"],
        })
        assert r.envelope["schemaId"] == "builtin:cloud.azure"
        resources = [s["name"] for s in r.envelope["value"]["monitorResources"]]
        assert "microsoft.compute/virtualmachines" in resources

    def test_gcp_envelope(self):
        r = CloudIntegrationTransformer().transform({
            "provider": "gcp",
            "name": "prod-gcp",
            "projectId": "project-xyz",
            "services": ["gke", "bigquery"],
        })
        assert r.envelope["schemaId"] == "builtin:cloud.gcp"
        svcs = [s["service"] for s in r.envelope["value"]["services"]]
        assert "kubernetes" in svcs and "bigquery" in svcs

    def test_runbook_lists_auth_steps(self):
        r = CloudIntegrationTransformer().transform({
            "provider": "aws", "name": "x", "awsAccountId": "1",
        })
        assert any("IAM role" in s for s in r.runbook["post_import_steps"])

    def test_unsupported_provider_errors(self):
        r = CloudIntegrationTransformer().transform({"provider": "oracle"})
        assert not r.success


# ---------------------------------------------------------------------------
# KubernetesTransformer
# ---------------------------------------------------------------------------


class TestKubernetes:
    def test_full_stack_mode_emits_cloudnative(self):
        r = KubernetesTransformer().transform({
            "clusterName": "prod-east",
            "mode": "full_stack",
            "dtApiUrl": "https://abc.live.dynatrace.com/api",
        })
        assert r.success
        oneagent = r.dynakube_manifest["spec"]["oneAgent"]
        assert oneagent["cloudNativeFullStack"]
        assert oneagent["hostMonitoring"] == {}

    def test_host_only_mode_emits_hostmonitoring(self):
        r = KubernetesTransformer().transform({
            "clusterName": "infra", "mode": "host_only",
        })
        oneagent = r.dynakube_manifest["spec"]["oneAgent"]
        assert oneagent["hostMonitoring"]
        assert oneagent["cloudNativeFullStack"] == {}

    def test_unknown_mode_warns(self):
        r = KubernetesTransformer().transform({
            "clusterName": "weird", "mode": "bespoke",
        })
        assert any("Unknown K8s mode" in w for w in r.warnings)

    def test_namespace_filter_emitted(self):
        r = KubernetesTransformer().transform({
            "clusterName": "x", "namespaces": ["prod", "staging"],
        })
        sel = r.dynakube_manifest["spec"]["namespaceSelector"]
        assert sel["matchExpressions"][0]["values"] == ["prod", "staging"]

    def test_runbook_includes_nri_uninstall(self):
        r = KubernetesTransformer().transform({"clusterName": "x"})
        assert any("newrelic-bundle" in s for s in r.runbook["nri_kubernetes_uninstall"])


# ---------------------------------------------------------------------------
# AIOpsTransformer
# ---------------------------------------------------------------------------


class TestAIOps:
    def test_workflow_migration_tasks_wired(self):
        r = AIOpsTransformer().transform({
            "workflows": [{
                "name": "incident-routing",
                "destinations": [{"name": "slack-ops", "url": "https://hooks.slack/x"}],
                "enrichments": [{"name": "ctx", "nrql": "SELECT count(*) FROM Log"}],
            }],
        })
        assert r.success and len(r.workflows) == 1
        wf = r.workflows[0]
        assert wf["title"].startswith("[NR AIOps → DT]")
        assert len(wf["tasks"]) == 2

    def test_decisions_captured_as_notes(self):
        r = AIOpsTransformer().transform({
            "decisions": [{"name": "correlate-db-errors",
                           "expression": "host == target AND errorClass == db"}],
        })
        assert len(r.decisions_notes) == 1
        assert "replaces" in r.decisions_notes[0].lower()
        assert any("Davis" in w for w in r.warnings)

    def test_anomaly_setting_emits_detector(self):
        r = AIOpsTransformer().transform({
            "anomalyDetectionSettings": [{
                "name": "web-errors", "metricKey": "builtin:service.errors.total.rate",
                "sensitivity": 4.5,
            }],
        })
        det = r.anomaly_detectors[0]
        assert det["value"]["strategy"]["type"] == "AUTO_ADAPTIVE_BASELINE"
        assert det["value"]["strategy"]["sensitivity"] == 4.5

    def test_empty_workflow_warns(self):
        r = AIOpsTransformer().transform({
            "workflows": [{"name": "empty"}],
        })
        assert any("empty shell" in w for w in r.warnings)


# ---------------------------------------------------------------------------
# VulnerabilityTransformer
# ---------------------------------------------------------------------------


class TestVulnerability:
    def test_severity_mapped(self):
        r = VulnerabilityTransformer().transform({
            "name": "prod", "minAlertSeverity": "critical",
        })
        assert r.success
        assert r.settings_envelope["value"]["minSeverity"] == "CRITICAL"

    def test_mute_list_becomes_muting_rules(self):
        r = VulnerabilityTransformer().transform({
            "name": "p", "muteList": [
                {"cve": "CVE-2024-1234", "reason": "accepted risk"},
                {"cve": "CVE-2024-5678"},
            ],
        })
        assert len(r.muting_rules) == 2
        assert r.muting_rules[0]["schemaId"] == "builtin:appsec.vulnerability-muting"
        assert r.muting_rules[0]["value"]["cve"] == "CVE-2024-1234"

    def test_license_policies_go_to_runbook(self):
        r = VulnerabilityTransformer().transform({
            "name": "p", "licensePolicies": ["no-gpl"],
            "blockedPackages": ["log4j:<2.17"],
        })
        assert r.runbook["license_policies"] == ["no-gpl"]
        assert any("build pipeline" in w or "license" in w.lower() for w in r.warnings)


# ---------------------------------------------------------------------------
# NPMTransformer
# ---------------------------------------------------------------------------


class TestNPM:
    def test_snmp_devices_envelopes(self):
        r = NPMTransformer().transform({
            "snmpDevices": [
                {"name": "switch-1", "ipAddress": "10.0.0.1", "community": "public"},
                {"name": "router-1", "ipAddress": "10.0.0.2"},
            ],
        })
        assert r.success and len(r.device_envelopes) == 2
        assert r.device_envelopes[0]["schemaId"] == "builtin:network.snmp-device"

    def test_community_secret_not_migrated(self):
        r = NPMTransformer().transform({
            "snmpDevices": [{"name": "s", "community": "public"}],
        })
        assert r.device_envelopes[0]["value"]["community"] == "<rotate-after-import>"
        assert any("community" in w for w in r.warnings)

    def test_netflow_envelope(self):
        r = NPMTransformer().transform({
            "netflow": {"enabled": True, "listenPort": 9995, "sourceSubnets": ["10.0.0.0/8"]},
        })
        assert r.netflow_envelope["value"]["listenPort"] == 9995


# ---------------------------------------------------------------------------
# AIMonitoringTransformer
# ---------------------------------------------------------------------------


class TestAIMonitoring:
    def test_models_become_envelopes(self):
        r = AIMonitoringTransformer().transform({
            "models": [
                {"name": "gpt-4", "provider": "openai", "modelId": "gpt-4",
                 "costPer1kInputTokens": 0.03, "costPer1kOutputTokens": 0.06},
            ],
        })
        assert r.success and len(r.model_envelopes) == 1
        assert r.model_envelopes[0]["schemaId"] == "builtin:ai.observability.model"

    def test_empty_models_warns_about_auto_discovery(self):
        r = AIMonitoringTransformer().transform({"providers": ["openai"]})
        assert any("auto-discover" in w for w in r.warnings)

    def test_inference_event_mapping_present(self):
        r = AIMonitoringTransformer().transform({"models": [{"name": "x"}]})
        assert "fetch bizevents" in r.inference_event_mapping
        assert "AI_INFERENCE" in r.inference_event_mapping


# ---------------------------------------------------------------------------
# PrometheusTransformer
# ---------------------------------------------------------------------------


class TestPrometheus:
    def test_scrape_targets_become_envelopes(self):
        r = PrometheusTransformer().transform({
            "mode": "scrape",
            "targets": [
                {"job": "api-metrics", "url": "http://api:9090/metrics",
                 "scrapeIntervalSeconds": 30},
            ],
        })
        assert r.success and len(r.scrape_envelopes) == 1
        assert r.scrape_envelopes[0]["schemaId"] == "builtin:prometheus.exporter"
        assert r.scrape_envelopes[0]["value"]["scrapeIntervalSeconds"] == 30

    def test_relabel_configs_become_filters(self):
        r = PrometheusTransformer().transform({
            "mode": "scrape",
            "targets": [{"job": "j", "url": "http://x:9090/metrics"}],
            "relabelConfigs": [
                {"action": "drop", "regex": "go_.*", "sourceLabels": ["__name__"]},
            ],
        })
        filters = r.scrape_envelopes[0]["value"]["metricFilters"]
        assert filters[0]["action"] == "drop"
        assert filters[0]["regex"] == "go_.*"

    def test_remote_write_mode_emits_otlp_envelope(self):
        r = PrometheusTransformer().transform({"mode": "remote_write"})
        assert r.remote_write_envelope["schemaId"] == "builtin:otel.ingest.prometheus"
        assert "otlp" in r.remote_write_envelope["value"]["endpoint"]
        assert any("token" in w.lower() for w in r.warnings)

    def test_runbook_includes_nri_uninstall(self):
        r = PrometheusTransformer().transform({"mode": "scrape"})
        assert any("newrelic-prometheus-agent" in s for s in r.runbook["nri_prometheus_uninstall"])
