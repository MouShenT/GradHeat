# GradHeat

> 11408 考研院校专业热度评估与择校分析平台

多维度评估 11408（政治 + 英一 + 数一 + 408）相关考研院校/专业的热度，以网站形式呈现。

**核心原则：承认数据缺失，用可量化的方式表达可信度，而不是假装数据完整。**

## 文档

- [设计方案](docs/DESIGN.md) —— 维度框架、技术选型、架构、真实性保障机制
- [相似项目调研](docs/PRIOR-ART.md) —— 开工前的同类项目/工具调研与可用性验证结论

## 开发前置规则

**任何模块开工前，先查 GitHub 上有没有同类项目或可用工具，验证其可用性与可靠性（活跃度、核心假设是否仍成立、许可证），结论写入 [docs/PRIOR-ART.md](docs/PRIOR-ART.md)。**

不因为 star 多就采用，也不因为小众就忽略 —— 看的是①能不能用、②还能不能用、③许可证允不允许。

## 目录结构

```
├── backend/          Spring Boot 服务（Java 17）
├── crawler/          Python 爬虫（Scrapy + Playwright）
├── web/              前端（Vue 3 + TypeScript + ECharts）
├── infra/docker/     基础设施（MySQL / Redis / RabbitMQ）
└── docs/             设计文档
```

## 技术栈

| 层 | 选型 |
|----|------|
| 前端 | Vue 3 + TypeScript + Vite + Element Plus + ECharts |
| 后端 | Spring Boot 3.2+ + Java 17/23 + MyBatis-Plus |
| 存储 | MySQL 8.0 / Redis 7 |
| 消息 | RabbitMQ 3.13 |
| 采集 | Python + Scrapy + Playwright |

> 本地实测环境：Java 23.0.1 / Maven 3.9.9 / Python 3.12.5 / Node 22.19.0。
> **Java 23 要求 Spring Boot ≥ 3.2**（3.2 起才支持 Java 22/23），不要用 2.x。

## 环境

基础设施部署在 Kali VM（`192.168.43.150`）。**存储/中间件跑 Docker，需要出网的采集/搜索服务跑宿主机** —— 容器不配代理（它们都是内网服务），出网任务直接用宿主机已有的 mihomo（`127.0.0.1:7890`）。

```bash
# 启动基础设施（Docker：MySQL / Redis / RabbitMQ）
ssh ms@192.168.43.150 "cd /opt/gradheat/infra/docker && docker compose up -d"

# 本地开发隧道
ssh -N -L 13306:127.0.0.1:3306 -L 16379:127.0.0.1:6379 -L 15673:127.0.0.1:15672 -L 18890:127.0.0.1:8890 ms@192.168.43.150
```

详见 [infra/docker/README.md](infra/docker/README.md)。

### SearXNG（全网搜索）

自建元搜索，跑在 Kali 宿主机上（`systemd` 服务 `searxng`，监听 `127.0.0.1:8890`），出网经 mihomo —— mihomo 是 `mode: rule`，**国内域名直连、境外走隧道**，已实测（百度 0.25s、清华 0.85s、Google 约 3.4s）。

```bash
# JSON API（开发用；HTML 前端可用上面的隧道 18890 打开）
curl -G 'http://127.0.0.1:8890/search' \
  --data-urlencode 'q=西安电子科技大学 计算机 拟录取名单' \
  --data-urlencode 'format=json'
```

配置：`/opt/gradheat/searxng-config/settings.yml` ｜ 服务：`/etc/systemd/system/searxng.service`

**引擎实测状态（2026-09-18）**：

| 引擎 | 状态 | 说明 |
|------|------|------|
| `google cse` | ✅ 稳定 | 走官方 API，不受 IP 风控影响，是主力 |
| `brave` | ✅ 可用 | 直接抓取 |
| `bing` | ✅ 可用 | 直接抓取（需显式指定 `engines=bing`） |
| `google` | ❌ CAPTCHA | 代理 IP 被 Google 标记 |
| `duckduckgo` | ❌ CAPTCHA | 同上 |
| `baidu` | ❌ 302 验证 | 需真实浏览器种下的 BAIDUID cookie，与代理无关（直连同样被挡） |

> ⚠️ **配置这两个坑必须避开**（已处理）：`search.formats` 不加 `json` 会让 JSON API 返回 **403**；`limiter` 必须关闭。

## 状态

Phase 0 准备中 —— 详见 [设计方案](docs/DESIGN.md) 路线图。