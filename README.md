# GradHeat

计算机考研择校应用：招生计划、历年录取、院校档案、热度值与个人胜利指数。目标科目为 101 / 201 / 301 / 408，支持学硕、专硕和个人条件稍后填写。

## 当前结构

| 目录 | 职责 |
|---|---|
| frontend/ | Vue 3、TypeScript、Vite，表格、图表与个人条件 |
| backend/ | Spring Boot，统一 /api/v1、比较档案与消息事务 |
| python_service/gradheat_python/ | 内部 API、独立采集、worker 与院校数据库 |
| python_service/gradheat_core/ | 语义匹配、共享算法、热度与胜利指数 |
| crawler/ | 原件归档、迁移、核对与资料发布 |
| tools/application/ | 独立开发服务 |
| tools/research/ | 当前流程所需采集、解析和恢复 |
| tools/release/ | 源码审查、干净副本验证、双向仓库同步 |
| infra/、contracts/ | 基础设施模板与接口约定 |

旧网页已退役，各模块共用一套算法。真实材料、数据、日志、生成查询和凭据留在本地忽略目录与 MySQL。

## 运行

准备 Node、Java 21+、Python 3.12、Maven，以及私有数据库连接和已信任的 SSH 配置：

```powershell
python -m pip install -r python_service/requirements.txt
.\tools\build-application.ps1
.\tools\start-frontend.ps1
```

开发页面：<http://127.0.0.1:5173/>。Windows 独立管理服务；前端保存源码热更新，关闭聊天或 Codex 不停止。见[运行手册](docs/APPLICATION-RUNBOOK.md)和[前端管理](docs/FRONTEND-DEV-SERVICE.md)。

热度综合公开讨论与实际搜索。搜索缺失时保留讨论估算状态。胜利指数结合个人条件和院校资料，为参考指数，见[算法说明](docs/ALGORITHMS.md)。院校档案独立存储，来源与原件留在后台。

采集可上传 JSON，或运行 tools/run-collection.ps1。已有任务先完成，后续排队，完整原件不重采。见[采集手册](docs/AUTONOMOUS-COLLECTION-RUNBOOK.md)。

## 开发与同步

```powershell
python -m unittest discover -s python_service/tests
npm.cmd --prefix frontend test
python tools/release/stage_code.py --stage
python tools/release/verify_code_checkout.py
git commit -m "业务变化"
```

本地提交审查后推送 main。独立服务每 15 分钟检查远程，工作目录干净且可快进时验证新版本，再更新运行服务；未提交修改保护现场。见[仓库同步](docs/REPOSITORY-SYNC.md)。

[当前状态](docs/STATUS.md) · [后续任务](docs/TASKS.md) · [架构](docs/ARCHITECTURE.md) · [任务约定](AGENTS.md)
