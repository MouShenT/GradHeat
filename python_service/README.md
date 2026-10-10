# GradHeat Python 内部服务

API只对Java或管理内网开放；网页只请求Spring Boot。Python复用`workbench/gradheat_workbench`中同一套偏好、历史匹配和拥挤情景实现，没有复制评分公式。生产直接读取MySQL已提交publication并核对canonical SHA，不实例化ResearchRepository、不扫描本地原件才能启动。资料头读取失败返回503；显式冻结文件只用于有SHA的开发/验收。

安装独立环境（不改变MediaCrawler `.venv`）：

```powershell
D:/software/python3.12/python.exe -m venv python_service/.venv
python_service/.venv/Scripts/python.exe -m pip install -r python_service/requirements.txt
$env:PYTHONPATH = "$PWD/python_service"
# 从私有配置设置DB/Rabbit/GRADHEAT_INTERNAL_TOKEN，不把令牌写在命令历史。
python_service/.venv/Scripts/python.exe -m gradheat_python.api
```

默认内部端口18730，Java默认18729。API要求`X-GradHeat-Internal-Token`且令牌至少32字符；没有令牌配置直接拒绝启动。`/health`只检查进程；`/internal/v1/ready`验证MySQL资料，不能用health当数据库就绪。

| 内部接口 | 输入/输出 |
|---|---|
| GET `/internal/v1/admissions` | 已提交投影、X-Data-Version |
| GET `/internal/v1/dashboard` | 可视化投影；缺少已审核背景证据时未知 |
| GET `/internal/v1/heat?unit=...` | MySQL bounded样本、60秒缓存；旧缓存保留旧时间 |
| POST `/internal/v1/recommendations` | 现有DiscoveryInput，必填data_version，无成绩要求 |
| POST `/internal/v1/game-scenario` | 现有ScenarioInput＋必填data_version，假设容量，不产概率 |
| POST `/internal/v1/comparisons/evaluate` | 比较结果、报告、精确canonical_result/canonical_archive、SHA |

一般写请求有200KB预算，采集JSON上传为5MB；模型限制候选数、参与人数、步数和非有限数。同步版本变更409，不悄悄更换用户输入版本。异步任务读取命令指定的不可变publication，当前head更新不改变该任务输入，也不会自行切换发布头。

AMQP worker（009由Java统一迁移；本模块不自动改表）：

```powershell
python_service/.venv/Scripts/python.exe -m gradheat_python.worker
# 联调只取一个命令，之后发布已提交结果事件：
python_service/.venv/Scripts/python.exe -m gradheat_python.worker --once
# 单独部署结果outbox发布器：
python_service/.venv/Scripts/python.exe -m gradheat_python.worker --publisher-only
```

连接采用Pika1.3.2，一个连接只被所属线程操作；耗时工作交给单线程执行器，消费者线程继续处理心跳，每15秒刷新MySQL租约。prefetch1、持久队列、manual ACK、持久结果事件outbox、publisher confirms与mandatory。消息scope只放公共参数/SHA，禁止Cookie、请求头、签名、账户信息。Java owns `app_task`状态；Python只写`python_worker_execution/result/event_outbox`，事件attempt＋sequence由Java去重/拒绝迟到更新。队列均配置deadletter；非法消息不自动重放。

执行键包含task_id、资料版本、processor版本与attempt；另核对input_sha，命令还只读核对Java任务账本scope。完成、失败或待人工先存结果精确字节并独立读回，提交终态outbox后才ACK。重复终态再次核对已存结果SHA/outbox，不重跑处理器。提交或读回故障不ACK，重投从原检查点恢复；不承诺exactly-once。

五类任务scope见`docs/PYTHON-SERVICE-20261009.md`。普通VM进程可运行解析/核对/分析；Windows专用checkout保留现有采集资料登记与Chrome9222。官网/社交采集保留本地冻结检查点，同时将公共原件字节写MySQL；不能把本地成功当已入库。社交任务不解除暂停、不触发登录，也不重启冻结全量队列。

新增第六类collect.autonomous.win-primary，复用独立单JSON采集器；本机启动器单独运行该worker与analyse.long worker。scope只引用冻结batch_id/plan_sha，运行不调用语言模型。网站的collection内部接口启动固定浏览器登录脚本、接收JSON并返回计数；任务登录/验证失败及格式异常记缺口后继续，明确retry_platforms只复查一次，原件包不塞进消息。CLI、页面和恢复说明见docs/AUTONOMOUS-COLLECTION-RUNBOOK.md与docs/APPLICATION-RUNBOOK.md。

```powershell
D:/software/python3.12/python.exe -X utf8 -B -m unittest discover -s python_service/tests -v
```

本模块的合成验收与真实MySQL/Rabbit联合验收分开记录。浏览器采集与全量资料完备不能由消息样例通过来证明。
