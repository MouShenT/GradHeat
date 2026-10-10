# 应用运行

需要 Node、Python 3.12、Java 21+、Maven。安装 python_service/requirements.txt；前端 npm ci。可选真实百度指数使用 tools/research/requirements-search-index.txt 的固定 SDK，Cookie 私有保存。

复制 contracts/runtime-connections.example.json 到本机私有 runtime-connections.json，配置已信任 VM、SSH 用户与 HostKeyAlias。infra/docker/.env 使用私有数据库、缓存与消息凭据。保持严格 SSH 校验，私有文件不进入 Git。

```powershell
.\tools\build-application.ps1
.\tools\start-frontend.ps1
```

当前开发地址 <http://127.0.0.1:5173/>。Vite 代理 Java 18731，内部 Python 18732；Windows 任务管理服务，前端热更新。状态与控制见 FRONTEND-DEV-SERVICE.md。后台构建采用已验证 jar；Java 修改需构建后部署，Python修改需重启内部服务，前端修改即时生效。

独立开发服务默认不启动采集 worker，避免重复浏览器任务。页面读取资料、个人胜利指数和热度直接经 Java→Python。需要网页异步采集时，用 start-application.ps1 在另一组端口启动包含 analyse.long 和 collect.autonomous.win-primary 消费者的业务实例，并显式配置 Vite 代理到该实例；也可直接使用独立采集 CLI。

网页采集支持四平台浏览器、人工确认登录、JSON 上传、任务进度及 incomplete.json/handoff.zip 下载。没有消费者时任务等待，不能把排队当已执行。正常采集方式、限制与恢复见 AUTONOMOUS-COLLECTION-RUNBOOK.md。

发布使用 code-only 白名单和干净副本检查，不修改已应用迁移、不全量清库。远程更新和常驻服务保持分离，见 REPOSITORY-SYNC.md。
