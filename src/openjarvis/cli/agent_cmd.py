"""``jarvis agents`` — persistent agent lifecycle management."""

from __future__ import annotations

from typing import Optional

import click
from rich.console import Console
from rich.table import Table


def _get_manager():
    """Get or create the AgentManager singleton."""
    from pathlib import Path

    from openjarvis.agents.manager import AgentManager
    from openjarvis.core.config import load_config

    config = load_config()
    db_path = config.agent_manager.db_path or str(
        Path("~/.openjarvis/agents.db").expanduser()
    )
    return AgentManager(db_path=db_path)


@click.group("agents")
def agent() -> None:
    """Manage persistent agents — create, inspect, chat, bind channels."""


@agent.command("list")
def list_agents() -> None:
    """List all managed agents."""
    console = Console(stderr=True)
    try:
        mgr = _get_manager()
        agents = mgr.list_agents()
        if not agents:
            console.print(
                "[dim]No agents found. Create one with: jarvis agents create[/dim]"
            )
            return
        table = Table(title="Managed Agents")
        table.add_column("ID", style="cyan", no_wrap=True)
        table.add_column("Name", style="green")
        table.add_column("Type", style="yellow")
        table.add_column("Status", style="bold")
        table.add_column("Tasks", justify="right")
        table.add_column("Channels", justify="right")
        for a in agents:
            tasks = mgr.list_tasks(a["id"])
            bindings = mgr.list_channel_bindings(a["id"])
            status_style = {
                "idle": "dim", "running": "green", "paused": "yellow",
                "error": "red", "archived": "dim strike",
            }.get(a["status"], "")
            table.add_row(
                a["id"], a["name"], a["agent_type"],
                f"[{status_style}]{a['status']}[/{status_style}]",
                str(len(tasks)), str(len(bindings)),
            )
        console.print(table)
    except Exception as exc:
        console.print(f"[red]Error: {exc}[/red]")


@agent.command("create")
@click.option("--name", "-n", required=True, help="Agent name")
@click.option("--template", "-t", default=None, help="Template ID to use")
@click.option("--type", "agent_type", default="monitor_operative", help="Agent type")
def create_agent(name: str, template: Optional[str], agent_type: str) -> None:
    """Create a new persistent agent."""
    console = Console(stderr=True)
    try:
        mgr = _get_manager()
        if template:
            result = mgr.create_from_template(template, name)
        else:
            result = mgr.create_agent(name=name, agent_type=agent_type)
        console.print(
            f"[green]Created agent:[/green] {result['id']} ({result['name']})"
        )
    except Exception as exc:
        console.print(f"[red]Error: {exc}[/red]")


@agent.command("info")
@click.argument("agent_id")
def info(agent_id: str) -> None:
    """Show detailed info about a managed agent."""
    console = Console(stderr=True)
    try:
        mgr = _get_manager()
        a = mgr.get_agent(agent_id)
        if not a:
            console.print(f"[red]Agent not found: {agent_id}[/red]")
            return
        console.print(f"[bold]{a['name']}[/bold] ({a['id']})")
        console.print(f"  Type:   {a['agent_type']}")
        console.print(f"  Status: {a['status']}")
        if a.get("summary_memory"):
            console.print(f"  Memory: {a['summary_memory'][:100]}...")
        tasks = mgr.list_tasks(agent_id)
        if tasks:
            console.print(f"  Tasks:  {len(tasks)}")
            for t in tasks[:5]:
                console.print(f"    [{t['status']}] {t['description'][:60]}")
        bindings = mgr.list_channel_bindings(agent_id)
        if bindings:
            console.print(f"  Channels: {len(bindings)}")
            for b in bindings:
                console.print(f"    {b['channel_type']}: {b['config']}")
    except Exception as exc:
        console.print(f"[red]Error: {exc}[/red]")


@agent.command("tasks")
@click.argument("agent_id")
def tasks(agent_id: str) -> None:
    """List tasks for an agent."""
    console = Console(stderr=True)
    try:
        mgr = _get_manager()
        task_list = mgr.list_tasks(agent_id)
        if not task_list:
            console.print("[dim]No tasks.[/dim]")
            return
        table = Table(title="Tasks")
        table.add_column("ID", style="cyan", no_wrap=True)
        table.add_column("Description", style="white")
        table.add_column("Status", style="bold")
        for t in task_list:
            table.add_row(t["id"], t["description"][:60], t["status"])
        console.print(table)
    except Exception as exc:
        console.print(f"[red]Error: {exc}[/red]")


@agent.command("pause")
@click.argument("agent_id")
def pause(agent_id: str) -> None:
    """Pause an agent."""
    console = Console(stderr=True)
    try:
        mgr = _get_manager()
        mgr.pause_agent(agent_id)
        console.print(f"[yellow]Paused agent {agent_id}[/yellow]")
    except Exception as exc:
        console.print(f"[red]Error: {exc}[/red]")


@agent.command("resume")
@click.argument("agent_id")
def resume(agent_id: str) -> None:
    """Resume a paused agent."""
    console = Console(stderr=True)
    try:
        mgr = _get_manager()
        mgr.resume_agent(agent_id)
        console.print(f"[green]Resumed agent {agent_id}[/green]")
    except Exception as exc:
        console.print(f"[red]Error: {exc}[/red]")


@agent.command("delete")
@click.argument("agent_id")
def delete(agent_id: str) -> None:
    """Archive (soft-delete) an agent."""
    console = Console(stderr=True)
    try:
        mgr = _get_manager()
        mgr.delete_agent(agent_id)
        console.print(f"[dim]Archived agent {agent_id}[/dim]")
    except Exception as exc:
        console.print(f"[red]Error: {exc}[/red]")


@agent.command("bind")
@click.argument("agent_id")
@click.option("--slack", default=None, help="Slack channel (e.g. #research)")
@click.option("--telegram", default=None, help="Telegram chat ID")
@click.option("--whatsapp", default=None, help="WhatsApp phone number")
def bind(
    agent_id: str,
    slack: Optional[str],
    telegram: Optional[str],
    whatsapp: Optional[str],
) -> None:
    """Bind a channel to an agent."""
    console = Console(stderr=True)
    try:
        mgr = _get_manager()
        if slack:
            b = mgr.bind_channel(agent_id, "slack", {"channel": slack})
        elif telegram:
            b = mgr.bind_channel(agent_id, "telegram", {"chat_id": telegram})
        elif whatsapp:
            b = mgr.bind_channel(agent_id, "whatsapp", {"phone": whatsapp})
        else:
            console.print(
                "[red]Specify a channel: --slack, --telegram, or --whatsapp[/red]"
            )
            return
        console.print(f"[green]Bound channel:[/green] {b['id']} ({b['channel_type']})")
    except Exception as exc:
        console.print(f"[red]Error: {exc}[/red]")


@agent.command("channels")
@click.argument("agent_id")
def channels(agent_id: str) -> None:
    """List channel bindings for an agent."""
    console = Console(stderr=True)
    try:
        mgr = _get_manager()
        bindings = mgr.list_channel_bindings(agent_id)
        if not bindings:
            console.print("[dim]No channel bindings.[/dim]")
            return
        table = Table(title="Channel Bindings")
        table.add_column("ID", style="cyan")
        table.add_column("Type", style="green")
        table.add_column("Config", style="white")
        table.add_column("Mode", style="yellow")
        for b in bindings:
            table.add_row(
                b["id"], b["channel_type"], str(b["config"]), b["routing_mode"]
            )
        console.print(table)
    except Exception as exc:
        console.print(f"[red]Error: {exc}[/red]")


@agent.command("search")
@click.argument("agent_id")
@click.argument("query")
@click.option("--limit", "-l", default=10, help="Max results")
def search(agent_id: str, query: str, limit: int) -> None:
    """Cross-session search across agent traces."""
    console = Console(stderr=True)
    try:
        from openjarvis.core.config import load_config
        from openjarvis.traces.store import TraceStore

        config = load_config()
        mgr = _get_manager()
        agent = mgr.get_agent(agent_id)
        if not agent:
            console.print(f"[red]Agent not found: {agent_id}[/red]")
            return
        store = TraceStore(config.traces.db_path or "~/.openjarvis/traces.db")
        results = store.search(query, agent=agent["name"], limit=limit)
        if not results:
            console.print("[dim]No results.[/dim]")
            return
        table = Table(title=f"Search: {query}")
        table.add_column("Trace", style="cyan", no_wrap=True)
        table.add_column("Query", style="white")
        table.add_column("Result", style="green")
        for r in results:
            table.add_row(r["trace_id"][:12], r["query"][:40], r["result"][:40])
        console.print(table)
    except Exception as exc:
        console.print(f"[red]Error: {exc}[/red]")


@agent.command("templates")
def templates() -> None:
    """List available agent templates."""
    console = Console(stderr=True)
    try:
        from openjarvis.agents.manager import AgentManager

        tpls = AgentManager.list_templates()
        if not tpls:
            console.print("[dim]No templates found.[/dim]")
            return
        table = Table(title="Agent Templates")
        table.add_column("ID", style="cyan")
        table.add_column("Name", style="green")
        table.add_column("Source", style="yellow")
        table.add_column("Description", style="white")
        for t in tpls:
            table.add_row(
                t.get("id", ""), t.get("name", ""),
                t.get("source", ""), t.get("description", "")[:60],
            )
        console.print(table)
    except Exception as exc:
        console.print(f"[red]Error: {exc}[/red]")


__all__ = ["agent"]
