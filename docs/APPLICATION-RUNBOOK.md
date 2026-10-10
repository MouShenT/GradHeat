# 本机正式工作台：启动与采集

Vue生产资源打进Spring Boot jar，同源提供页面与/api/v1。Python内部API和RabbitMQ worker由本机启动器管理；MySQL、Redis、RabbitMQ、SearXNG在已有虚拟机。Windows专用Chrome留在本机，不能搬到无桌面的VM使用本机登录资料。

## 构建

Java21+、Maven、Node和Python3.12；先安装python_service/requirements.txt。然后在项目根目录：

```powershell
.\tools\build-application.ps1
```

先Vue测试和生产构建，再Maven verify。未构建Vue时Java打包明确失败，不发布空前端。node_modules、dist、target均忽略，不提交运行产物。002—009已经应用的SQL不可改写，Git对这些文件保留确切字节。

## 连接与启动

私有contracts/runtime-connections.json填写VM主机、用户、HostKeyAlias；可复制example模板。保持严格SSH主机密钥校验。私有infra/docker/.env与crawler/.env使用现有轮换后的密码，不入Git。启动器用只绑定127.0.0.1的临时SSH端口，内部认证令牌仅进子进程环境。

```powershell
.\tools\start-application.ps1
```

保留终端和虚拟机。入口默认http://127.0.0.1:18729/，内部Python18730。Ctrl+C只关闭本次子进程和隧道，不关闭用户Chrome、不停VM数据库。本机启动器显式启用本机写操作；远程部署必须另外配置访问认证，不能直接开放本机采集控制。

默认有analyse.long和collect.autonomous.win-primary两个独立worker；算法不会被长时间采集占用。--no-worker仅用于API检查，页面任务会等待消费者。运行状态在.research/application-runtime/runtime.json，原件与私有日志均留本地忽略目录。

## 页面采集

进入“信息采集”。

1. 点击“爬取 · 打开浏览器”，程序在本机调出小红书、抖音、知乎和B站。已有会话和标签保留；不会关闭用户浏览器。
2. 在浏览器登录并确认可正常搜索，勾选“我已登录，确认平台可以搜索”。调试连接可达仅表示浏览器可连接，不由程序推断已登录。
3. 选择JSON，页面检查格式和任务数；点击“开始爬取”。服务器先冻结完整输入，RabbitMQ只发batch_id/plan_sha引用，文件不塞进消息。
4. 页面5秒读取任务与采集进度。关闭网页不停止后端任务；本机服务、Chrome和VM应保留运行。
5. 登录/验证、内容为空、格式异常均记录后继续其他任务；受限平台后续记未请求。结束可下载incomplete.json和handoff.zip。预算到期可点“继续未执行任务”，成功原件不重采。

采集控制和下载仅向本机已启用工作台或显式授权请求开放。招生页面仍隐藏资料来源；操作页的原材料包专门用于用户后续整理。采集不会自动发布招生字段或改写个人比较。

输入格式、补采和独立CLI见AUTONOMOUS-COLLECTION-RUNBOOK.md。日志错误不会作为公开正文归档，原件字节先保存再通过SHA读回核对。

## 验收

Python单元与合成恢复、Java事务/消息/HTTP、Vue单元与隔离浏览器分别检查。tools/integration/verify_application_chain.py验证真实分析链；tools/integration/verify_collection_ui.py对已运行的新工作台上传一个有界官网任务，验证实际消息、原件入库、浏览器下载及数据库字节。

2026-10-10采集页面真实验收16/16通过，只取一份公开官网材料，保留审计与原件；没有重发社交验证，也没有改动招生head/个人比较。采集页面合成9项与整站合成16项分别通过。历史分析链42项通过，不能把这些数字叫作全平台资料完备。
