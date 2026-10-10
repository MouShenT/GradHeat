# GradHeat

面向计算机考研的招生资料、院校比较和偏好情景工作台。目标初试科目为101政治、201英语一、301数学一、408计算机基础，兼容学硕与专硕。

## 应用架构

| 模块 | 职责 |
|---|---|
| `frontend/` | Vue 3、TypeScript、Vite、ECharts；招生表、筛选排序、历史图表、院校对比、热度样本、无成绩偏好推荐、博弈情景 |
| `backend/` | Spring Boot业务主服务；统一`/api/v1`、MySQL资料读取、不可变比较档案、任务状态、消息outbox/inbox |
| `python_service/` | FastAPI内部算法接口、Python任务worker；复用采集、语义核对、推荐与拥挤情景算法 |
| `crawler/` | 官网与公开资料的采集、原件字节入库、审核后投影发布 |
| `workbench/gradheat_workbench/` | 当前共享的比较、语义核对与情景算法；旧工作台保留以支持渐进迁移 |
| `infra/` | MySQL、Redis、RabbitMQ和检索基础设施模板 |

浏览器只调用Java业务接口。短计算由Java调用Python内部HTTP，耗时任务通过RabbitMQ执行；MySQL保存原件、版本和结果，Redis为可重建缓存。受限平台后续查询记录未请求，其他任务继续，不重复采集已有完整原件。

信息采集页面支持打开本机专用Chrome及四个平台、确认登录、上传一个JSON后通过RabbitMQ启动独立Python采集。登录/验证码、空内容和异常格式记录后继续其他任务，结束下载未完成JSON和公共原材料包。也可直接运行tools/run-collection.ps1；见[采集说明](docs/AUTONOMOUS-COLLECTION-RUNBOOK.md)和[应用启动说明](docs/APPLICATION-RUNBOOK.md)。

具体状态见[逐项实施计划](docs/IMPLEMENTATION-PLAN-20261009.md)，接口和消息格式见[应用契约](contracts/application-v1/README.md)，模块说明见[前端](frontend/README.md)、[Java](backend/README.md)、[Python](python_service/README.md)。

## 数据与解释

招生信息按院校、院系、专业、年份、学习方式和录取人群核对。两个独立来源链语义一致即可取消对应信息的待核标记；转载与fork不能额外投票。来源留在后台，页面仅展示数据、口径、缺失及核验状态。

推荐支持不填初试成绩；偏好得分不是录取概率。双非友好度只能来自范围明确的规则或证据，不根据院校层次推测。平台热度展示有时间、查询与样本范围的公开样本，不等于全站热度或报名人数。博弈页使用有界的假设偏好和拥挤参数，结果为情景分析。

## 开发与提交

只提交业务、算法、采集与前端源码、依赖锁、配置模板、合成测试和开发文档。真实招生资料、社交样本、原件、院校档案、数据库导出、运行日志和凭据保存在本地与MySQL，不进入Git。

配置模板中的密码和服务令牌须由本机私有环境提供；不要提交`.env`。数据库增量迁移不得使用旧的全量清库脚本。开发检查和联合测试步骤记录在各模块README及实施计划中。

研究规范和早期架构见[资料核验政策](docs/RESEARCH-EVIDENCE-POLICY.md)、[历史设计](docs/DESIGN.md)。
