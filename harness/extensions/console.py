"""Console output Hook — 美化打印 workflow 状态和 agent 输出到命令行。

仅通过 Workflow.use(ConsoleOutput()) 手动注册，不会自动激活，
确保不影响现有 UI。

用法:
    from harness.extensions.console import ConsoleOutput

    wf = Workflow("test", agents=[...])
    wf.use(ConsoleOutput(stream=False, verbose=True))
    result = wf.run({"task": "..."})
"""

import textwrap
from harness.extensions.base import BaseHook, WorkflowCtx, NodeCtx, ToolCtx, Any


class ConsoleOutput(BaseHook):
    """命令行输出 Hook — 美化打印 workflow 状态和 agent 输出"""

    name = "console-output"

    def __init__(self, stream: bool = False, verbose: bool = True, show_system: bool = True, show_upstream: bool = True):
        self.stream = stream
        self.verbose = verbose
        self.show_system = show_system
        self.show_upstream = show_upstream
        self._buffer = ""

    def _box(self, title: str, content: str, width: int = 60) -> str:
        """绘制带标题的框"""
        if not content:
            return ""
        lines = []
        lines.append(f"┌─ {title} " + "─" * (max(0, width - len(title) - 5)) + "┐")
        for line in textwrap.wrap(content, width - 4):
            lines.append("│ " + line + " " * (width - 4 - len(line)) + " │")
        lines.append("└" + "─" * (width - 2) + "┘")
        return "\n".join(lines)

    def _section(self, title: str, content: str, indent: int = 4) -> str:
        """绘制带标题的区域"""
        if not content:
            return ""
        indent_str = " " * indent
        lines = []
        lines.append(f"{indent_str}┌─ {title}")
        for line in textwrap.wrap(content, 70 - indent - 4):
            lines.append(f"{indent_str}│ {line}")
        lines.append(f"{indent_str}└")
        return "\n".join(lines)

    def _extract_system_prompt(self, messages: list[dict]) -> str | None:
        """从 messages 中提取 system prompt"""
        for msg in messages:
            if msg.get("role") == "system":
                content = msg.get("content", "")
                # 去掉可能的换行符开头
                return content.lstrip("\n")
        return None

    def _extract_user_prompt(self, messages: list[dict]) -> str | None:
        """从 messages 中提取最后的 user prompt"""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                content = msg.get("content", "")
                return content
        return None

    def _format_upstream_outputs(self, outputs: dict) -> str:
        """格式化上游输出"""
        if not outputs:
            return "(无上游输出)"
        lines = []
        for name, output in outputs.items():
            lines.append(f"• {name}:")
            if isinstance(output, dict):
                if "summary" in output:
                    lines.append(f"  Summary: {output['summary'][:100]}...")
                if "details" in output and output["details"]:
                    lines.append(f"  Details: {str(output['details'])[:100]}...")
            else:
                lines.append(f"  {str(output)[:100]}...")
        return "\n".join(lines)

    async def on_workflow_start(self, ctx: WorkflowCtx) -> None:
        print(f"\n{'╔' + '═' * 48 + '╗'}")
        print(f"║ 🚀 Workflow: {ctx.workflow_name:<36} ║")
        print(f"║ ID: {ctx.workflow_id[:8]}...{' ':36} ║")
        print(f"╚{'═' * 48}╝\n")

    async def on_workflow_end(self, ctx: WorkflowCtx, result: dict[str, Any]) -> None:
        print(f"\n{'╔' + '═' * 48 + '╗'}")
        print(f"║ ✅ Workflow 完成{' ':33} ║")
        if "errors" in result and result["errors"]:
            print(f"║ ❌ 错误: {str(result['errors'])[:40]}... ║")
        print(f"╚{'═' * 48}╝\n")

    async def on_node_start(self, ctx: NodeCtx) -> None:
        print(f"\n{'─' * 50}")
        print(f"🔹 [{ctx.agent_name}] 开始执行")
        print(f"{'─' * 50}\n")

        if self.verbose:
            # System prompt（如果有）
            if self.show_system:
                system = self._extract_system_prompt(ctx.messages)
                if system:
                    print(self._section("System Prompt", system))

            # User prompt
            user = self._extract_user_prompt(ctx.messages)
            if user:
                print(self._section("User Prompt", user))

            # 上游输出
            if self.show_upstream and ctx.upstream_outputs:
                upstream = self._format_upstream_outputs(ctx.upstream_outputs)
                print(self._section("上游 Agent 输出", upstream))

            print()  # 空行

    async def on_node_end(self, ctx: NodeCtx, output: Any) -> None:
        if self._buffer:
            print()  # 流式缓冲残留换行

        print(f"{'─' * 50}")
        print(f"✓ [{ctx.agent_name}] 执行完成")
        print(f"{'─' * 50}\n")

        if self.verbose and output:
            self._print_output(output)
        self._buffer = ""

    async def on_llm_delta(self, ctx: NodeCtx, delta: str) -> None:
        if self.stream:
            self._buffer += delta
            while "\n" in self._buffer:
                line, self._buffer = self._buffer.split("\n", 1)
                print(f"  {line}")
        else:
            print(".", end="", flush=True)

    async def on_tool_call(self, ctx: ToolCtx, result: Any) -> None:
        if self.verbose:
            result_str = str(result)[:150]
            print(f"\n  🔧 工具调用: {ctx.tool_name}")
            print(f"     └─ {result_str}{'...' if len(str(result)) > 150 else ''}")

    def _print_output(self, output: Any) -> None:
        """美化打印输出"""
        if isinstance(output, dict):
            # 打印 Summary
            if "summary" in output:
                summary = output["summary"]
                print("┌─ 📋 输出摘要")
                for line in textwrap.wrap(str(summary), 66):
                    print(f"│ {line}")
                print("└")

            # 打印 Details
            if "details" in output and output["details"]:
                details = output["details"]
                print("\n┌─ 📝 详细内容")
                detail_text = str(details)
                # 限制长度
                if len(detail_text) > 500:
                    detail_text = detail_text[:500] + "..."
                for line in textwrap.wrap(detail_text, 66):
                    print(f"│ {line}")
                print("└")

            # 其他字段
            other_keys = [k for k in output.keys() if k not in ["summary", "details"]]
            if other_keys:
                print("\n其他字段:")
                for k in other_keys:
                    val = str(output[k])[:100]
                    print(f"  • {k}: {val}{'...' if len(str(output[k])) > 100 else ''}")
        else:
            # 非字典输出
            print("┌─ 📋 输出内容")
            text = str(output)
            if len(text) > 300:
                text = text[:300] + "..."
            for line in textwrap.wrap(text, 66):
                print(f"│ {line}")
            print("└")