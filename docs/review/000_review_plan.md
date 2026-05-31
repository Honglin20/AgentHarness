# E2E 功能审查计划

**创建时间**: 2026-05-27
**迭代**: Ralph Loop (max 20)

---

## 审查范围

### 第一轮: 用户隔离与数据安全
1. [ ] 前端 user_id 传递链完整性
2. [ ] 后端 API 端点 user 过滤
3. [ ] WebSocket 事件隔离
4. [ ] RunStore 数据隔离
5. [ ] 默认用户回退行为

### 第二轮: Conversation 持久化与隔离
6. [ ] Conversation 创建与存储
7. [ ] Conversation 读取隔离
8. [ ] Conversation 更新权限
9. [ ] 前端切换 history 时 conversation 堆叠问题

### 第三轮: Result 持久化与隔离
10. [ ] Run 结果存储
11. [ ] Run 结果读取隔离
12. [ ] 前端结果展示一致性

### 第四轮: Benchmark 运行与对比
13. [ ] Benchmark 启动流程
14. [ ] Benchmark 运行中 history 检查
15. [ ] Benchmark 结果隔离
16. [ ] Benchmark 对比功能

### 第五轮: 交叉验证
17. [ ] 多用户并发场景
18. [ ] 边界条件测试
19. [ ] 性能与稳定性

---

## 检查方法
- **前端**: 启动 dev server，浏览器测试
- **后端**: 启动 server，curl 命令验证 API
- **日志**: 后端 log 重定向分析
- **代码审查**: 关键路径逐行检查
