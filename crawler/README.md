# GradHeat 采集层

11408 院校数据的采集工具。当前边界见 [架构 v0.2](../docs/DESIGN.md)，待修复项与验收见 [执行流程](../docs/WORKFLOW.md)。代码注释中的“机制 9”等历史编号对应 [v0.1 归档](../docs/archive/DESIGN-v0.1.md)，不代表新版流程已全部接入。

## 为什么不用 Scrapy（暂时）

> 2026-09-23 修正：下面是初始试点的历史选择理由。静态页面同样可受益于 Scrapy 的调度与去重；是否引入 Scrapy 不取决于是否需要 JS。当前按 [采集方案评审](../docs/ARCHITECTURE-REVIEW-2026-09-23.md) 决定：小样本沿用现有实现，多站点常态采集优先评估 Scrapy，Playwright 独立按需启用。并非所有学校页面均已验证为纯服务端渲染。

研招网 `/sch/` 与各校研究生院页面**都是服务端渲染**，不需要 JS 执行 ——
用 `requests` + `lxml` 足够。Scrapy/Playwright 留给确需渲染的场景（如动态加载的专业目录）。

引入框架的代价（并发调度、去重、中间件）在这个阶段大于收益。
**当出现第一个必须执行 JS 才能拿到数据的源时再引入 Playwright。**

## 目录

```
crawler/
├── gradheat/
│   ├── net.py        HTTP 客户端：显式代理控制、限速、重试
│   ├── store.py      落盘：JSONL + fetched_count 元数据
│   └── yz.py         研招网解析器
├── run_school_list.py   入口：抓取院校基础清单
└── data/                输出（已 gitignore）
```

## 环境

复用本机 Python 3.12（`requests` / `lxml` / `pymysql` 已装）。

## 代理纪律（机制 9 ⑪⑫）

宿主机环境变量里有 `HTTP_PROXY=http://127.0.0.1:7897`。
**采集器不继承环境变量** —— 国内站点（研招网、各校 .edu.cn）必须直连。

`net.py` 的 `Session` 默认 `trust_env = False`，代理只能显式传入。
每次运行先打印出口 IP 自证（`preflight`），不信任配置文件。

## 运行

```bash
python run_school_list.py
```
