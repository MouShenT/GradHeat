# 双向仓库同步

仓库 `https://github.com/MouShenT/GradHeat`，发布分支 `main`。用户已授权业务提交推送及远程更新。

本地设置 `core.hooksPath=.githooks`。提交后调用 `sync_repository.py push`，审查完整提交树和未推送提交，确保没有本地数据或已知私有值，再快进推送。不强推，失败保留本地提交并写回执。

独立开发管理进程每 15 分钟调用 `sync_repository.py pull --deploy`，后台数据服务未就绪时仍执行仓库检查。仅获取固定仓库 `main`；本地修改、分叉、采集锁占用或验证失败时保留现场。新版本从无数据副本检查和构建，通过后快进，并更新专属后台构建，不清库、不启动采集。

常驻管理服务重启而 API 尚在启动时，若同一版本的受管安装产物仍通过路径和字节校验，只检查仓库状态，不重复构建该版本。仓库已同步与服务真正就绪分别检查；坏校验和或受管目录外的产物不能复用。

```powershell
python tools/release/stage_code.py --stage
python tools/release/verify_code_checkout.py
git commit -m "业务变化"
python tools/release/sync_repository.py pull --deploy
Get-Content .research/repo-sync/latest.json
```

Git 使用现有凭据管理器，私有连接和日志不提交。首次启用钩子：`git config core.hooksPath .githooks`。后台只同步已提交源码，不自动加入工作目录。

最新状态保存在 `.research/repo-sync/latest.json`，推送回执另存 `push.json`；部署版本在 `.research/frontend-dev/runtime.json` 的 `backend_source_sha`。已配置每5分钟的采集与仓库巡检，只在实质更新或新持续故障时通知，不额外启动同步进程；源码接收仍由独立服务每15分钟执行。钩子暂遇已有操作会延期，后续独立检查重试已提交业务版本。采集锁占用时更新延期，本地修改或分叉必须保留并处理后再同步。
