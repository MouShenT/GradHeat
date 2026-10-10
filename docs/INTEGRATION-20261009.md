# Vue / Java / Python 联合验收

独立测试入口是 `tools/integration/verify_application_chain.py`。验收读取当前已提交的招生投影，但不新增、修改招生事实，不切换 publication head，也不保存或改写个人比较。

```powershell
D:/software/python3.12/python.exe -X utf8 -B tools/integration/verify_application_chain.py --live
```

不带 `--live` 会在接触基础设施之前退出。运行前需要构建 Java jar，并在独立 Python 环境安装 `python_service/requirements.txt`。它使用当前私有 `crawler/.env`、`infra/docker/.env`，通过既有严格 HostKeyAlias 的 SSH 连接访问 GradHeat 的 MySQL、RabbitMQ 和 Redis。令牌随机产生，只通过子进程环境传递；不写入提交、报告或命令参数。

临时 Java / Python HTTP 服务、SSH 转发都只绑定 `127.0.0.1` 的空闲端口。测试不启动旧工作台，不操作 Chrome，不请求任何招生官网或社交平台。所有自建进程通过 `finally` / ExitStack 关闭，worker 只取 `analyse.long` 队列的一条消息，每次有明确超时。若分析队列、Java outbox 或 Python event outbox 有原有待执行项目，则直接停止，避免接管其他任务。

## 实际检查范围

- Java 从 MySQL / Redis 读取投影，公共版本头与精确 canonical UTF-8 SHA 相符。
- Python 内部接口拒绝缺少令牌；Java 经内部 HTTP 完成无成绩偏好推荐和有界博弈计算。
- 资料版本过时返回 409；公共投影不含原件地址、原件哈希或会话材料。
- 比较只计算，验证 Python 原 canonical result、archive 和 SHA，以及 Java 解包后的对象一致。
- Java 创建任务与 outbox、Rabbit 持久投递、Python 执行 / 精确结果字节 / 结果 outbox、Rabbit 状态事件、Java inbox / 成功状态、公共任务结果组成真实往返。
- 相同 request_id 返回原任务；同编号改变参数返回 409。
- 重投已完成命令不再产生结果；改变同一任务的 scope 被拒绝进入死信队列。
- 重放相同事件不增加 inbox 行；迟到事件保留 stale 处置且不能回退终态。
- 已发送但尚未执行的任务接受取消请求，worker 在计算前取消，再由事件确认停止。
- 最后核对 publication head 和原有个人比较完全未变，分析队列已清空。

分析任务使用本次新生成 UUID，只留下任务 / 结果 / inbox / outbox 审计记录。故意改变输入的负例保留在 GradHeat 死信队列，测试不删除它。测试日志和真实运行报告位于 `.research/module-integration-20261009/<UTC时间>/`，全部排除 Git；报告不含真实招生正文或凭据。

## 联调发现与处理

第一轮真实跨语言 HTTP 检查发现：直接调用 Python 推荐返回 200，Java 调用返回 503，Python 收到 `Unsupported upgrade request` / `Invalid HTTP request received`。原因是 JDK HttpClient 默认尝试 HTTP/2 明文升级，而当前 Uvicorn 路径未支持该升级。Java 模块已将内部客户端限定为 HTTP/1.1，并增加断言不发送 Upgrade 头的回归测试。

2026-10-09 15:10:25—15:11:06 UTC 的真实联合验收 **42 / 42 通过**。临时服务使用包含 HTTP/1.1 修复的 Java jar，全部自建进程和隧道已关闭。同步 / 异步博弈结果一致，两个分析任务审计保留；负例的一条死信保留，招生发布头及全部原有个人比较未变。完整实际报告保存在上述忽略目录，开发文档仅记录检查结论。

模块的合成测试通过、消息往返通过、Vue 页面通过和长期部署完成分别记录，不互相代替。此入口验证真实业务消息链与 HTTP 契约，页面视觉和交互由单独浏览器验收负责。

## 网站发起采集

tools/integration/verify_collection_ui.py对已经运行的18729工作台上传一个公开官网任务，经过Java冻结单JSON、RabbitMQ、独立Windows Python worker、MySQL原件与结果事件，再用浏览器下载incomplete.json及handoff.zip。2026-10-10 04:11:21 UTC开始的真实检查16/16通过，原件包每项SHA与数据库字节独立读回相符，招生head和个人比较未变。实际报告位于.research/collection-live-acceptance/20261010T041121Z/verification.json，属于忽略的运行材料。

独立合成检查为Python35项、Vue15单元、整站16项与采集页面9项浏览器检查，Java23项；旧工作台131项回归。真实采集仅为有界官网样本，不重新请求待人工社交平台，不说明所有渠道已采完。

页面打开浏览器接口也已真实调用：复用已有四平台标签并调出窗口。HTTP调试连接返回400的路径已改为本机直接读取/json/version返回的可信WebSocket地址；不经过代理、不关闭现有Chrome。Git白名单暂存内容另做全新目录导出，35与131项测试再次通过，并逐件核对SQL暂存字节与已应用文件相同。
