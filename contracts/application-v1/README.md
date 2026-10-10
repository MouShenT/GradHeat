# Java/Python application-v1 合同

本目录记录当前 Java/Python 接口与消息合同。实际数据一律不进 Git，运行状态以当前健康检查和本地回执为准。

启动方式见 docs/APPLICATION-RUNBOOK.md；独立前端默认不启动采集 worker，耗时采集需使用明确启用 worker 的启动方式。

## 浏览器只访问Java

基址`/api/v1`，JSON snake_case沿用已实现工作台结构，避免再做一套字段映射。只返回纯数据投影，不含source_url、原件路径/哈希等来源字段。招生年份、口径、待核/缺失及官方对应说明保留。

| Java公开接口 | 行为/对应Python内部接口 |
|---|---|
| GET `/admissions` | MySQL已提交public payload；`X-Data-Version`=64hex版本，仅读，不现场采集 |
| GET `/dashboard` | GET `/internal/v1/dashboard`，现有programme_overview结构 |
| GET `/heat?unit=...` | GET `/internal/v1/heat`，已存样本，只读、有界、缓存与旧时间明确 |
| GET `/school-indices` | 当前每院校热度值和缺失状态 |
| GET `/school-dossier?unit=...` | 单院校重要档案字段，不返回私有原件 |
| POST `/victory-index` | 当前 data_version 和可选个人条件，Python 计算胜利指数 |
| POST `/recommendations` | POST `/internal/v1/recommendations`，同步返回现有discover结果；data_version必填 |
| POST `/game-scenario` | POST `/internal/v1/game-scenario`，同步有界返回simulate结果；新增data_version必填，由wrapper去掉后交算法 |
| POST `/admissions/compare` | POST `/internal/v1/comparisons/evaluate`，Java向页面返回其中result |
| POST `/admissions/comparisons` | 同样evaluate，再Java保存MySQL现有personal_comparison不可变格式 |
| GET `/admissions/comparisons`、`/{id}`、`/{id}/export?format=md/json` | 兼容旧已保存记录、读取/导出原版本 |
| POST `/tasks` | 返回202以及task_id，任务创建+Java outbox同事务 |
| GET `/tasks/{id}` | MySQL状态；前端可先轮询 |
| POST `/tasks/{id}/cancel` | 持久化取消请求，worker协作取消；已存原件保留 |
| POST/GET `/collection/browser` | 本机专用Chrome启动/连接状态；不推断登录，脚本固定，不接受命令参数 |
| POST `/collection/prepare` | 最多5MB单JSON，Python冻结输入，返回batch_id/plan_sha与任务数 |
| GET `/collection/{batch}` | 计数与下载就绪，不返回来源/原件路径 |
| GET `/collection/{batch}/download/{incomplete\|handoff}` | 独立操作下载，只放行固定批次与两种文件，原件不经过MQ |

短计算使用内部HTTP，网络及计算预算固定；较长任务由`/tasks`走Rabbit。错误：422输入/范围无效、409资料版本已改变、404对象不存在、503依赖暂不可用；不能悄悄用新资料覆盖用户所填版本。前端不直连Python/MQ，不要求考研分数。允许后续SSE，当前可靠轮询也可完成首轮联合链路。

## 比较精确字节

Python `/internal/v1/comparisons/evaluate`返回`result`、`report_md`、`canonical_result`、`canonical_archive`、`comparison_id`。canonical_result为现有Python canonical(result) UTF-8文本；canonical_archive为canonical({result,report_md})文本，comparison_id=SHA256其UTF-8字节。Java核对SHA和包装对象一致，再存原canonical_result字节到现有result_bytes，不能通过Java浮点重序列化改变旧结果。Java不重实现评分/渲染公式。

## Rabbit消息

AMQP0-9-1，UTF-8 JSON；commands exchange `gradheat.commands`，events `gradheat.events`。共有字段：`schema_version=1`、message_id、task_id、type、input_version(admissions_publication的64hex SHA)、processor_version、attempt(正整数)、trace_id、created_at、deadline_at。命令参数放在顶层`scope`对象中，不使用payload包装；另算canonical input_sha供worker核对，不能把scope任意改变后仍复用同一个task。processor_version为gradheat-python-v1。queue名为gradheat.加命令type，command routing_key=type，事件queue gradheat.task.status及routing_key task.status。数据库原件/result以SHA引用，消息不放原文件、登录信息或原件请求头。

命令类型：`collect.official`、`collect.social.win-primary`、`collect.autonomous.win-primary`、`extract.documents`、`verify.information`、`analyse.long`。算法scope的`operation`可为recommendations/game-scenario，引用固定data_version与参数。独立采集scope仅为batch_id、plan_sha和retry_platforms，worker验证冻结输入SHA，不能接受任意文件路径；只由Windows采集worker消费。队列prefetch1，社交查询30秒/详情3秒。独立入口登录/验证码/空内容/格式异常记缺口继续；受限平台后续任务未请求，明确确认登录后只做一次有界复查，结束导出同输入格式的incomplete.json。旧collect.social入口仍保留自己的人工暂停规则。

采集控制和操作下载必须有显式授权，或由本机启动器明确启用且请求来自loopback/同源；不能因普通GET可读就开放原件下载。前端只请求Java，Java与Python之间保留内部认证。自动采集不发布事实、不改写个人比较。

状态事件统一`type=task.status`，保留attempt、input_version、processor_version，`sequence`在该attempt内递增（started=1、terminal=2；需要细分进度时单调递增）。顶层包含`status`、`result_id`、`result_sha`、`error_code`等，不使用payload包装。Java仅在attempt/version匹配且sequence更新时更新状态；重复/迟到旧事件去重留痕，不把新任务退回旧状态。

Java owns app_task/app_outbox/app_inbox。Python owns worker_execution/worker_result/worker_event_outbox（表名以Java提供009 DDL为准）。Python不直接更新app_task；执行记录+结果+事件outbox事务后ACK。Rabbit至少一次＋幂等，不承诺exactly-once。

已应用 002—010 迁移保持原字节。两个服务共享字段合同而不共享写入同一任务行。资料发布head本轮仍由既有Python发布器维护。

009含`admissions_publication_bytes`：Python生成和校验不可变规范UTF-8字节，Java核对`SHA256(content)==version_id`并对照MySQL JSON语义。旧投影只校验回填，不改变版本/head。Python结果的`result_bytes`同样在提交后读回并校验，不使用Java重新序列化推测原哈希。

## Git范围

提交源码、合成测试、依赖锁与模板、架构/计划/接口文档。真实招生/社交数据、院校档案、原件、运行产物、导出库、会话/凭据不进入提交。通过完整源码审查和干净副本验证后提交，钩子同步远程；远程更新按快进保护规则处理。
