# Current Task

**当前任务**: 领域门户 (Domain Portal) — Phase 1-4 完成
**状态**: Phase 4 完成，待浏览器验证

---

## 已完成

### Phase 1: 门户首页 ✅
### Phase 2: 生产工作流页 ✅
### Phase 3: 教学页 ✅

### Phase 4: API 文档页 ✅
- 后端: `parse_tutorials.py` 提取 section 级 api_refs + 反向映射 (API → 章节)
- 后端: `GET /api/domains/{domain}/api/{name}` 返回 API md + referenced_by + other_apis
- 前端: `portalStore` 扩展 "api-doc" view + URL sync
- 前端: `DomainTutorialPage` 右侧面板改为上下文感知 (API 卡片 + Agent + 其他 API)
- 前端: `ApiDocPage.tsx` — API 详情页 (markdown + 相关教程 + 其他 API)
- 前端: `CenterPanel.tsx` 增加 api-doc 路由分支
- 修复: "试一试"/工作流卡片点击后调用 previewTemplate 显示 DAG

## 待验证

- [ ] 浏览器中测试教学页右侧 API 卡片随章节切换
- [ ] 点击 API 卡片跳转到 API 详情页
- [ ] API 详情页底部"相关教程"跳转回教学页

## 下一步

| Phase | 内容 | 状态 |
|-------|------|------|
| Phase 1-3 | 门户首页 + 工作流 + 教学 | ✅ |
| Phase 4 | API 文档页 | ✅ 待验证 |
| Phase 5 | 内容填充 | 未开始 |

## 必读文件

- `docs/portal-redesign/04-api-doc-page.md` — Phase 4 设计文档
