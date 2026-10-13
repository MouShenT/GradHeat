# 单JSON自动采集：运行与补采

工作目录D:\aaopenclow-share\Graduate_school_selection。执行不需要Codex在线；关闭启动终端会结束进程，检查点保留。本入口只收集原材料，整理和事实发布在交接之后。

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

