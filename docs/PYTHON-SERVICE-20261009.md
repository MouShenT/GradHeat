# Python 内部服务与采集/算法worker实现

2026-10-09。本模块已经实现可运行Python服务与AMQP适配，合成验收15项通过；真实MySQL/Rabbit业务联合链路由root及模块测试agent另行执行和记录。本记录不声称采集全量完备，也没有自动启动新采集批次。

`python_service/gradheat_python/api.py`直接从MySQL publication起服务；没有ResearchRepository依赖，没有D盘原件也可运行。Dashboard复用现有同事项/历史口径；可选本地已审核规则插件不存在时，背景友好仍未知，不给未知加分。背景证据的独立MySQL读取投影尚未移交，不把这个缺口填成友好。

## 任务与边界

命令processor_version为`gradheat-python-v1`，input_version为已保存publication SHA，scope内容另算input_sha。命令必须匹配Java拥有的task行；新attempt有独立执行记录，既有终态/原件不可被覆盖。

| type / queue后缀 | scope | 行为 |
|---|---|---|
| analyse.long | operation、input；operation为recommendations/game-scenario/compare/dashboard/heat | 直接复用现有算法；命令固定版本，不自写另一套公式 |
| extract.documents | sha256、format(pdf/html/text)、max_pages≤200 | 读取MySQL完整原件，字节/SHA/分块复验后候选转录，≤20MB原件/800000字符，不宣称图片或表格已审核 |
| verify.information | observation_ids≤400 | 只接受该publication的consensus_run active IDs；补入相同单位的活跃观察，包括冲突，而非挑选相同数值；调用现有Corroborator |
| collect.official | items≤12（unit/url/title/year）；或者resume_batch | 核对登记的院校域、公共地址、有界请求；存原件和原URL观察账本，不升级招生事实 |
| collect.social.win-primary | units≤2、platforms、limit≤3、worker=win-primary；或resume_batch | 只在Windows消费；各unit/platform单查询串行，至少30秒间隔，详情仍由原采集器3秒；仅已解除的平台请求 |

官网首次任务文件夹确定为app＋execution SHA。重投发现sources/summary完整时只入库；不完整则恢复已冻结URL metadata的原件，记录需人工恢复，绝不重新请求不明的崩溃点。显式storage resume要求原summary/manifest完整。原件路径必须属于该批，原件实际SHA必须一致。

社交`collect_social_sources.run`新增可选run_id_override，默认每日执行保持原行为。worker传确定性app执行标识：已有manifest只调用原resume；目录存在但manifest缺失拒绝重采。worker持原full-run OS锁，避免与冻结全量/日更同时占浏览器；保留Chrome、人工页面与每个平台暂停状态。原件续传允许在暂停期间进行。验证码产生paused_human终态及事件后ACK；没有任何自动清pause、验证码突破或旧签名重放。

## 存储与消息恢复

Java owns app_task/app_outbox/app_inbox；Python owns python_worker_execution/result/event_outbox。009新增表由Java统一维护。Worker结果同时存JSON查询投影与canonical UTF-8 result_bytes，result_sha由精确字节计算，避免MySQL JSON浮点标准化破坏复验。

租约120秒、每15秒续期；同execution有效租约不会被抢走。事务写结果＋terminal事件outbox后独立连接读回结果字节再ACK。提交后ACK前退出，下一次重投核对终态结果/outbox后直接复用。网络/存储故障保留未ACK消息与冻结批次；不把local-only/待续传说成入库。事件发布持MySQL advisory lock，confirmed且mandatory无未路由返回才提交sent；确认后DB提交前故障可重复发布，由Java inbox/attempt/sequence兜底。

消息拓扑为durable direct gradheat.commands、gradheat.events、gradheat.deadletters。五个gradheat.任务队列与gradheat.task.status各配置对应gradheat.dead.死信队列。死信需要审查或明确新attempt，不自动当正常空结果。Pika连接仅单线程使用；handler在执行器，消费者继续process_data_events。停止/取消为协作方式，运行中的一次有限HTTP/文档操作完成后归档已有原件再返回，不能声称立即杀掉远程请求。

## 合成验收证据

命令：`D:/software/python3.12/python.exe -X utf8 -B -m unittest discover -s python_service/tests -v`。

15项涵盖：无原件目录仍起API、内部认证拒绝缺失token、纯偏好无成绩/无友好推断、版本409、明确非11408排除、拥挤假设不产概率、比较精确字节兼容、原件版本SHA篡改拒绝、200KB预算、ACK只在提交及读回后、数据库故障不ACK、重复投递不重处理、验证码持久paused后ACK、poison路由死信、同execution输入SHA变化识别、确定性社交检查点只续传和缺manifest不重采。

这组测试使用合成资料及受控接口/账本替身；没有写真实数据库，没有访问用户Chrome，没有现场爬取平台。真实MySQL lease/SQL隔离、Rabbit确认、Java状态消费和部署进程必须联合实测后才能把首轮链路标完成。

## 官方依据

[Pika连接与跨线程说明](https://pypi.org/project/pika/1.3.2/)要求连接适配器按单线程操作，耗时处理应让所属线程继续维护I/O。项目遵循该约束并固定已核版本；没有把当前latest文档的额外功能当1.3.2实测结果。

[RabbitMQ确认说明](https://www.rabbitmq.com/docs/confirms)区分消费者ACK与生产者确认；项目在持久结果后ACK，并将结果事件确认与DB outbox提交分开，接受可能重复而以幂等消化。文档解释协议，不代替本项目真实故障联调。
