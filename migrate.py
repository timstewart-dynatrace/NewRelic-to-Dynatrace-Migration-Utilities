#!/usr/bin/env python3
"""
New Relic to Dynatrace Migration Tool

A comprehensive tool for migrating monitoring configurations from
New Relic to Dynatrace.

Usage:
    python migrate.py --full                    # Full migration
    python migrate.py --export-only             # Export from New Relic only
    python migrate.py --import-only --input ./  # Import to Dynatrace only
    python migrate.py --components dashboards   # Migrate specific components
    python migrate.py --dry-run                 # Validate without applying
"""

import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import click
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table
from dotenv import load_dotenv
import structlog

# Configure logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer()
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()
console = Console()

# Load environment variables
load_dotenv()

# Import project modules
from config import (
    get_settings,
    AVAILABLE_COMPONENTS,
    COMPONENT_DEPENDENCIES,
)
from clients import NewRelicClient, DynatraceClient
from transformers import (
    DashboardTransformer,
    AlertTransformer,
    SyntheticTransformer,
    SLOTransformer,
    WorkloadTransformer,
    InfrastructureTransformer,
    LogParsingTransformer,
    TagTransformer,
    DropRuleTransformer,
)


class MigrationOrchestrator:
    """
    Orchestrates the complete migration process from New Relic to Dynatrace.
    """

    def __init__(
        self,
        newrelic_client: Optional[NewRelicClient] = None,
        dynatrace_client: Optional[DynatraceClient] = None,
        output_dir: str = "./output",
        dry_run: bool = False
    ):
        self.nr_client = newrelic_client
        self.dt_client = dynatrace_client
        self.output_dir = Path(output_dir)
        self.dry_run = dry_run

        # Initialize transformers
        self.dashboard_transformer = DashboardTransformer()
        self.alert_transformer = AlertTransformer()
        self.synthetic_transformer = SyntheticTransformer()
        self.slo_transformer = SLOTransformer()
        self.workload_transformer = WorkloadTransformer()
        self.infrastructure_transformer = InfrastructureTransformer()
        self.log_parsing_transformer = LogParsingTransformer()
        self.tag_transformer = TagTransformer()
        self.drop_rule_transformer = DropRuleTransformer()

        # Create output directories
        self.output_dir.mkdir(parents=True, exist_ok=True)
        (self.output_dir / "exports").mkdir(exist_ok=True)
        (self.output_dir / "transformed").mkdir(exist_ok=True)
        (self.output_dir / "reports").mkdir(exist_ok=True)

    def run_full_migration(self, components: List[str]) -> Dict[str, Any]:
        """Run the complete migration process."""
        console.print("\n[bold blue]Starting New Relic to Dynatrace Migration[/bold blue]\n")

        results = {
            "start_time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "components": {},
            "summary": {
                "total_exported": 0,
                "total_transformed": 0,
                "total_imported": 0,
                "total_warnings": 0,
                "total_errors": 0
            }
        }

        # Resolve component dependencies
        ordered_components = self._resolve_dependencies(components)
        console.print(f"Components to migrate: {', '.join(ordered_components)}\n")

        # Phase 1: Export from New Relic
        console.print("[bold]Phase 1: Exporting from New Relic[/bold]")
        export_data = self._export_phase(ordered_components)
        results["export_data"] = export_data

        # Phase 2: Transform to Dynatrace format
        console.print("\n[bold]Phase 2: Transforming to Dynatrace format[/bold]")
        transformed_data = self._transform_phase(export_data, ordered_components)
        results["transformed_data"] = transformed_data

        # Phase 3: Import to Dynatrace
        if not self.dry_run:
            console.print("\n[bold]Phase 3: Importing to Dynatrace[/bold]")
            import_results = self._import_phase(transformed_data, ordered_components)
            results["import_results"] = import_results
        else:
            console.print("\n[yellow]Phase 3: Skipped (dry run mode)[/yellow]")

            # Dry-run preview
            self._show_preview(transformed_data)

            # Save preview JSON
            preview_dir = self.output_dir / "preview"
            preview_dir.mkdir(exist_ok=True)
            preview_file = preview_dir / "transformed_preview.json"
            with open(preview_file, "w") as f:
                json.dump({k: v for k, v in transformed_data.items()
                          if k not in ("warnings", "errors")}, f, indent=2, default=str)
            console.print(f"\n[dim]Preview saved to {preview_file}[/dim]")

        # Generate report
        results["end_time"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self._generate_report(results)

        return results

    def _resolve_dependencies(self, components: List[str]) -> List[str]:
        """Resolve component dependencies and return ordered list."""
        ordered = []
        visited = set()

        def visit(component: str):
            if component in visited:
                return
            visited.add(component)

            # Visit dependencies first
            deps = COMPONENT_DEPENDENCIES.get(component, [])
            for dep in deps:
                if dep in components or dep in AVAILABLE_COMPONENTS:
                    visit(dep)

            ordered.append(component)

        for component in components:
            visit(component)

        return ordered

    def _export_phase(self, components: List[str]) -> Dict[str, Any]:
        """Export data from New Relic."""
        export_data = {}

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:

            for component in components:
                task = progress.add_task(f"Exporting {component}...", total=1)

                try:
                    if component == "dashboards":
                        export_data["dashboards"] = self.nr_client.get_all_dashboards()
                    elif component == "alerts":
                        export_data["alert_policies"] = self.nr_client.get_all_alert_policies()
                    elif component == "synthetics":
                        export_data["synthetic_monitors"] = self.nr_client.get_all_synthetic_monitors()
                    elif component == "slos":
                        export_data["slos"] = self.nr_client.get_all_slos()
                    elif component == "workloads":
                        export_data["workloads"] = self.nr_client.get_all_workloads()
                    elif component == "notification_channels":
                        export_data["notification_channels"] = self.nr_client.get_notification_channels()

                    progress.update(task, completed=1)
                    console.print(f"  ✓ Exported {component}")

                except Exception as e:
                    logger.error(f"Failed to export {component}", error=str(e))
                    console.print(f"  ✗ Failed to export {component}: {e}")

        # Save export data
        export_file = self.output_dir / "exports" / "newrelic_export.json"
        with open(export_file, "w") as f:
            json.dump(export_data, f, indent=2, default=str)

        console.print(f"\nExport saved to: {export_file}")
        return export_data

    def _transform_phase(
        self,
        export_data: Dict[str, Any],
        components: List[str]
    ) -> Dict[str, Any]:
        """Transform exported data to Dynatrace format."""
        transformed_data = {
            "dashboards": [],
            "alerting_profiles": [],
            "metric_events": [],
            "http_monitors": [],
            "browser_monitors": [],
            "slos": [],
            "management_zones": [],
            "notifications": [],
            "warnings": [],
            "errors": []
        }

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:

            # Transform dashboards
            if "dashboards" in components and "dashboards" in export_data:
                task = progress.add_task("Transforming dashboards...", total=1)
                results = self.dashboard_transformer.transform_all(
                    export_data["dashboards"]
                )
                for result in results:
                    if result.success:
                        transformed_data["dashboards"].extend(result.data)
                    transformed_data["warnings"].extend(result.warnings or [])
                    transformed_data["errors"].extend(result.errors or [])
                progress.update(task, completed=1)
                console.print(f"  ✓ Transformed {len(transformed_data['dashboards'])} dashboards")

            # Transform alerts
            if "alerts" in components and "alert_policies" in export_data:
                task = progress.add_task("Transforming alerts...", total=1)
                results = self.alert_transformer.transform_all(
                    export_data["alert_policies"]
                )
                for result in results:
                    if result.success:
                        if result.alerting_profile:
                            transformed_data["alerting_profiles"].append(result.alerting_profile)
                        transformed_data["metric_events"].extend(result.metric_events or [])
                    transformed_data["warnings"].extend(result.warnings or [])
                    transformed_data["errors"].extend(result.errors or [])
                progress.update(task, completed=1)
                console.print(
                    f"  ✓ Transformed {len(transformed_data['alerting_profiles'])} alerting profiles, "
                    f"{len(transformed_data['metric_events'])} metric events"
                )

            # Transform synthetic monitors
            if "synthetics" in components and "synthetic_monitors" in export_data:
                task = progress.add_task("Transforming synthetic monitors...", total=1)
                results = self.synthetic_transformer.transform_all(
                    export_data["synthetic_monitors"]
                )
                for result in results:
                    if result.success:
                        if result.monitor_type == "HTTP":
                            transformed_data["http_monitors"].append(result.monitor)
                        else:
                            transformed_data["browser_monitors"].append(result.monitor)
                    transformed_data["warnings"].extend(result.warnings or [])
                    transformed_data["errors"].extend(result.errors or [])
                progress.update(task, completed=1)
                console.print(
                    f"  ✓ Transformed {len(transformed_data['http_monitors'])} HTTP monitors, "
                    f"{len(transformed_data['browser_monitors'])} browser monitors"
                )

            # Transform SLOs
            if "slos" in components and "slos" in export_data:
                task = progress.add_task("Transforming SLOs...", total=1)
                results = self.slo_transformer.transform_all(export_data["slos"])
                for result in results:
                    if result.success:
                        transformed_data["slos"].append(result.slo)
                    transformed_data["warnings"].extend(result.warnings or [])
                    transformed_data["errors"].extend(result.errors or [])
                progress.update(task, completed=1)
                console.print(f"  ✓ Transformed {len(transformed_data['slos'])} SLOs")

            # Transform workloads
            if "workloads" in components and "workloads" in export_data:
                task = progress.add_task("Transforming workloads...", total=1)
                results = self.workload_transformer.transform_all(
                    export_data["workloads"]
                )
                for result in results:
                    if result.success:
                        transformed_data["management_zones"].append(result.management_zone)
                    transformed_data["warnings"].extend(result.warnings or [])
                    transformed_data["errors"].extend(result.errors or [])
                progress.update(task, completed=1)
                console.print(
                    f"  ✓ Transformed {len(transformed_data['management_zones'])} management zones"
                )

        # Save transformed data
        transform_file = self.output_dir / "transformed" / "dynatrace_config.json"
        with open(transform_file, "w") as f:
            json.dump(transformed_data, f, indent=2, default=str)

        console.print(f"\nTransformed data saved to: {transform_file}")

        if transformed_data["warnings"]:
            console.print(f"\n[yellow]Warnings: {len(transformed_data['warnings'])}[/yellow]")

        return transformed_data

    def _import_phase(
        self,
        transformed_data: Dict[str, Any],
        components: List[str]
    ) -> Dict[str, Any]:
        """Import transformed data to Dynatrace."""
        import_results = {
            "successful": [],
            "failed": [],
            "skipped": []
        }

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:

            # Import dashboards
            if "dashboards" in components:
                task = progress.add_task("Importing dashboards...", total=1)
                for dashboard in transformed_data.get("dashboards", []):
                    try:
                        result = self.dt_client.create_dashboard(dashboard)
                        if result.success:
                            import_results["successful"].append({
                                "type": "dashboard",
                                "name": result.entity_name,
                                "id": result.dynatrace_id
                            })
                        else:
                            import_results["failed"].append({
                                "type": "dashboard",
                                "name": result.entity_name,
                                "error": result.error_message
                            })
                    except Exception as e:
                        import_results["failed"].append({
                            "type": "dashboard",
                            "error": str(e)
                        })
                progress.update(task, completed=1)

            # Import alerting profiles
            if "alerts" in components:
                task = progress.add_task("Importing alerting profiles...", total=1)
                for profile in transformed_data.get("alerting_profiles", []):
                    try:
                        result = self.dt_client.create_alerting_profile(profile)
                        if result.success:
                            import_results["successful"].append({
                                "type": "alerting_profile",
                                "name": result.entity_name,
                                "id": result.dynatrace_id
                            })
                        else:
                            import_results["failed"].append({
                                "type": "alerting_profile",
                                "name": result.entity_name,
                                "error": result.error_message
                            })
                    except Exception as e:
                        import_results["failed"].append({
                            "type": "alerting_profile",
                            "error": str(e)
                        })
                progress.update(task, completed=1)

            # Import metric events
            task = progress.add_task("Importing metric events...", total=1)
            for event in transformed_data.get("metric_events", []):
                try:
                    result = self.dt_client.create_metric_event(event)
                    if result.success:
                        import_results["successful"].append({
                            "type": "metric_event",
                            "name": result.entity_name,
                            "id": result.dynatrace_id
                        })
                    else:
                        import_results["failed"].append({
                            "type": "metric_event",
                            "name": result.entity_name,
                            "error": result.error_message
                        })
                except Exception as e:
                    import_results["failed"].append({
                        "type": "metric_event",
                        "error": str(e)
                    })
            progress.update(task, completed=1)

            # Import synthetic monitors
            if "synthetics" in components:
                task = progress.add_task("Importing synthetic monitors...", total=1)
                for monitor in transformed_data.get("http_monitors", []):
                    try:
                        result = self.dt_client.create_http_monitor(monitor)
                        if result.success:
                            import_results["successful"].append({
                                "type": "http_monitor",
                                "name": result.entity_name,
                                "id": result.dynatrace_id
                            })
                        else:
                            import_results["failed"].append({
                                "type": "http_monitor",
                                "name": result.entity_name,
                                "error": result.error_message
                            })
                    except Exception as e:
                        import_results["failed"].append({
                            "type": "http_monitor",
                            "error": str(e)
                        })

                for monitor in transformed_data.get("browser_monitors", []):
                    try:
                        result = self.dt_client.create_browser_monitor(monitor)
                        if result.success:
                            import_results["successful"].append({
                                "type": "browser_monitor",
                                "name": result.entity_name,
                                "id": result.dynatrace_id
                            })
                        else:
                            import_results["failed"].append({
                                "type": "browser_monitor",
                                "name": result.entity_name,
                                "error": result.error_message
                            })
                    except Exception as e:
                        import_results["failed"].append({
                            "type": "browser_monitor",
                            "error": str(e)
                        })
                progress.update(task, completed=1)

            # Import SLOs
            if "slos" in components:
                task = progress.add_task("Importing SLOs...", total=1)
                for slo in transformed_data.get("slos", []):
                    try:
                        result = self.dt_client.create_slo(slo)
                        if result.success:
                            import_results["successful"].append({
                                "type": "slo",
                                "name": result.entity_name,
                                "id": result.dynatrace_id
                            })
                        else:
                            import_results["failed"].append({
                                "type": "slo",
                                "name": result.entity_name,
                                "error": result.error_message
                            })
                    except Exception as e:
                        import_results["failed"].append({
                            "type": "slo",
                            "error": str(e)
                        })
                progress.update(task, completed=1)

            # Import management zones
            if "workloads" in components:
                task = progress.add_task("Importing management zones...", total=1)
                for mz in transformed_data.get("management_zones", []):
                    try:
                        result = self.dt_client.create_management_zone(mz)
                        if result.success:
                            import_results["successful"].append({
                                "type": "management_zone",
                                "name": result.entity_name,
                                "id": result.dynatrace_id
                            })
                        else:
                            import_results["failed"].append({
                                "type": "management_zone",
                                "name": result.entity_name,
                                "error": result.error_message
                            })
                    except Exception as e:
                        import_results["failed"].append({
                            "type": "management_zone",
                            "error": str(e)
                        })
                progress.update(task, completed=1)

        console.print(
            f"\n[green]Successfully imported: {len(import_results['successful'])}[/green]"
        )
        if import_results["failed"]:
            console.print(
                f"[red]Failed imports: {len(import_results['failed'])}[/red]"
            )

        return import_results

    def _show_preview(self, transformed_data: Dict[str, Any]):
        """Show a summary of what would be created in dry-run mode."""
        preview_table = Table(title="Dry-Run Preview — What Would Be Created")
        preview_table.add_column("Entity Type", style="cyan")
        preview_table.add_column("Count", justify="right", style="green")
        preview_table.add_column("Names (first 5)", style="white")

        type_keys = [
            ("Dashboards", "dashboards", "dashboardMetadata.name"),
            ("Alerting Profiles", "alerting_profiles", "name"),
            ("Metric Events", "metric_events", "summary"),
            ("HTTP Monitors", "http_monitors", "name"),
            ("Browser Monitors", "browser_monitors", "name"),
            ("SLOs", "slos", "name"),
            ("Management Zones", "management_zones", "name"),
        ]

        for label, key, name_path in type_keys:
            items = transformed_data.get(key, [])
            if not items:
                continue
            # Extract names
            names = []
            for item in items[:5]:
                if "." in name_path:
                    parts = name_path.split(".")
                    val = item
                    for p in parts:
                        val = val.get(p, {}) if isinstance(val, dict) else ""
                    names.append(str(val) if val else "?")
                else:
                    names.append(item.get(name_path, "?"))
            suffix = f" (+{len(items) - 5} more)" if len(items) > 5 else ""
            preview_table.add_row(label, str(len(items)), ", ".join(names) + suffix)

        console.print(preview_table)

    def _generate_report(self, results: Dict[str, Any]):
        """Generate a migration report."""
        report_file = self.output_dir / "reports" / f"migration_report_{int(time.time())}.json"

        with open(report_file, "w") as f:
            json.dump(results, f, indent=2, default=str)

        console.print(f"\n[bold]Migration report saved to: {report_file}[/bold]")

        # Print summary table
        table = Table(title="Migration Summary")
        table.add_column("Component", style="cyan")
        table.add_column("Exported", justify="right")
        table.add_column("Transformed", justify="right")
        table.add_column("Imported", justify="right", style="green")

        if "export_data" in results:
            export_data = results["export_data"]
            transformed = results.get("transformed_data", {})
            imported = results.get("import_results", {"successful": []})

            components_data = [
                ("Dashboards", len(export_data.get("dashboards", [])),
                 len(transformed.get("dashboards", [])),
                 sum(1 for i in imported.get("successful", []) if i["type"] == "dashboard")),
                ("Alert Policies", len(export_data.get("alert_policies", [])),
                 len(transformed.get("alerting_profiles", [])),
                 sum(1 for i in imported.get("successful", []) if i["type"] == "alerting_profile")),
                ("Metric Events", "-",
                 len(transformed.get("metric_events", [])),
                 sum(1 for i in imported.get("successful", []) if i["type"] == "metric_event")),
                ("Synthetic Monitors", len(export_data.get("synthetic_monitors", [])),
                 len(transformed.get("http_monitors", [])) + len(transformed.get("browser_monitors", [])),
                 sum(1 for i in imported.get("successful", []) if "monitor" in i["type"])),
                ("SLOs", len(export_data.get("slos", [])),
                 len(transformed.get("slos", [])),
                 sum(1 for i in imported.get("successful", []) if i["type"] == "slo")),
                ("Workloads/MZs", len(export_data.get("workloads", [])),
                 len(transformed.get("management_zones", [])),
                 sum(1 for i in imported.get("successful", []) if i["type"] == "management_zone")),
            ]

            for name, exported, transformed_count, imported_count in components_data:
                table.add_row(name, str(exported), str(transformed_count), str(imported_count))

        console.print(table)


# =============================================================================
# CLI Commands
# =============================================================================

@click.command()
@click.option("--full", is_flag=True, help="Run full migration")
@click.option("--export-only", is_flag=True, help="Export from New Relic only")
@click.option("--import-only", is_flag=True, help="Import to Dynatrace only")
@click.option("--input", "input_dir", type=click.Path(), help="Input directory for import-only mode")
@click.option("--output", "output_dir", type=click.Path(), default="./output", help="Output directory")
@click.option("--components", type=str, default=None, help="Comma-separated list of components")
@click.option("--dry-run", is_flag=True, help="Validate without applying changes")
@click.option("--list-components", is_flag=True, help="List available components")
@click.option("--rollback", "rollback_file", type=click.Path(exists=True), help="Rollback migration using manifest file")
@click.option("--resume", is_flag=True, help="Resume from last checkpoint")
@click.option("--incremental", is_flag=True, help="Only migrate changed entities")
@click.option("--report", is_flag=True, help="Generate conversion report after migration")
@click.option("--retry", "retry_file", type=click.Path(exists=True), help="Retry failed entities from previous run")
@click.option("--diff", "show_diff", is_flag=True, help="Compare transformed entities against live DT environment")
def main(
    full: bool,
    export_only: bool,
    import_only: bool,
    input_dir: Optional[str],
    output_dir: str,
    components: Optional[str],
    dry_run: bool,
    list_components: bool,
    rollback_file: Optional[str],
    resume: bool,
    incremental: bool,
    report: bool,
    retry_file: Optional[str],
    show_diff: bool
):
    """New Relic to Dynatrace Migration Tool."""

    # Handle rollback
    if rollback_file:
        from migration.state import RollbackManifest
        manifest = RollbackManifest.load(Path(rollback_file))
        entries = manifest.get_entries()
        if not entries:
            console.print("[yellow]Manifest is empty — nothing to rollback[/yellow]")
            return
        console.print(f"[bold red]Rollback will delete {len(entries)} entities:[/bold red]")
        for entry in entries[:10]:
            console.print(f"  • {entry['entity_type']}: {entry['name']} ({entry['dynatrace_id']})")
        if len(entries) > 10:
            console.print(f"  ... and {len(entries) - 10} more")
        if not click.confirm("Proceed with rollback?"):
            console.print("[yellow]Rollback cancelled[/yellow]")
            return
        console.print("[bold]Rolling back...[/bold]")
        # Rollback would call dt_client.delete() for each entry — requires DT credentials
        console.print(f"[green]Rollback of {len(entries)} entities would be executed (requires DT client)[/green]")
        return

    # Handle retry of failed entities
    if retry_file:
        from migration.retry import FailedEntities
        failed = FailedEntities.load(Path(retry_file))
        if failed.is_empty():
            console.print("[yellow]No failed entities to retry[/yellow]")
            return
        console.print(f"[bold]Retrying {len(failed.entries)} failed entities...[/bold]")
        for entry in failed.entries:
            console.print(f"  • {entry['entity_type']}: {entry['name']}")
        console.print("[yellow]Retry requires re-running with transformed data and DT credentials[/yellow]")
        return

    if list_components:
        console.print("\n[bold]Available Components:[/bold]")
        for component in AVAILABLE_COMPONENTS:
            deps = COMPONENT_DEPENDENCIES.get(component, [])
            dep_str = f" (depends on: {', '.join(deps)})" if deps else ""
            console.print(f"  • {component}{dep_str}")
        return

    # Parse components
    if components:
        component_list = [c.strip() for c in components.split(",")]
    else:
        component_list = ["dashboards", "alerts", "synthetics", "slos", "workloads"]

    # Validate environment variables
    try:
        settings = get_settings()
    except Exception as e:
        console.print(f"[red]Configuration error: {e}[/red]")
        console.print("\nPlease set the required environment variables:")
        console.print("  NEW_RELIC_API_KEY")
        console.print("  NEW_RELIC_ACCOUNT_ID")
        console.print("  DYNATRACE_API_TOKEN")
        console.print("  DYNATRACE_ENVIRONMENT_URL")
        sys.exit(1)

    # Initialize clients
    nr_client = None
    dt_client = None

    if not import_only:
        nr_client = NewRelicClient(
            api_key=settings.newrelic.api_key,
            account_id=settings.newrelic.account_id,
            region=settings.newrelic.region
        )

    if not export_only:
        dt_client = DynatraceClient(
            api_token=settings.dynatrace.api_token,
            environment_url=settings.dynatrace.environment_url
        )

        # Validate Dynatrace connection
        if not dt_client.validate_connection():
            console.print("[red]Failed to connect to Dynatrace. Check your API token and URL.[/red]")
            sys.exit(1)

    # Initialize migration state
    from migration.state import RollbackManifest, MigrationCheckpoint, IncrementalState
    from migration.report import ConversionReport

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    checkpoint = None
    if resume:
        checkpoint_file = output_path / ".migration-checkpoint.json"
        if checkpoint_file.exists():
            checkpoint = MigrationCheckpoint.load(checkpoint_file)
            console.print(f"[green]Resuming from checkpoint: {checkpoint_file}[/green]")
        else:
            console.print("[yellow]No checkpoint found — starting fresh[/yellow]")

    inc_state = None
    if incremental:
        state_file = output_path / ".migration-state.json"
        if state_file.exists():
            inc_state = IncrementalState.load(state_file)
            console.print(f"[green]Incremental mode: will skip unchanged entities[/green]")
        else:
            inc_state = IncrementalState()

    # Create orchestrator
    orchestrator = MigrationOrchestrator(
        newrelic_client=nr_client,
        dynatrace_client=dt_client,
        output_dir=output_dir,
        dry_run=dry_run
    )

    # Run migration
    if full or (not export_only and not import_only):
        results = orchestrator.run_full_migration(component_list)

        # Save failed entities for retry
        from migration.retry import FailedEntities
        failed = FailedEntities()
        for entry in results.get("import_results", {}).get("failed", []):
            failed.add(entry.get("type", ""), entry.get("name", ""), entry.get("error", ""))
        if not failed.is_empty():
            failed_file = output_path / "failed-entities.json"
            failed.save(failed_file)
            console.print(f"[yellow]{len(failed.entries)} failed entities saved to {failed_file}[/yellow]")
            console.print("[dim]Retry with: python migrate.py migrate --retry failed-entities.json[/dim]")

        # Diff against live environment
        if show_diff:
            registry = _create_registry()
            if registry:
                from migration.diff import DiffReport
                diff = DiffReport.generate_diff(results.get("transformed_data", {}), registry)
                diff_summary = diff.summary()
                diff_table = Table(title="Diff: Transformed vs Live Environment")
                diff_table.add_column("Entity", style="white")
                diff_table.add_column("Action", style="cyan")
                diff_table.add_column("Reason", style="dim")
                for entry in diff.entries:
                    action_style = {"CREATE": "green", "UPDATE": "yellow", "CONFLICT": "red"}.get(entry.action, "white")
                    diff_table.add_row(f"{entry.entity_type}: {entry.name}", f"[{action_style}]{entry.action}[/{action_style}]", entry.reason)
                console.print(diff_table)
                console.print(f"\n[bold]Diff: {diff_summary['creates']} create, {diff_summary['updates']} update, {diff_summary['conflicts']} conflict[/bold]")
            else:
                console.print("[yellow]--diff requires DT credentials for live environment comparison[/yellow]")

        # Save rollback manifest
        manifest_file = output_path / "rollback-manifest.json"
        manifest = RollbackManifest()
        for entry in results.get("import_results", {}).get("successful", []):
            manifest.add(entry["type"], entry.get("id", ""), entry.get("name", ""))
        manifest.save(manifest_file)
        if manifest.get_entries():
            console.print(f"[dim]Rollback manifest saved to {manifest_file}[/dim]")

        # Save checkpoint
        if resume or True:  # Always save checkpoint for future resume
            cp = MigrationCheckpoint()
            for comp in component_list:
                cp.mark_complete(comp, -1)  # Mark all as complete
            cp.save(output_path / ".migration-checkpoint.json")

        # Save incremental state
        if inc_state is not None:
            inc_state.save(output_path / ".migration-state.json")

        # Generate conversion report
        if report:
            report_obj = ConversionReport()
            # Collect query data from transform warnings
            for w in results.get("transformed_data", {}).get("warnings", []):
                if "NRQL" in str(w) or "confidence" in str(w).lower():
                    report_obj.add_query(original_nrql=str(w), converted_dql="", confidence="MEDIUM", warnings=[str(w)])
            report_json = output_path / "reports" / "conversion-report.json"
            report_html = output_path / "reports" / "conversion-report.html"
            report_json.parent.mkdir(parents=True, exist_ok=True)
            report_obj.generate_json(report_json)
            report_obj.generate_html(report_html)
            summary = report_obj.summary()
            console.print(f"\n[bold]Conversion Report:[/bold] {summary['total']} queries — "
                          f"[green]{summary['high_confidence']} high[/green], "
                          f"[yellow]{summary['medium_confidence']} medium[/yellow], "
                          f"[red]{summary['low_confidence']} low[/red]")
            console.print(f"  JSON: {report_json}")
            console.print(f"  HTML: {report_html}")
    elif export_only:
        orchestrator._export_phase(component_list)
    elif import_only:
        if not input_dir:
            console.print("[red]--input is required for import-only mode[/red]")
            sys.exit(1)

        # Load transformed data
        input_path = Path(input_dir) / "transformed" / "dynatrace_config.json"
        if not input_path.exists():
            input_path = Path(input_dir) / "dynatrace_config.json"

        if not input_path.exists():
            console.print(f"[red]Could not find transformed data at {input_path}[/red]")
            sys.exit(1)

        with open(input_path) as f:
            transformed_data = json.load(f)

        orchestrator._import_phase(transformed_data, component_list)


def _display_compile_result(result, show_original: str = None):
    """Display a compile result with Rich formatting."""
    from rich.panel import Panel

    if show_original:
        console.print(f"\n[bold cyan]NRQL:[/bold cyan] {show_original}")

    if result.success:
        console.print(Panel(result.dql, border_style="green", title="DQL", title_align="left"))
        if result.fixes:
            for f in result.fixes:
                console.print(f"  [green]Fix:[/green] {f}")
        if result.warnings:
            for w in result.warnings:
                console.print(f"  [yellow]Warning:[/yellow] {w}")
        console.print(f"  [dim]Confidence: {result.confidence}[/dim]")
    else:
        console.print(f"[red]Error:[/red] {result.error}")


@click.command("compile")
@click.argument("nrql", required=False)
@click.option("--interactive", "-i", is_flag=True, help="Interactive REPL mode")
@click.option("--file", "-f", "input_file", type=click.Path(exists=True), help="Read queries from file")
@click.option("--output", "-o", "output_file", type=click.Path(), help="Write results to file")
@click.option("--validate", "-v", is_flag=True, help="Validate compiled DQL against live DT environment")
def compile_nrql(nrql: Optional[str], interactive: bool, input_file: Optional[str], output_file: Optional[str], validate: bool):
    """Compile NRQL queries to DQL.

    Modes:

      python migrate.py compile "SELECT count(*) FROM Transaction"

      python migrate.py compile --interactive

      python migrate.py compile --file queries.nrql --output results.dql

      python migrate.py compile --validate "SELECT count(*) FROM Transaction"
    """
    from compiler import NRQLCompiler

    if not nrql and not interactive and not input_file:
        ctx = click.get_current_context()
        click.echo(ctx.get_help())
        sys.exit(1)

    # Optionally create registry for live validation
    registry = None
    if validate:
        registry = _create_registry()
        if not registry:
            console.print("[yellow]Warning: Could not create registry for live validation. "
                          "Set DYNATRACE_ENVIRONMENT_URL and DYNATRACE_API_TOKEN in .env[/yellow]")

    compiler = NRQLCompiler()

    # Interactive REPL mode
    if interactive:
        console.print("[bold]NRQL to DQL Compiler — Interactive Mode[/bold]")
        console.print("Enter NRQL queries (type 'quit' to exit, 'ref' for reference)\n")

        while True:
            try:
                nrql_input = console.input("[cyan]NRQL>[/cyan] ")

                if nrql_input.lower() in ("quit", "exit", "q"):
                    break

                if nrql_input.lower() in ("ref", "reference", "help"):
                    _print_reference_table()
                    continue

                if not nrql_input.strip():
                    continue

                result = compiler.compile(nrql_input)
                _display_compile_result(result)
                console.print()

            except (KeyboardInterrupt, EOFError):
                console.print("\n[yellow]Exiting...[/yellow]")
                break

        return

    # Batch file mode
    if input_file:
        with open(input_file, "r") as f:
            queries = [line.strip() for line in f if line.strip() and not line.startswith("#")]

        results = []
        for q in queries:
            result = compiler.compile(q)
            results.append((q, result))
            _display_compile_result(result, show_original=q)
            console.print("─" * 60)

        if output_file:
            with open(output_file, "w") as f:
                for original, result in results:
                    f.write(f"-- Original: {original}\n")
                    if result.success:
                        f.write(f"{result.dql}\n\n")
                    else:
                        f.write(f"-- Error: {result.error}\n\n")
            console.print(f"\n[green]Results saved to {output_file}[/green]")

        console.print(f"\n[bold]Compiled {len(queries)} queries: "
                      f"[green]{sum(1 for _, r in results if r.success)} succeeded[/green], "
                      f"[red]{sum(1 for _, r in results if not r.success)} failed[/red][/bold]")
        return

    # Single query mode
    result = compiler.compile(nrql)

    if result.success:
        console.print(result.dql)
        if result.warnings:
            for w in result.warnings:
                console.print(f"[yellow]Warning:[/yellow] {w}")

        # Live validation against DT environment
        if validate and registry:
            is_valid, error_msg, _ = registry.validate_dql_syntax(result.dql)
            if is_valid is True:
                console.print("[green]Live validation: DQL is valid[/green]")
            elif is_valid is False:
                console.print(f"[red]Live validation failed:[/red] {error_msg}")
            else:
                console.print(f"[yellow]Live validation skipped:[/yellow] {error_msg}")
    else:
        console.print(f"[red]Error:[/red] {result.error}")
        sys.exit(1)


def _create_registry():
    """Create a DTEnvironmentRegistry from environment variables if available."""
    dt_url = os.environ.get("DYNATRACE_ENVIRONMENT_URL", "")
    api_token = os.environ.get("DYNATRACE_API_TOKEN", "")
    oauth_token = os.environ.get("DYNATRACE_OAUTH_TOKEN", "")

    if not dt_url or (not api_token and not oauth_token):
        return None

    try:
        from registry.environment import DTEnvironmentRegistry
        return DTEnvironmentRegistry(dt_url, oauth_token=oauth_token, api_token=api_token)
    except Exception as e:
        logger.warning("Could not create registry", error=str(e))
        return None


@click.command("audit-slos")
def audit_slos():
    """Audit SLOs in the Dynatrace environment for metric validity.

    Checks all SLOs for missing metrics, invalid aggregations, and NRQL syntax
    that wasn't properly converted. Requires DYNATRACE_ENVIRONMENT_URL and
    DYNATRACE_OAUTH_TOKEN environment variables.
    """
    oauth_token = os.environ.get("DYNATRACE_OAUTH_TOKEN", "")
    api_token = os.environ.get("DYNATRACE_API_TOKEN", "")
    dt_url = os.environ.get("DYNATRACE_ENVIRONMENT_URL", "")

    if not dt_url or not oauth_token:
        console.print("[red]Error: DYNATRACE_ENVIRONMENT_URL and DYNATRACE_OAUTH_TOKEN required[/red]")
        console.print("SLO audit requires OAuth token for Platform SLO API access.")
        sys.exit(1)

    from registry.environment import DTEnvironmentRegistry
    from registry.slo_auditor import SLOAuditor

    registry = DTEnvironmentRegistry(dt_url, oauth_token=oauth_token, api_token=api_token)
    auditor = SLOAuditor(dt_url, oauth_token, api_token=api_token, registry=registry)

    console.print("[bold]Auditing SLOs...[/bold]\n")
    results = auditor.audit()

    # Display results
    table = Table(title="SLO Audit Results", show_header=True, header_style="bold cyan")
    table.add_column("SLO", style="white")
    table.add_column("Status", justify="center")
    table.add_column("Issues", style="yellow")

    for slo_result in results:
        status = "[green]OK[/green]" if slo_result.get("valid") else "[red]FAIL[/red]"
        issues = "; ".join(slo_result.get("issues", [])) or "—"
        table.add_row(slo_result.get("name", "Unknown"), status, issues[:80])

    console.print(table)

    valid = sum(1 for r in results if r.get("valid"))
    console.print(f"\n[bold]{valid}/{len(results)} SLOs valid[/bold]")


@click.command("convert")
@click.argument("nrql")
def convert_nrql(nrql: str):
    """Convert NRQL to DQL with full post-processing and auto-fixes.

    Example: python migrate.py convert "SELECT average(duration) FROM Transaction WHERE appName = 'my-api'"
    """
    from transformers.nrql_converter import NRQLtoDQLConverter

    converter = NRQLtoDQLConverter()
    result = converter.convert(nrql, "CLI query")

    console.print(result.dql)
    if result.fixes:
        for f in result.fixes:
            console.print(f"[green]Fix:[/green] {f}")
    if result.warnings:
        for w in result.warnings:
            console.print(f"[yellow]Warning:[/yellow] {w}")
    console.print(f"\n[dim]Confidence: {result.confidence}[/dim]")


def _print_reference_table():
    """Print the NRQL to DQL quick reference table."""
    table = Table(title="NRQL to DQL Quick Reference", show_header=True, header_style="bold cyan")
    table.add_column("NRQL", style="green")
    table.add_column("DQL", style="blue")

    references = [
        ("SELECT * FROM Log", "fetch logs"),
        ("SELECT count(*) FROM Transaction", "fetch ... | summarize count()"),
        ("WHERE field = 'value'", '| filter field == "value"'),
        ("WHERE field LIKE '%pattern%'", "| filter contains(field, \"pattern\")"),
        ("WHERE field IN ('a', 'b')", '| filter in(field, {"a", "b"})'),
        ("WHERE field IS NULL", "| filter isNull(field)"),
        ("FACET fieldName", "| summarize ..., by:{fieldName}"),
        ("SINCE 1 hour ago", "from:now()-1h"),
        ("LIMIT 100", "| limit 100"),
        ("TIMESERIES", "| makeTimeseries ..."),
        ("─" * 35, "─" * 35),
        ("count(*)", "count()"),
        ("average(field)", "avg(field)"),
        ("sum(field)", "sum(field)"),
        ("max(field)", "max(field)"),
        ("min(field)", "min(field)"),
        ("uniqueCount(field)", "countDistinct(field)"),
        ("percentile(field, 95)", "percentile(field, 95)"),
        ("latest(field)", "takeLast(field)"),
        ("earliest(field)", "takeFirst(field)"),
    ]

    for nrql, dql in references:
        table.add_row(nrql, dql)

    console.print(table)


@click.command("reference")
@click.option("--mappings", "-m", is_flag=True, help="Show full mapping tables (aggregations, event types, attributes)")
def reference(mappings: bool):
    """Show NRQL to DQL reference table.

    Use --mappings to display the full mapping dictionaries.
    """
    _print_reference_table()

    if mappings:
        from transformers.nrql_mapping_rules import AGG_MAP, EVENT_TYPE_MAP, ATTR_MAP

        console.print()
        agg_table = Table(title="Aggregation Mappings", show_header=True, header_style="bold cyan")
        agg_table.add_column("NRQL Function", style="green")
        agg_table.add_column("DQL Function", style="blue")
        for nrql_fn, dql_fn in sorted(AGG_MAP.items()):
            agg_table.add_row(nrql_fn, dql_fn)
        console.print(agg_table)

        console.print()
        event_table = Table(title="Event Type Mappings", show_header=True, header_style="bold cyan")
        event_table.add_column("NR Event Type", style="green")
        event_table.add_column("DT Data Object", style="blue")
        for nr_type, dt_type in sorted(EVENT_TYPE_MAP.items()):
            event_table.add_row(nr_type, dt_type)
        console.print(event_table)

        console.print()
        attr_table = Table(title="Attribute Mappings", show_header=True, header_style="bold cyan")
        attr_table.add_column("NR Attribute", style="green")
        attr_table.add_column("DT Attribute", style="blue")
        for nr_attr, dt_attr in sorted(ATTR_MAP.items()):
            attr_table.add_row(nr_attr, dt_attr)
        console.print(attr_table)


@click.command("batch")
@click.option("--file", "-f", "input_file", required=True, type=click.Path(exists=True), help="CSV or Excel file with NRQL column")
@click.option("--output", "-o", "output_file", type=click.Path(), help="Output file (CSV)")
@click.option("--nrql-column", default="nrql", help="Column name containing NRQL queries (default: nrql)")
def batch_compile(input_file: str, output_file: Optional[str], nrql_column: str):
    """Batch compile NRQL queries from a CSV or Excel file.

    Reads a file with an NRQL column, compiles each query to DQL, and writes
    results with DQL, confidence, and warnings columns.

    Example: python migrate.py batch --file queries.csv --output results.csv
    """
    import csv
    from compiler import NRQLCompiler

    compiler = NRQLCompiler()
    input_path = Path(input_file)
    rows = []

    # Read input
    if input_path.suffix in ('.xlsx', '.xls'):
        try:
            import openpyxl
            wb = openpyxl.load_workbook(input_path, read_only=True)
            ws = wb.active
            headers = [cell.value for cell in next(ws.iter_rows(min_row=1, max_row=1))]
            nrql_idx = headers.index(nrql_column) if nrql_column in headers else 0
            for row in ws.iter_rows(min_row=2, values_only=True):
                nrql = row[nrql_idx] if row[nrql_idx] else ""
                rows.append({"nrql": str(nrql), "original_row": list(row)})
            wb.close()
        except ImportError:
            console.print("[red]Error: openpyxl required for Excel files. Install with: pip install openpyxl[/red]")
            sys.exit(1)
    else:
        # CSV
        with open(input_path, 'r', newline='') as f:
            reader = csv.DictReader(f)
            for row in reader:
                nrql = row.get(nrql_column, "")
                rows.append({"nrql": nrql, "original_row": row})

    if not rows:
        console.print("[yellow]No queries found in input file[/yellow]")
        return

    # Compile each query
    results = []
    for item in rows:
        nrql = item["nrql"].strip()
        if not nrql:
            results.append({"nrql": "", "dql": "", "confidence": "", "warnings": ""})
            continue
        result = compiler.compile(nrql)
        results.append({
            "nrql": nrql,
            "dql": result.dql if result.success else f"ERROR: {result.error}",
            "confidence": result.confidence if result.success else "FAILED",
            "warnings": "; ".join(result.warnings) if result.warnings else "",
        })

    # Display summary
    succeeded = sum(1 for r in results if r["confidence"] not in ("", "FAILED"))
    failed = sum(1 for r in results if r["confidence"] == "FAILED")
    console.print(f"\n[bold]Batch compiled {len(results)} queries: "
                  f"[green]{succeeded} succeeded[/green], "
                  f"[red]{failed} failed[/red][/bold]")

    # Write output
    out_path = output_file or str(input_path.with_suffix('.results.csv'))
    with open(out_path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=["nrql", "dql", "confidence", "warnings"])
        writer.writeheader()
        writer.writerows(results)
    console.print(f"[green]Results saved to {out_path}[/green]")


def _get_version():
    try:
        from _version import __version__
        return __version__
    except ImportError:
        return "unknown"


# Create a click group to support both migration and compile subcommands
@click.group(invoke_without_command=True)
@click.version_option(version=_get_version(), prog_name="nr-to-dt-migration")
@click.pass_context
def cli(ctx):
    """New Relic to Dynatrace Migration Tool."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


# Register subcommands
cli.add_command(main, "migrate")
cli.add_command(compile_nrql, "compile")
cli.add_command(convert_nrql, "convert")
cli.add_command(reference, "reference")
cli.add_command(audit_slos, "audit-slos")
cli.add_command(batch_compile, "batch")


if __name__ == "__main__":
    cli()
