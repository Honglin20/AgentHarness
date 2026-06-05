# API 文档页设计

## 定位

API 文档是领域工具库的详细参考，从教学页可跳转进入，与教程形成闭环。

---

## 入口

1. **教学页左侧**：章节 DAG 下方，列出当前领域的 API 文档列表
2. **教程正文内**：`[Quantizer](api/quantizer.md)` 可点击跳转到 API 详情
3. **领域门户首页**：领域卡片内无直接入口（保持简洁）

---

## API 详情页布局

```
┌──────────────────────────────────────────────────────────────────┐
│ ← 返回教程        ● 量化 · Quantizer API                         │  blue accent
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  # Quantizer                                                     │
│                                                                  │
│  将 FP32 模型量化为指定比特宽度。                                 │
│                                                                  │
│  ## 参数                                                         │
│                                                                  │
│  | 参数 | 类型 | 默认值 | 说明 |                                 │
│  |------|------|--------|------|                                 │
│  | w_bits | int | 8 | 权重比特数 |                               │
│  | a_bits | int | 8 | 激活比特数 |                               │
│  | block_size | int | 16 | 分块粒度 |                           │
│                                                                  │
│  ## 示例                                                         │
│                                                                  │
│  ```python                                                       │
│  from bitx import Quantizer                                      │
│  q = Quantizer(w_bits=4, a_bits=4, block_size=16)                │
│  result = q.quantize(model, calib_loader)                        │
│  print(result.accuracy)  # 0.923                                 │
│  ```                                                             │
│                                                                  │
│  ## 输出                                                         │
│                                                                  │
│  返回 `QuantizeResult`，包含 accuracy、per_layer_qsnr 等字段。   │
│                                                                  │
│  ──────────────────────────────────────────────────────────────  │
│                                                                  │
│  相关教程                                                        │
│  · [基础量化 → 执行量化脚本] — 完整 Quantizer 使用流程           │
│  · [精度诊断 → 运行实验] — 多配置 Quantizer 对比                 │
│                                                                  │
│  其他 API                                                        │
│  · [StudyRunner]  · [Adapter]  · [StudyReport]                  │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

---

## 教学页左侧增加 API 入口

```
┌──────────────────┐
│  ● 分析项目结构   │
│  │  analyzer     │
│  ▼               │
│  ● 配置量化参数   │
│  │  configurator │
│  ▼               │
│  ● 执行量化脚本   │
│  │  runner       │
│  ▼               │
│  ● 保存诊断数据   │
│  │  diag_saver   │
│  ▼               │
│  ● 生成报告       │
│     report_painter│
│                  │
│  ─────────────── │
│                  │
│  📖 API 参考     │
│  · Quantizer     │  ← 点击进入 API 详情页
│  · StudyRunner   │
│  · Adapter       │
│                  │
│  ─────────────── │
│  [试一试 ▶]       │
└──────────────────┘
```

---

## 联动闭环

```
教学页 ──左侧 API 列表──→ API 详情页
教学页 ──正文 [Quantizer](api/quantizer.md)──→ API 详情页
API 详情页 ──底部"相关教程"──→ 教学页（滚动到对应章节）
API 详情页 ──底部"其他 API"──→ 另一个 API 详情页
```

所有跳转在同一领域内，不跳出。

---

## 链接识别规则

API 引用链接和普通链接通过**路径约定**区分：

### 目录结构

```
tutorials/quantization/
├── _index.md
├── 01_quick_start.md
└── api/
    ├── quantizer.md
    └── study_runner.md
```

### 正文写法

```markdown
调用 [Quantizer](api/quantizer.md) 进行量化...
完整参数见 → [Quantizer API](api/quantizer.md)
```

### 脚本识别

只提取 href 以 `api/` 开头的链接：

```python
for link in md_links:
    if link.href.startswith("api/"):
        api_refs.add(link.href)  # API 引用
    # 其他链接忽略（外部URL、教程间跳转等）
```

### 兜底：frontmatter apis 字段

如果正文中没有自然地提到某个 API，可在 frontmatter 补充：

```yaml
---
workflow: workflows/tutorials/mxint-analysis
apis: [quantizer, study_runner]
---
```

脚本取正文链接和 frontmatter 的并集。

---

## 数据来源

| 数据 | 来源 | 用途 |
|------|------|------|
| API 全量列表 | `api/` 目录扫描 | 左侧 API 列表、底部"其他 API" |
| 反向映射（API→章节） | 正文 `](api/xxx.md)` 链接 | API 详情页底部"相关教程" |
| frontmatter `apis` | 教程 MD 头部 | 兜底补充 |

---

## API 文档 MD 模板

```markdown
# Quantizer

将 FP32 模型量化为指定比特宽度。

## 参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| w_bits | int | 8 | 权重比特数 |
| a_bits | int | 8 | 激活比特数 |
| block_size | int | 16 | 分块粒度 |

## 示例

​```python
from bitx import Quantizer
q = Quantizer(w_bits=4, a_bits=4, block_size=16)
result = q.quantize(model, calib_loader)
print(result.accuracy)  # 0.923
​```

## 输出

返回 `QuantizeResult` 对象，包含：
- `accuracy` — 量化后精度
- `per_layer_qsnr` — 每层 QSNR 字典
- `config_name` — 配置名称
```
