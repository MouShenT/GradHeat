# 独立前端开发服务

固定地址：<http://127.0.0.1:5173/>。Vite 直接读取 `frontend/src`，保存 Vue、TypeScript、CSS 文件后通过 WebSocket 热更新；Java 的静态构建页不是开发入口。

`tools/start-frontend.ps1` 安装当前 Windows 用户的登录启动任务，并立即启动。服务由 Windows 任务计划程序管理，不依赖 Codex、聊天任务或终端；任务没有运行时长上限，进程意外退出会自动恢复。前端只监听本机地址，端口被占用时不会偷偷换网址。服务准备好后打开默认浏览器，登录 Windows 后也会启动并打开网页。

同一管理进程保持 Java 18731、Python 18732 和私有 SSH 转发运行，API 请求通过 Vite 代理。使用已验证的独立 Java 构建；后续构建可通过 `-JarPath` 指定，后台构建指针校验 jar 的 SHA。Java/Python 修改需重新构建或重启，前端源码自动热更新。该服务不启动采集 worker，不争用采集浏览器。

管理进程每 15 分钟检查已授权 GitHub `main`。新源码先从无数据副本测试和构建，再快进更新并重启专属 API；Vite 继续热更新。本地修改、分叉、采集锁或验证失败会保留现场。提交后的推送钩子失败可由后续检查重试，见 `docs/REPOSITORY-SYNC.md`。

```powershell
# 首次启动 / 已运行时不会重复创建进程
.\tools\start-frontend.ps1
# 查看 Windows 任务及服务状态
.\tools\start-frontend.ps1 -Mode Status
# 重启前端和专属 API
.\tools\start-frontend.ps1 -Mode Restart
# 停止服务，同时禁用下次登录自启
.\tools\start-frontend.ps1 -Mode Stop
```

也可双击 `tools/打开前端.cmd`。配置、状态和服务日志在忽略目录 `.research/frontend-dev/`；后台基础设施详细日志仍在 `.research/application-runtime-18731/private.log`。关闭浏览器标签不停止服务。计算机关机期间服务暂停，下次登录恢复。

2026-10-10 实测：控制命令结束后服务仍由 Windows 的 `svchost.exe` 启动链持有；Vite 客户端、页面和代理后的招生 API 均返回 200。临时添加 CSS 自定义属性，浏览器直接读到新值，删除后立即恢复，`performance.timeOrigin` 全程未改变，原文件字节校验一致。停止服务后三个专属端口全部释放。前端类型检查与生产构建通过。冷启动的 Java/API 预热保留 180 秒等待预算，避免系统繁忙时反复启动。
