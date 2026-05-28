"""Console output Hook — 使用 Rich 美化打印 workflow 状态和 agent 输出到命令行。

仅通过 Workflow.use(ConsoleOutput()) 手动注册，不会自动激活，
确保不影响现有 UI。

用法:
    from harness.extensions.console import ConsoleOutput

    wf = Workflow("test", agents=[...])
    wf.use(ConsoleOutput(stream=False, verbose=True))
    result = wf.run({"task": "..."})

依赖:
    pip install rich
"""

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.json import JSON
from rich.syntax import Syntax
from rich.markdown import Markdown
from rich.text import Text
from rich.progress import Progress, BarColumn, TextColumn
from rich.layout import Layout
from rich.align import Align

from harness.extensions.base import AgentConfig, BaseHook, WorkflowCtx, NodeCtx, ToolCtx, Any

# 创建全局 console 实例
console = Console()


class ConsoleOutput(BaseHook):
    """命令行输出 Hook — 使用 Rich 美化打印 workflow 状态和 agent 输出"""

    name = "console-output"

    def __init__(self, stream: bool = False, verbose: bool = True, show_system: bool = True, show_upstream: bool = True, use_colors: bool = True, show_model: bool = True, show_tools: bool = True, show_config: bool = False, show_critique: bool = True, show_full_prompt: bool = True):
        self.stream = stream
        self.verbose = verbose
        self.show_system = show_system
        self.show_upstream = show_upstream
        self.use_colors = use_colors
        self.show_model = show_model
        self.show_tools = show_tools
        self.show_config = show_config
        self.show_critique = show_critique
        self.show_full_prompt = show_full_prompt
        self._buffer = ""
        # 禁用颜色
        if not use_colors:
            self.console = Console(no_color=True)
        else:
            self.console = console

    def _extract_system_prompt(self, messages: list[dict], config: AgentConfig | None = None) -> str | None:
        """从 messages 或 config 中提取 system prompt"""
        for msg in messages:
            if msg.get("role") == "system":
                content = msg.get("content", "")
                return content.lstrip("\n")
        # Fallback to config
        if config and config.system_prompt:
            return config.system_prompt.lstrip("\n")
        return None

    def _extract_user_prompt(self, messages: list[dict]) -> str | None:
        """从 messages 中提取最后的 user prompt"""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                content = msg.get("content", "")
                return content
        return None

    def _format_upstream_outputs(self, outputs: dict) -> Table:
        """格式化上游输出为表格"""
        table = Table(show_header=False, box=None, pad_edge=False)
        table.add_column("name", style="cyan", width=12)
        table.add_column("content", style="dim")

        if not outputs:
            table.add_row("", "[dim]无上游输出[/dim]")
            return table

        for name, output in outputs.items():
            if isinstance(output, dict):
                summary = str(output.get("summary", ""))[:80]
                table.add_row(name, f"[dim]{summary}[/dim]")
            else:
                out = str(output)[:80]
                table.add_row(name, f"[dim]{out}[/dim]")
        return table

    def _format_output(self, output: Any) -> Panel | None:
        """格式化输出为 Panel"""
        if not self.verbose:
            return None

        # Normalize Pydantic BaseModel to dict
        if hasattr(output, "model_dump"):
            output = output.model_dump()

        content_parts = []

        if isinstance(output, dict):
            # Summary
            if "summary" in output:
                summary = str(output["summary"])
                # 尝试解析 JSON
                try:
                    import json
                    parsed = json.loads(summary)
                    if isinstance(parsed, dict):
                        content_parts.append("[bold]输出摘要:[/bold]")
                        content_parts.append(JSON(parsed, ensure_ascii=False))
                    else:
                        content_parts.append(f"[bold]输出摘要:[/bold]\n{summary}")
                except:
                    content_parts.append(f"[bold]输出摘要:[/bold]\n{summary}")

            # Details
            if "details" in output and output["details"]:
                details = str(output["details"])
                # 尝试解析 JSON
                try:
                    import json
                    parsed = json.loads(details)
                    if isinstance(parsed, dict) or isinstance(parsed, list):
                        content_parts.append("\n[bold]详细内容:[/bold]")
                        content_parts.append(JSON(parsed, ensure_ascii=False))
                    else:
                        content_parts.append(f"\n[bold]详细内容:[/bold]\n{details}")
                except:
                    content_parts.append(f"\n[bold]详细内容:[/bold]\n{details}")

            # 其他字段
            other_keys = [k for k in output.keys() if k not in ["summary", "details"]]
            if other_keys:
                content_parts.append("\n[bold]其他字段:[/bold]")
                for k in other_keys:
                    val = str(output[k])
                    try:
                        parsed = json.loads(val)
                        content_parts.append(f"  • [cyan]{k}[/cyan]:")
                        content_parts.append(f"    {JSON(parsed, ensure_ascii=False)}")
                    except:
                        content_parts.append(f"  • [cyan]{k}[/cyan]: {val[:100]}")

            if not content_parts:
                return None

            # 组合成 Panel
            from rich.console import Group
            return Panel(Group(*content_parts), border_style="green", title="[bold]Agent 输出[/bold]", padding=(0, 1))

        else:
            # 非字典输出
            text = str(output)
            try:
                import json
                parsed = json.loads(text)
                if isinstance(parsed, (dict, list)):
                    return Panel(JSON(parsed, ensure_ascii=False), border_style="green", title="[bold]输出[/bold]")
            except:
                pass
            return Panel(text, border_style="green", title="[bold]输出[/bold]")

    async def on_workflow_start(self, ctx: WorkflowCtx) -> None:
        title = Text.assemble(
            ("🚀 Workflow: ", "bold white"),
            (ctx.workflow_name, "bold cyan"),
        )
        subtitle = Text(f"ID: {ctx.workflow_id[:8]}...", style="dim")
        self.console.print(Panel(Align.center(subtitle), title=title, border_style="blue", padding=(1, 2)))
        self.console.print()

    async def on_workflow_end(self, ctx: WorkflowCtx, result: dict[str, Any]) -> None:
        self.console.print()

        if "errors" in result and result["errors"]:
            error_text = f"错误: {result['errors']}"
            self.console.print(Panel(error_text, title="[bold red]❌ Workflow 未完成[/bold red]", border_style="red"))
        else:
            self.console.print(Panel("✅", title="[bold green]Workflow 完成[/bold green]", border_style="green"))
        self.console.print()

    async def on_node_start(self, ctx: NodeCtx) -> None:
        # 标题
        title = Text.assemble(
            ("🔹 ", "yellow"),
            (ctx.agent_name, "bold yellow"),
            (" 开始执行", "yellow"),
        )
        self.console.print(Panel("", title=title, border_style="yellow", padding=(0, 1)))

        if self.verbose:
            # System prompt（如果有）
            if self.show_system:
                system = self._extract_system_prompt(ctx.messages, ctx.config)
                if system:
                    display = system if self.show_full_prompt else system[:500]
                    self.console.print(Panel(Markdown(display), title="📌 System Prompt", border_style="magenta", padding=(0, 1)))

            # User prompt
            user = self._extract_user_prompt(ctx.messages)
            if user:
                display = user if self.show_full_prompt else user[:300]
                self.console.print(Panel(display, title="📌 User Prompt", border_style="cyan", padding=(0, 1)))

            # 上游输出
            if self.show_upstream and ctx.upstream_outputs:
                upstream_table = self._format_upstream_outputs(ctx.upstream_outputs)
                self.console.print(Panel(upstream_table, title="📤 上游输出", border_style="blue", padding=(0, 1)))

            # Agent config (tools, model, paths, critique)
            if ctx.config is not None:
                if self.show_model and ctx.config.model:
                    self.console.print(Panel(
                        ctx.config.model,
                        title="Model",
                        border_style="blue",
                        padding=(0, 1),
                    ))

                if self.show_tools and ctx.config.tool_info:
                    tools_table = Table(show_header=True, box=None, pad_edge=False)
                    tools_table.add_column("Tool", style="cyan", width=20)
                    tools_table.add_column("Description", style="dim")
                    for ti in ctx.config.tool_info:
                        tools_table.add_row(ti.get("name", ""), ti.get("description", "")[:80])
                    self.console.print(Panel(tools_table, title="Tools", border_style="blue", padding=(0, 1)))

                if self.show_critique and ctx.config.critique:
                    self.console.print(Panel(
                        ctx.config.critique[:300],
                        title="Critique (retry feedback)",
                        border_style="red",
                        padding=(0, 1),
                    ))

                if self.show_config:
                    config_lines = []
                    if ctx.config.retries is not None:
                        config_lines.append(f"Retries: {ctx.config.retries}")
                    if ctx.config.result_type_name:
                        config_lines.append(f"Result type: {ctx.config.result_type_name}")
                    if ctx.config.agent_md_path:
                        config_lines.append(f"Agent MD: {ctx.config.agent_md_path}")
                    if config_lines:
                        self.console.print(Panel(
                            "\n".join(config_lines),
                            title="Config",
                            border_style="dim",
                            padding=(0, 1),
                        ))

        self.console.print()

    async def on_node_end(self, ctx: NodeCtx, output: Any) -> None:
        if self._buffer:
            self.console.print()

        # 标题
        title = Text.assemble(
            ("✓ ", "green"),
            (ctx.agent_name, "bold green"),
            (" 执行完成", "green"),
        )
        self.console.print(Panel("", title=title, border_style="green", padding=(0, 1)))

        if self.verbose and output:
            panel = self._format_output(output)
            if panel:
                self.console.print(panel)

        self._buffer = ""

    async def on_llm_delta(self, ctx: NodeCtx, delta: str) -> None:
        if self.stream:
            self._buffer += delta
            # 累积到一定长度再输出
            if len(self._buffer) > 50 or "\n" in self._buffer:
                self.console.print(self._buffer, end="", style="dim")
                self._buffer = ""
        else:
            self.console.print(".", end="", style="dim")

    async def on_tool_call(self, ctx: ToolCtx, result: Any) -> None:
        if self.verbose:
            title = Text.assemble(
                ("🔧 ", "magenta"),
                (ctx.tool_name, "bold magenta"),
            )
            result_str = str(result)[:150]
            self.console.print(Panel(result_str, title=title, border_style="magenta", padding=(0, 1)))