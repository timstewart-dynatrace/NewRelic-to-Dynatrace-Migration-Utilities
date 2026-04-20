"""Tests for Phase 16 modules: Lambda, Browser RUM, Mobile RUM, agents,
custom-instrumentation translator."""

from click.testing import CliRunner

from agents import (
    SUPPORTED_LANGUAGES,
    DotNetAgent,
    GoAgent,
    JavaAgent,
    NodeAgent,
    PHPAgent,
    PythonAgent,
    RubyAgent,
)
from transformers import (
    BrowserRUMTransformer,
    CustomInstrumentationTranslator,
    LambdaTransformer,
    MobileRUMTransformer,
)

# ---------------------------------------------------------------------------
# LambdaTransformer
# ---------------------------------------------------------------------------


class TestLambdaTransformer:
    def test_nodejs_lambda_maps_to_dynatrace_layer(self):
        r = LambdaTransformer().transform({
            "name": "checkout",
            "region": "us-west-2",
            "runtime": "nodejs20.x",
            "arch": "x86_64",
        })
        assert r.success
        assert r.settings_envelopes[0]["schemaId"] == "builtin:cloud.aws"
        assert "Dynatrace_OneAgent_Nodejs" in r.runbook["layer_arn_template"]
        assert "us-west-2" in r.runbook["layer_arn_template"]

    def test_python_arm_maps_to_arm64_layer(self):
        r = LambdaTransformer().transform({
            "name": "worker", "region": "eu-west-1",
            "runtime": "python3.11", "arch": "arm64",
        })
        assert "Dynatrace_OneAgent_Python_ARM64" in r.runbook["layer_arn_template"]

    def test_unknown_runtime_warns_and_falls_back(self):
        r = LambdaTransformer().transform({
            "name": "odd", "region": "us-east-1", "runtime": "rust-custom",
        })
        assert r.success
        assert any("no direct Dynatrace layer" in w for w in r.warnings)

    def test_env_vars_include_auth(self):
        r = LambdaTransformer().transform({
            "name": "x", "region": "us-east-1", "runtime": "nodejs20.x",
        })
        env = r.runbook["env_vars_to_set"]
        assert "DT_TENANT" in env and "DT_CONNECTION_AUTH_TOKEN" in env

    def test_batch(self):
        rs = LambdaTransformer().transform_all([
            {"name": "a", "region": "us-east-1", "runtime": "nodejs20.x"},
            {"name": "b", "region": "us-east-1", "runtime": "python3.12"},
        ])
        assert len(rs) == 2 and all(r.success for r in rs)


# ---------------------------------------------------------------------------
# BrowserRUMTransformer
# ---------------------------------------------------------------------------


class TestBrowserRUMTransformer:
    def test_simple_app_emits_settings_envelope(self):
        r = BrowserRUMTransformer().transform({
            "name": "web-prod", "domain": "example.com",
        })
        assert r.success
        assert r.app_config["schemaId"] == "builtin:rum.web.app-config"
        assert r.app_config["value"]["type"] == "MPA"
        assert r.app_config["value"]["injection"]["mode"] == "AUTO"

    def test_spa_flag_preserved(self):
        r = BrowserRUMTransformer().transform({"name": "spa-app", "isSpa": True})
        assert r.app_config["value"]["type"] == "SPA"

    def test_session_replay_warns(self):
        r = BrowserRUMTransformer().transform({
            "name": "srep", "sessionReplayEnabled": True,
        })
        assert any("Session Replay" in w for w in r.warnings)

    def test_runbook_maps_browser_events(self):
        r = BrowserRUMTransformer().transform({"name": "x"})
        assert "PageView" in r.runbook["nr_event_to_dql"]
        assert "JavaScriptError" in r.runbook["nr_event_to_dql"]

    def test_runbook_lists_core_web_vitals(self):
        r = BrowserRUMTransformer().transform({"name": "x"})
        vitals = r.runbook["core_web_vitals"]
        assert vitals["largestContentfulPaint"] == "builtin:apps.web.largestContentfulPaint"
        assert vitals["cumulativeLayoutShift"] == "builtin:apps.web.cumulativeLayoutShift"


# ---------------------------------------------------------------------------
# MobileRUMTransformer
# ---------------------------------------------------------------------------


class TestMobileRUMTransformer:
    def test_android_app_maps_to_mobile_settings(self):
        r = MobileRUMTransformer().transform({
            "name": "Shop", "platform": "android",
            "packageName": "com.example.shop",
        })
        assert r.success
        assert r.app_config["schemaId"] == "builtin:mobile-application"
        assert r.app_config["value"]["platform"] == "ANDROID"
        assert "agent-android" in r.runbook["sdk_swap"]["dt_sdk"]

    def test_ios_app_maps_dsym_guidance(self):
        r = MobileRUMTransformer().transform({
            "name": "iShop", "platform": "ios", "bundleId": "com.ex.ishop",
        })
        assert "dSYM" in r.runbook["sdk_swap"]["symbolication"]

    def test_unknown_platform_warns(self):
        r = MobileRUMTransformer().transform({
            "name": "weird", "platform": "blackberry",
        })
        assert any("Unknown mobile platform" in w for w in r.warnings)

    def test_react_native_supported(self):
        r = MobileRUMTransformer().transform({
            "name": "rn-shop", "platform": "react-native",
        })
        assert "@dynatrace/react-native-plugin" in r.runbook["sdk_swap"]["dt_sdk"]

    def test_runbook_maps_mobile_events(self):
        r = MobileRUMTransformer().transform({"name": "x", "platform": "android"})
        events = r.runbook["nr_event_to_dql"]
        assert "MobileSession" in events
        assert "MobileCrash" in events


# ---------------------------------------------------------------------------
# Agents orchestrator
# ---------------------------------------------------------------------------


class TestAgents:
    def test_supported_languages_complete(self):
        assert set(SUPPORTED_LANGUAGES) == {
            "java", "dotnet", "nodejs", "python", "ruby", "php", "go",
        }

    def test_java_uninstall_plan_has_actions(self):
        r = JavaAgent().uninstall_nr({"name": "h1"})
        assert r.success and len(r.plan.actions) >= 3
        assert all(a.id.startswith("uninstall_nr.java.") for a in r.plan.actions)

    def test_dotnet_has_iis_handling(self):
        r = DotNetAgent().uninstall_nr({"name": "h1"})
        assert any("iis" in a.command.lower() for a in r.plan.actions)

    def test_nodejs_removes_npm_and_require(self):
        r = NodeAgent().uninstall_nr({"name": "h1"})
        cmds = " ".join(a.command for a in r.plan.actions)
        assert "newrelic" in cmds and "npm" in cmds

    def test_python_removes_admin_wrapper(self):
        r = PythonAgent().uninstall_nr({"name": "h1"})
        cmds = " ".join(a.description for a in r.plan.actions)
        assert "newrelic-admin" in cmds

    def test_ruby_removes_gem(self):
        r = RubyAgent().uninstall_nr({"name": "h1"})
        cmds = " ".join(a.command for a in r.plan.actions)
        assert "newrelic_rpm" in cmds or "Gemfile" in cmds

    def test_php_removes_daemon(self):
        r = PHPAgent().uninstall_nr({"name": "h1"})
        cmds = " ".join(a.command for a in r.plan.actions)
        assert "newrelic-daemon" in cmds

    def test_go_oneagent_returns_not_supported(self):
        r = GoAgent().install_oneagent({"name": "h1"})
        assert not r.success
        assert any("does not auto-instrument Go" in w for w in r.warnings)

    def test_go_otel_fallback_works(self):
        r = GoAgent().install_otel_fallback({"name": "h1"})
        assert r.success and len(r.plan.actions) >= 3

    def test_verify_returns_plan(self):
        for Agent in (JavaAgent, PythonAgent, NodeAgent, RubyAgent, PHPAgent, DotNetAgent):
            r = Agent().verify({"name": "h1"})
            assert r.success
            assert r.plan.phase == "verify"


# ---------------------------------------------------------------------------
# CustomInstrumentationTranslator
# ---------------------------------------------------------------------------


class TestCustomInstrumentation:
    def test_javascript_custom_event(self):
        t = CustomInstrumentationTranslator()
        r = t.scan_text(
            "newrelic.recordCustomEvent('Signup', { plan: 'pro' });",
            "a.js",
        )
        assert len(r.suggestions) == 1
        s = r.suggestions[0]
        assert s.api_category == "custom_event"
        assert s.confidence == "HIGH"
        assert "bizevents/ingest" in s.replacement

    def test_javascript_error(self):
        t = CustomInstrumentationTranslator()
        r = t.scan_text("newrelic.noticeError(err);", "a.js")
        assert r.suggestions[0].api_category == "error"
        assert "recordException" in r.suggestions[0].replacement

    def test_python_custom_attribute(self):
        t = CustomInstrumentationTranslator()
        r = t.scan_text(
            "newrelic.agent.add_custom_attribute('user.id', uid)",
            "app.py",
        )
        assert r.suggestions[0].api_category == "custom_attribute"
        assert "oneagent" in r.suggestions[0].replacement

    def test_python_metric(self):
        t = CustomInstrumentationTranslator()
        r = t.scan_text(
            "newrelic.agent.record_custom_metric('Checkout/Count', 1)",
            "app.py",
        )
        assert r.suggestions[0].api_category == "metric"
        assert "get_meter" in r.suggestions[0].replacement

    def test_java_custom_attribute_and_error(self):
        t = CustomInstrumentationTranslator()
        r = t.scan_text(
            'NewRelic.addCustomParameter("orderId", oid);\n'
            "NewRelic.noticeError(ex);",
            "Foo.java",
        )
        cats = {s.api_category for s in r.suggestions}
        assert cats == {"custom_attribute", "error"}

    def test_language_detection_from_suffix(self):
        t = CustomInstrumentationTranslator()
        assert t.detect_language("foo.ts") == "javascript"
        assert t.detect_language("foo.py") == "python"
        assert t.detect_language("Foo.java") == "java"
        assert t.detect_language("foo.rs") is None

    def test_diff_renders_original_and_replacement(self):
        t = CustomInstrumentationTranslator()
        r = t.scan_text(
            "newrelic.noticeError(e);",
            "a.js",
        )
        diff = t.render_diff(r)
        assert "a.js" in diff and "- newrelic.noticeError" in diff

    def test_confidence_low_for_txn_name(self):
        t = CustomInstrumentationTranslator()
        r = t.scan_text("newrelic.setTransactionName('/api/x');", "a.js")
        assert r.suggestions[0].confidence == "LOW"

    def test_unknown_language_warns_not_errors(self):
        t = CustomInstrumentationTranslator()
        r = t.scan_text("newrelic.noticeError(err);", "a.rs")
        assert r.success and len(r.suggestions) == 0
        assert any("Unknown language" in w for w in r.warnings)


# ---------------------------------------------------------------------------
# CLI smoke
# ---------------------------------------------------------------------------


class TestPhase16CLI:
    def test_agents_subcommand_java_dry_run(self):
        import migrate as migrate_mod
        runner = CliRunner()
        result = runner.invoke(
            migrate_mod.agents_cmd,
            ["--language", "java", "--dry-run"],
        )
        assert result.exit_code == 0, result.output
        assert "uninstall_nr.java" in result.output

    def test_scan_instrumentation_subcommand(self, tmp_path):
        import migrate as migrate_mod
        src = tmp_path / "a.js"
        src.write_text("newrelic.noticeError(err);")
        runner = CliRunner()
        result = runner.invoke(
            migrate_mod.scan_instrumentation_cmd,
            ["--file", str(src)],
        )
        assert result.exit_code == 0, result.output
        assert "recordException" in result.output
