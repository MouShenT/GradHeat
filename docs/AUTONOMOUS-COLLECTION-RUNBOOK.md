# 单JSON自动采集：运行与补采

工作目录D:\aaopenclow-share\Graduate_school_selection。执行不需要Codex在线；独立Windows任务在聊天和终端关闭后继续，直接前台CLI会随终端退出，检查点保留。本入口只收集原材料，整理和事实发布在交接之后。

## 从网站开始

确认 Windows 常驻管理任务已运行，打开 http://127.0.0.1:5173/#/tasks 的“信息采集”。点击“爬取 · 打开浏览器”，在四个平台登录；回页面勾选登录确认，选择JSON并点击“开始爬取”。任务通过Java/RabbitMQ交给Windows Python worker执行，关闭网页后继续，保留Chrome和VM。页面可以下载未完成JSON和原材料包，并继续预算内未执行的任务。原件不直接显示在招生表格。

网站和下面的独立CLI共用冻结队列与MySQL。CLI可以在Java/RabbitMQ不在线时运行；不要同时启动两份采集。

## 首次准备

Python3.12安装python_service/requirements.txt；保留已有MediaCrawler及其Python环境、专用Chrome登录会话。contracts/social-collection.json的collector/python/cdp_port指向实际安装；9222的/json/version可达。VM的MySQL、SearXNG和严格SSH按私有contracts/runtime-connections.json配置，保留HostKeyAlias和已信任密钥。密码放忽略的.env，检索JSON不填Cookie或令牌。

公开官网浏览器回退使用本机Chrome，可用GRADHEAT_PUBLIC_CHROME指定路径。GitHub可选环境变量GRADHEAT_GITHUB_TOKEN提高API额度，不输出或归档令牌。独立采集目前为Windows入口，不把Python API镜像当成已部署采集器。

## 一个输入文件

复制config/collection-input.example.json到.research/my-queries.json，编辑tasks。每项一词，四平台分别填写：

```json
{
  "schema_version":1,
  "tasks":[
    {"platform":"official","query":"北京邮电大学 2027 硕士 专业目录","domains":["bupt.edu.cn"],"urls":["https://yzb.bupt.edu.cn/"],"limit":8},
    {"platform":"xhs","query":"北京邮电大学 408 考研 复试","limit":6},
    {"platform":"zhihu","query":"北京邮电大学 计算机 双非 复试","limit":6},
    {"platform":"dy","query":"北京邮电大学 2027 考研","sort":"general","limit":6},
    {"platform":"bili","query":"北京邮电大学 408 拟录取","limit":6},
    {"platform":"github","query":"kaoyan408 in:name,description,readme","limit":3},
    {"platform":"github","repo":"Laz8Noy/kaoyan408-share"}
  ]
}
```

官网纯搜索可省域名，默认教育/科研/研招网域名；其他域名明确填写。多个入口放urls数组。社交当前每词一页、默认6条内容、上限20；更多覆盖用多个关键词。抖音和知乎当前读取正常网页综合搜索，实际排序单独记录；小红书、B站支持general/latest/popular。settings覆盖预算，见示例。

## 开始与原批续跑

```powershell
.\tools\run-collection.ps1 -InputJson .\.research\my-queries.json
```

第一行输出本批目录与任务数，每个任务输出状态。默认8小时有界执行，-Hours 24可调整；-MaxJobs 10先试十项。按输入顺序执行。共享锁拒绝与其他日更/全量采集器并行。

预算耗尽或中断后，用输出的实际批次目录续跑：

```powershell
.\tools\run-collection.ps1 -Batch "D:\aaopenclow-share\Graduate_school_selection\.research\autonomous-collection\batch-实际编号"
```

成功任务跳过；请求已经开始但回执不确定时标记缺口，不自行重发。MySQL故障时原批加-OnlyIngest，仅续传已有原件，不重新搜索。

## 失败后继续与补采

登录、验证码、无正文、非法响应、超时、附件缺失均记录后继续。平台验证后，该平台其他任务标记受限未请求，其他渠道继续。人工正在使用采集浏览器时，不发新社交请求、不等待，任务进入缺口。

回执的 `failure_phase` 区分本机检查、浏览器连接、新页、导航、客户端、搜索与详情。`browser-connection-timeout` 不表示登录失效；即使 `/json/version` 正常，也可能被旧页面初始化拖住。先定位阶段，得到用户授权后仅清理对应旧页，重新打开采集页，保留登录资料和原批证据。网络与解析失败不触发整个平台人工暂停。

知乎改用原生调试连接，只创建并连接本批页面，结束仅关闭该页，不初始化其他标签。读取正常搜索页面实际返回的帖子正文和已公开互动数，排除 AI 搜索摘要，不调用被拒绝的详情接口。搜索内容标为摘录；当前验证范围为综合第一页，额外分页记缺口，其他排序保留实际与请求值。详情拒绝保存在独立限制记录中，不因网络超时或搜索成功清除；搜索本身拒绝或验证仍暂停。

结束生成incomplete.json，包含未完成任务，failure_details注明状态及是否实际请求。先在原Chrome确认对应平台可正常搜索，再补采；原来受限的平台使用-RetryPlatform显式复查。复查仍失败继续记录，不阻塞后续：

```powershell
.\tools\run-collection.ps1 -InputJson "原批目录\incomplete.json" -RetryPlatform xhs,zhihu,dy
```

原批保存成功材料与失败证据，新批不覆盖。不会重跑已完整完成的任务；部分任务重查可能取得重复字节，交接按SHA去重。tasks为空时无需补采。

退出码0=计划材料完整；2=队列处理完但有缺口；3=预算/待续传等尚未结束；1=启动或配置错误。2和3不表示结果未保存。

## 交接

本批含SUMMARY.md、summary.json、incomplete.json、详细missing.json、state.json、冻结输入与计划、各项原件/转录/manifest，以及handoff.zip和public-materials.json。ZIP逐件SHA核对，排除私有会话和日志。

把目录或ZIP交回来后整理、核对、汇总。前端只显示招生数据，不展示原始材料。入库成功和内容完整分别统计；一页搜索或一个仓库不代表全国信息齐全。
## 批内并行

用户已授权不同平台和不同网站并行。`tools/research/collect_parallel_sources.py` 接受 `config/parallel-collection.example.json` 的公开输入结构，实际输入和结果保存在 `.research/`：

```powershell
python tools/research/collect_parallel_sources.py --input .research/parallel-input.json --output .research/parallel-batch --social-workers 3 --website-workers 4 --wait-for-lock
```

一个批次先持有现有全局采集锁，跨平台各自打开采集页面；同平台查询起点间隔至少 30 秒，同网站主机互斥并保留请求间隔。只在主线程写 MySQL。重复运行相同目录复用已冻结原件；校验失败或未完成的社交请求保持待核对，不转成新请求。真实验证限制照常暂停对应平台。批次输出目录输入不可改变，后续新输入使用新目录。

## 多批次有界队列

`tools/research/run_collection_queue.py` 接受 `{"schema_version":1,"batches":[并行输入,并行输入]}`。每批最多 60 项，按院校覆盖优先排序后冻结；实际院校名称、查询和回执仍只放忽略目录。四个平台各有一个串行任务通道，网站默认八个线程，同主机仍串行。队列完成一批并读回数据库后才进入下一批。

```powershell
python tools/research/run_collection_queue.py --input .research/priority-queue-input.json --output .research/priority-queue --hours 8
```

时间预算在批次之间检查，不杀死正在请求或入库的批次。关闭聊天不应终止独立启动的队列；Windows 隐藏进程的 PID 与当前批次记录在输出目录 `runtime.json`，原件和明细在各批目录。只有持有共享锁的子进程执行采集，不启动第二个批次。

完成回执与冻结输入相同才跳过已有批次；中断时若仍有 `current_batch`，再次调用会保留 `needs-review`，先核对已请求材料和原批入库情况，不能自动重新采集。`budget-ended` 可从未执行的下一批继续，`queue-processed` 仅表示队列处理结束，验证码、拒绝、空内容和待核对事实仍是缺口。请求前路径异常记录实际校验根目录和目标路径，保持严格私有输出边界。

深采使用新的冻结输入与输出目录，添加 `--after-queue .research/原队列目录`。后续进程仅等候；必须确认原所有者退出、预算结束或队列已处理、输入和完成回执相符，才取得原共享采集锁开始执行。原队列或后续队列有不确定的已请求批次时均保留待核对，不改写旧输入。待查百度关键词不等同于未请求关键词，服务错误后的不确定请求不自动重发。

## 持续只读监测

```powershell
python tools/research/watch_collection.py --queue .research/priority-queue --output .research/collection-monitor/priority --interval 15
```

监测器独立于采集运行，只读冻结输入、回执和进程生存状态，每15秒原子写入简短本地 `latest.json`。它不访问平台、不修改队列、不写数据库、不重启采集。讨论观测仅统计已提交的批次，搜索的取得与导入分别显示；空结果不是平台完整覆盖。原始关键词、正文、Cookie和路径不进入监测摘要。读取中断保留上次有效进度；15分钟没有新回执或持续无法读取会标记待核对。

消息巡检每5分钟读取实际状态，只在入库或阶段实质完成、新故障重复确认或需要用户操作时通知。正常计数增长、相同故障、已报告版本和采集锁保护状态保持安静。终止状态仍按原回执判断资料缺口，监测不会把进程存在当成功。

# 独立持续采集服务

运行 `tools/start-collector.ps1 -Mode Start -QueueFolder <冻结队列目录列表>` 安装独立 Windows 任务；配置和回执位于 `.research/collection-service/`。`Status` 读取管理进程状态，`Stop` 请求在当前批次结束后退出，`Restart` 在同一边界重启；不会终止当前采集，也不会打开浏览器。关闭聊天不停止该任务，Windows 登录后自动启动。

服务按配置顺序读取各目录已有 `queue.json`，沿用采集锁和单写者。八小时预算结束后从未完成批次接续；处理完所有冻结队列后保持等待，可在私有配置追加新冻结队列，不回头重采。配置或报告不一致、已请求断点、已有活跃所有者均保全现场。CDP 不可用时等待，不把尚未请求的社交任务处理为空样本。后续旧等待器只有在全部前置队列完成、原所有者退出且自身从未启动时才能首次接续。

每15秒监测写入服务 `latest.json`，只读既有运行、取得、入库及发布回执，不调用数据库写入。网页任务状态与常驻队列管理状态分别核对，不把回执的 running 字段当作实际进程存活。

恢复中断批次先核实原 PID 已退出、冻结输入一致，再运行 `collect_parallel_sources.py --recover-only`。该模式仅校验和入库已保存原件，不发送来源请求；缺少完整回执的请求保留为 needs-review。所有入库回执通过后生成带输入 SHA 的恢复报告。只有该报告与任务一一对应、无未核对 running 且原所有者退出，才可用 `run_collection_queue.reconcile_recovered()` 对齐断点；原运行回执另存保留。不要直接删除 current_batch 或改冻结输入。

