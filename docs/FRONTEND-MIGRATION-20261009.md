# Vue 前端迁移进度 · 2026-10-09

本模块负责 `frontend/`；Java、Python、统一任务/迁移/部署和 Git 由其他模块与 root 维护。首轮 UI 不是旧静态表格加脚本，已建立可构建的 Vue 3 + TypeScript 组件和路由。

| 事项 | 状态 | 证据/范围 |
|---|---|---|
| 固定依赖与锁文件 | 完成 | Vue 3.5.43、Vite 7.3.1、Node 22.19；npm 元数据及包内许可证核对 |
| 招生计划与列操作 | 完成 | 搜索、选择值、升降序同一浮层，表头固定，未知值两向排序留末尾 |
| 历史、图览、比较、推荐、热度、情景、更新页 | 首轮完成 | 8 个 Vue Router 页面，只访问 `/api/v1` |
| 资料/结果版本与双非未知规则 | 完成 | 不要求初试分数；权重自己指定；双非证据不足不打分 |
| 桌面和窄屏视觉验收 | 完成（合成） | 1440×1000、390×844；全列无横向溢出、手机条件折叠与 sticky 表头 |
| 单元测试与生产构建 | 完成 | 13 tests pass；vue-tsc + vite build；路由与图表延迟加载 |
| 校线 / 院线及名单分组 | 完成（合成验收） | 独立折叠表、年度和范围筛选；5/7 列全显示；拟录取和 retest_pool 复试分组分别标注 |
| 生产依赖审计 | 完成 | 镜像审计 404 后只读切换 npm 官方注册表；本次生产依赖 0 条已知漏洞，开发依赖未计入 |
| Java 对接状态字段 | 完成 | 任务使用 `status`，`paused_human` 为待人工操作 |
| 真实 Java/Python/MySQL 保存/读回和旧记录兼容 | 待联合验收 | 前端请求和输入 shape 已实现；不能用合成验收代替真实数据库验证 |
| Rabbit 长任务全过程与在线入口 | 待联合验收 | 当前短计算同步；任务视图只显示本浏览器记录 |

浏览器验收脚本：`frontend/tests/browser_smoke.py`。当前报告 `.research/frontend-migration-20261009/browser-smoke-report.json`，包含准确 UTC 检查时间、离线/非共享浏览器标志、检查项和接口请求清单。测试不含真实招生或社交数据，运行截图/报告不进入 Git。

视觉截图：`desktop-plans.png`、`desktop-column-filter.png`、`desktop-overview.png`、`desktop-game.png`、`mobile-plans.png`、`mobile-column-filter.png`、`desktop-history-scopes.png`、`mobile-history-scopes.png`。已实际查看桌面与手机截图。来源只留后台，前端展示数据、口径、核对状态和页尾官方说明。

后续补齐独立校线 / 院线和名单分组表，增加 5 个历史范围单测，总计 13 个单元测试和 16 项浏览器验收。校线不作为 11408 证明；科目未知的分组保留未知并可查阅，明确 22408 在 11408 范围下排除。人口类型只接受 API 的 `enrolled` 和 `retest_pool`，未知不猜测；名单提取人数不汇总、不用于复录比，不把复试分数当录取分布。复录比的分母原口径显示在主表状态栏和说明中。

另已对齐异步结果入口：Java任务状态 `status=succeeded` 后单独读取 `/tasks/{id}/result`，不再从状态响应猜测 `task.result`；合成 API 单测覆盖这一顺序。当前推荐 / 情景页仍按共同合同用同步有界算法。

生产入口约 121 kB，ECharts 约 512 kB，图表相关路由才加载；构建仍提示图表 chunk > 500 kB。后续性能验收应使用真实数据集和实际网络，不能拿这次合成结果承诺实时推送或全站热度。

细节、依赖官方链接、许可证与本机开发接入见 [frontend/README.md](../frontend/README.md)。
