# Current Task

**当前任务**: (无)
**状态**: idle

---

## 上一任务

修复 replay 数据丢失(Bug A 刷新后 history 空白 + Bug B replay 显示少)
完成时间:2026-05-30
方案:抽出共享 `routeEvent`,删除 `WorkflowScope` reset 副作用,reset 责任下放到数据写入入口
详情:`docs/status/CHANGELOG.md` 2026-05-30 条目
