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
                        transformed_data["dashboards"].append(result.data)
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
def main(
    full: bool,
    export_only: bool,
    import_only: bool,
    input_dir: Optional[str],
    output_dir: str,
    components: Optional[str],
    dry_run: bool,
    list_components: bool
):
    """New Relic to Dynatrace Migration Tool."""

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

    # Create orchestrator
    orchestrator = MigrationOrchestrator(
        newrelic_client=nr_client,
        dynatrace_client=dt_client,
        output_dir=output_dir,
        dry_run=dry_run
    )

    # Run migration
    if full or (not export_only and not import_only):
        orchestrator.run_full_migration(component_list)
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


@click.command("compile")
@click.argument("nrql")
def compile_nrql(nrql: str):
    """Compile a single NRQL query to DQL.

    Example: python migrate.py compile "SELECT count(*) FROM Transaction FACET appName TIMESERIES"
    """
    from compiler import NRQLCompiler

    compiler = NRQLCompiler()
    result = compiler.compile(nrql)

    if result.success:
        console.print(result.dql)
        if result.warnings:
            for w in result.warnings:
                console.print(f"[yellow]Warning:[/yellow] {w}")
    else:
        console.print(f"[red]Error:[/red] {result.error}")
        sys.exit(1)


@click.command("convert")
@click.argument("nrql")
def convert_nrql(nrql: str):
    """Convert NRQL to DQL with full post-processing and auto-fixes.

    Example: python migrate.py convert "SELECT average(duration) FROM Transaction WHERE appName = 'my-api'"
    """
    from transformers.nrql_converter import NRQLtoDQLConverter

    converter = NRQLtoDQLConverter()
    result = converter.convert(nrql, "CLI query")

    console.print(result.converted_dql)
    if result.fixes_applied:
        for f in result.fixes_applied:
            console.print(f"[green]Fix:[/green] {f}")
    if result.warnings:
        for w in result.warnings:
            console.print(f"[yellow]Warning:[/yellow] {w}")
    console.print(f"\n[dim]Confidence: {result.confidence}[/dim]")


# Create a click group to support both migration and compile subcommands
@click.group(invoke_without_command=True)
@click.pass_context
def cli(ctx):
    """New Relic to Dynatrace Migration Tool."""
    if ctx.invoked_subcommand is None:
        # No subcommand — show help
        click.echo(ctx.get_help())


# Register subcommands
cli.add_command(main, "migrate")
cli.add_command(compile_nrql, "compile")
cli.add_command(convert_nrql, "convert")


if __name__ == "__main__":
    cli()
