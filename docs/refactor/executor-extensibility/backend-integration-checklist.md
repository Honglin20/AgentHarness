# Backend Integration Checklist

> 新 CLI backend 接入的**有序步骤清单**。每一步都要打勾才能进入下一步。配套读 [`backend-integration-template.md`](./backend-integration-template.md)(写 translator 的细节) 和 [`NEW_BACKEND_ADR_TEMPLATE.md`](./NEW_BACKEND_ADR_TEMPLATE.md)(决策记录格式)。

本文档假设 backend 名为 `<name>`(例:`opencode` / `codex`)。命令中替换为实际名字。

---

## Phase 0:调研(0.5 天)

- [ ] 阅读 [主 ADR](./ADR.md) §Decision 3,理解 CliProfile 框架
- [ ] 阅读 [`backend-integration-template.md`](./backend-integration-template.md),理解 translator 契约
- [ ] 阅读官方 backend 文档(CLI / 输出格式 / MCP 支持)
- [ ] 通读 claude-code 范本 [`harness/translator/stream_json.py`](../../../harness/translator/stream_json.py)(408 行,必读)
- [ ] 通读 [`harness/cli_profiles/claude.py`](../../../harness/cli_profiles/claude.py)(profile 范本)
- [ ] 跑一次 backend CLI,人工观察输出格式,识别事件清单

**产出**:能列出 backend 的事件类型 + 字段结构(口头或草稿)。

---

## Phase 1:录制 fixture(0.5 天)

- [ ] 确认本地已安装 backend CLI(`which <binary>`)
- [ ] 录制 5 个场景(必须):

```bash
# 1. basic — 纯文本输出
python scripts/record_cli_session.py \
    --backend <name> \
    --prompt "What is 2+2? Answer in one sentence." \
    --scenario basic \
    --out harness/translator/_fixtures/sample_<name>_basic.jsonl

# 2. with_bash — 单工具调用
python scripts/record_cli_session.py \
    --backend <name> \
    --prompt "Run 'echo hello' and tell me the output." \
    --scenario with_bash \
    --out harness/translator/_fixtures/sample_<name>_with_bash.jsonl

# 3. multi_step — 多步推理(至少 2 次工具调用)
python scripts/record_cli_session.py \
    --backend <name> \
    --prompt "Read README.md, then read pyproject.toml, summarize both." \
    --scenario multi_step \
    --out harness/translator/_fixtures/sample_<name>_multi_step.jsonl

# 4. error — 错误路径(故意配错 API key / 用不存在的工具)
python scripts/record_cli_session.py \
    --backend <name> \
    --prompt "..." \
    --scenario error \
    --out harness/translator/_fixtures/sample_<name>_error.jsonl

# 5. structured — 结构化输出(请求 JSON)
python scripts/record_cli_session.py \
    --backend <name> \
    --prompt "Return JSON: {\"answer\": \"...\"} with the meaning of life." \
    --scenario structured \
    --out harness/translator/_fixtures/sample_<name>_structured.jsonl
```

- [ ] 检查每个 fixture:第一行和最后一行能 `python -c "import json; json.loads(open('...').readline())"` 通过
- [ ] 提交 fixture 到 git(用于测试 + 离线复现)

**录制脚本约束**:`sample_<name>_*.jsonl` 已存在时 skip,**不允许覆盖**(尤其保护现有 `sample_basic.jsonl` / `sample_with_bash.jsonl` 的 claude fixture)。

**产出**:`harness/translator/_fixtures/sample_<name>_*.jsonl` × 5 个,全部 git 提交。

---

## Phase 2:写 ADR(0.5 天)

- [ ] 复制 [`NEW_BACKEND_ADR_TEMPLATE.md`](./NEW_BACKEND_ADR_TEMPLATE.md) 到 `docs/refactor/executor-extensibility/<date>-<name>-backend.md`
- [ ] 填 Context(为什么加这个 backend)
- [ ] 填 Protocol Research(基于 Phase 1 录制的 fixture)
- [ ] 填 Event Mapping 表
- [ ] 填 Decision 1(CliProfile 字段)
- [ ] 填 Decision 2(映射规则)
- [ ] 填 Decision 3(result_extractor)
- [ ] 填 Decision 4(Pitfall Decisions,每个陷阱都明确决策)
- [ ] 填 Test Matrix
- [ ] 填 Rollback Criteria

**产出**:`docs/refactor/executor-extensibility/<date>-<name>-backend.md`。

---

## Phase 3:实现 translator(0.5-1 天)

- [ ] 新建 `harness/translator/<name>_stream.py`
- [ ] 实现 `translate(event: dict, ctx: TranslateContext) -> list[TranslatedEvent]` 主入口
- [ ] 按 ADR Event Mapping 表实现每个 `_translate_*` 子函数
- [ ] 实现 `_DISPATCH` 字典,按 backend 原生 `type` 字段分派
- [ ] 未知事件 → 返回空列表(不抛)
- [ ] 缺字段 → 返回空列表或最佳努力(不抛)
- [ ] **关键 import 检查**:`from harness.translator import TranslateContext, TranslatedEvent`(允许);**不允许**任何修改 `harness/translator/__init__.py` 的操作

参考骨架见 [`backend-integration-template.md` §5](./backend-integration-template.md)。

**产出**:`harness/translator/<name>_stream.py`。

---

## Phase 4:写 CliProfile(0.5 天)

- [ ] 新建 `harness/cli_profiles/<name>.py`(builtin)或 `./.harness/cli_profiles/<name>.py`(项目级)
- [ ] 导出 `PROFILE = CliProfile(...)` 实例
- [ ] `translator` 字段**必须用全路径 import**:

```python
from harness.translator.<name>_stream import translate as _<name>_translator

PROFILE = CliProfile(
    name="<name>",
    prompt_paradigm="minimal",
    cli_path_env="HARNESS_<UPPER>_CLI",
    default_cli_path="<binary>",
    flags=(...),
    prompt_channel="<stdin|argv>",
    mcp_flag_template=<None | "--mcp {path}">,
    env_overlay_prefixes=(...),
    translator=_<name>_translator,
    result_extractor=<填写 — 见 ADR Decision 3>,
    default_timeout_s=<填写>,
)
```

- [ ] 写 env overlay 配置(项目 `.env` 加 `<UPPERPER_>_API_KEY` 等)
- [ ] 烟测:重启 server,看 startup log 是否出现 `registered builtin profile <name> from ...`

**产出**:`harness/cli_profiles/<name>.py` + `.env` 增量。

---

## Phase 5:写测试(0.5 天)

- [ ] 新建 `tests/translator/test_<name>_stream.py`
- [ ] 继承 `TranslatorTestBase`,声明 `TRANSLATOR` 和 `BACKEND_NAME`:

```python
from harness.translator.<name>_stream import translate
from harness.translator import TranslateContext
from tests.translator._base import TranslatorTestBase

class Test<Name>Translator(TranslatorTestBase):
    TRANSLATOR = translate
    BACKEND_NAME = "<name>"

    def test_basic_session(self):
        events = self.load_fixture("basic")
        ctx = TranslateContext(node_id="n1", agent_name="a1", iteration=1, attempt=1)
        out = self.translate_all(events, ctx)
        self.assert_event_types_subset(out)
        self.assert_tool_call_id_consistency(out)

    # ... 其他场景测试,对照 ADR Test Matrix
```

- [ ] 覆盖 ADR Test Matrix 的每一行(至少 5 个 fixture 场景 + 未知事件 + 缺字段)
- [ ] 跑 `python -m pytest tests/translator/test_<name>_stream.py -v` 全绿

**产出**:`tests/translator/test_<name>_stream.py`。

---

## Phase 6:零回归验证(0.5 天)

**这是用户最关心的环节** —— 不能影响 pydantic-ai 和 claude-code。

跑下面 5 条命令,全部通过才能继续:

```bash
cd /Users/mozzie/Desktop/Projects/AgentHarness

# 1. 全量回归
python -m pytest tests/ -x -q

# 2. translator 专项(claude-code 稳定性核心证据)
python -m pytest tests/translator/ -v
python -m pytest tests/engine/test_claude_code_executor.py \
    tests/engine/test_claude_code_executor_profile.py \
    tests/engine/test_claude_code_executor_env_overlay.py -v

# 3. CliProfile registry 不受污染
python -m pytest tests/engine/test_cli_profile_registry.py \
    tests/engine/test_cli_profile_dataclass.py \
    tests/engine/test_cli_profile_startup_degradation.py \
    tests/engine/test_executor_factory_profile_dispatch.py \
    tests/engine/test_custom_profile_e2e_mock.py -v

# 4. import 解耦 grep(应只显示现有依赖 + 新 backend 全路径 import)
grep -rn "from harness.translator" harness/ tests/

# 5. __init__.py 未被改动(必须为空)
git diff --name-only harness/translator/__init__.py
```

- [ ] 命令 1-3 全绿
- [ ] 命令 4 grep 输出里**新 backend 都用全路径**(`from harness.translator.<name>_stream import`)
- [ ] 命令 5 输出为空(`__init__.py` 未被修改)

**任一失败 → 不允许合并,必须先排查根因。**

---

## Phase 7:端到端 + 文档(0.5-1 天)

- [ ] 写一个简单 workflow JSON,用一个 agent 配置 `executor: "<name>"`
- [ ] 启动 server,跑这个 workflow,验证:
  - [ ] 启动日志显示 `registered builtin profile <name>`
  - [ ] workflow 正常完成(`node.completed`)
  - [ ] 前端能看到 text_delta / tool_call / tool_result
  - [ ] 错误路径(故意配错)emit `agent.executor_error` 且 `executor` 字段 = `<name>`(不是 `claude-code`)
- [ ] 写 release note `docs/releases/<date>-<name>-backend.md`
- [ ] 更新 `docs/status/CHANGELOG.md` 顶部索引
- [ ] 更新 `docs/status/CURRENT.md`(若任务完成则清空)
- [ ] (可选)更新 `README.md` 执行器与 CLI Profile 章节,把新 backend 加入支持列表

**产出**:release note + CHANGELOG 索引 + 端到端证据。

---

## 完成签收

全部勾选后,PR 描述应包含:

- [x] ADR 链接
- [x] fixture 链接(5 个)
- [x] 测试通过截图/log
- [x] 零回归证据(Phase 6 的 5 条命令输出)
- [x] 端到端 demo 结果
- [x] CHANGELOG 索引已加

**预估总工作量**:3-4 天(已含调研和文档,不含等待 review 时间)。

---

## 常见陷阱自查

- [ ] translator 是否在 import `harness.translator.translate`?(❌ 不允许)
- [ ] 是否改了 `harness/translator/__init__.py`?(❌ 不允许)
- [ ] tool_call 是否带 `tool_call_id`?(必须)
- [ ] 未知事件是否抛异常?(必须返回 `[]`)
- [ ] 错误事件是否在 translator emit?(❌ 由 executor emit)
- [ ] profile 是否用全路径 import translator?(必须)
- [ ] 是否跑了 Phase 6 的 5 条验证命令?(必须全绿)
