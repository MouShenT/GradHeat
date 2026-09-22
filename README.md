# GradHeat

> 11408 考研院校专业热度评估与择校分析平台

围绕 11408（政治 + 英一 + 数一 + 408）择校，建立原始证据、竞争池事实、历史描述、个人适配与情景比较的可追溯流程。网站与 API 尚待实现。

**核心原则：证据质量、数据完整度与预测不确定性分别表达；未验证的概率不发布。**

## 文档

- [社交平台采集项目选型](docs/SOCIAL-COLLECTOR-SELECTION.md) —— MediaCrawler 首轮试点、专项备用与可靠性验收
- [多平台热度方案](docs/HEAT-SIGNALS.md) —— 小红书、抖音、B站、知乎的获取边界、指标和采样偏差
- [架构、择校与爬虫方案评审（9 月 23 日）](docs/ARCHITECTURE-REVIEW-2026-09-23.md) —— 选型结论、真实官网样本、可靠性与效率验收
- [本地搜索工具配置](docs/SEARCH-SETUP.md) —— MCP、研究技能、虚拟机后备检索及实测状态
- [研究证据规范](docs/RESEARCH-EVIDENCE-POLICY.md) —— 来源追溯、量化验证与博弈论适用条件
- [择校决策审查](docs/DECISION-REVIEW.md) —— 从信息获取到决策的改进建议
- [当前架构 v0.2](docs/DESIGN.md) —— 模块边界、竞争池、版本化事实与发布能力
- [执行流程](docs/WORKFLOW.md) —— 状态机、实施工作包、验收与恢复
- [发布数据契约](contracts/README.md) —— 可运行的清单检查及适用限制
- [相似项目调研](docs/PRIOR-ART.md) —— 开工前的同类项目/工具调研与可用性验证结论

## 开发前置规则

**任何模块开工前，先查 GitHub 上有没有同类项目或可用工具，验证其可用性与可靠性（活跃度、核心假设是否仍成立、许可证），结论写入 [docs/PRIOR-ART.md](docs/PRIOR-ART.md)。**

不因为 star 多就采用，也不因为小众就忽略 —— 看的是①能不能用、②还能不能用、③许可证允不允许。

## 目录结构

```
├── crawler/          Python 采集与导入（requests + lxml）
├── contracts/        发布清单 schema 与合成样例
├── tools/research/   本地研究工具
├── tools/architecture/ 发布清单校验器与测试
├── infra/docker/     MySQL / Redis / RabbitMQ 配置
├── infra/search/     虚拟机后备搜索与证据留存
└── docs/             当前架构、执行流程、研究规范与历史归档
```

## 技术栈

| 层 | 选型 |
|----|------|
| 前端（规划） | Vue 3 + TypeScript；按比较流程建设 |
| 后端（规划） | Spring Boot 模块化单体；具体依赖在实施时核验 |
| 存储 | MySQL 8.0 / Redis 7 |
| 消息 | RabbitMQ 3.13 |
| 采集 | Python + requests + lxml；动态页面按需引入浏览器 |

## 架构契约验证

```powershell
python -B tools/architecture/validate_release.py contracts/examples/descriptive.json
python -B -m unittest discover -s tools/architecture -p 'test_*.py'
python -B -m unittest discover -s crawler -p 'test_*.py'   # 入口探测 P0.1 离线验证（无网络请求）
```

此校验只检查发布声明的一致性，不代替证据审核或正式模型验证。下一实施顺序为采集失败修复 → 证据与事实版本 → 1 池完整报告 → 多池情景比较 → 页面与模型准入，详见执行流程。P0.1（入口探测修复）已完成，下一步 P0.2（快照与证据追加）。

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
