# 本地研究工具配置与运行记录

核验日期：2026-09-22。这里配置的是本地 Codex 的研究工具，不是网站产品的搜索接口。网络服务状态是当次观测，不是持续可用承诺。

## 已安装与实测

| 能力 | 接入与观测结果 | 限制 |
|---|---|---|
| 全网发现 | 用户级 MCP `gradheat_exa`：官方托管接口；匿名真实查询成功 | 旧 Exa 密钥返回 401，未用于新配置；匿名额度可能受限 |
| 搜索与原文采集 | 用户级 MCP `gradheat_firecrawl`：完整端点，认证、列工具、搜索成功 | 使用现有私人密钥；按服务额度使用 |
| 论文检索与正文核验 | 同一 Firecrawl MCP 的 research 工具；已检索、按 arXiv ID 核对、读取相关正文段落 | 检索排序未必命中目标；独立 `/v2/mcp-search` 端点用当前密钥返回 401，未配置 |
| 命令行搜索 | 官方 `firecrawl-cli@1.19.6` 安装于用户目录，真实搜索返回 3 条结果 | 此版本无 `research` 子命令；论文查询走 MCP |
| DOI 核对 | Crossref 官方 REST，Rosenthal 1973 文献查询命中 | 仅验证元数据，不代表全文验证 |
| 自托管后备搜索 | 虚拟机 SearXNG：Google CSE 20 条、Bing 10 条 | Brave 返回限流，正常查询默认排除，健康检查仍显示其状态 |
| 领域技能 | `~/.codex/skills/gradheat-research/SKILL.md` 已安装并通过格式校验 | 约束证据和模型适用范围，不能替代研究判断 |
| Scite | 已安装并连接；按 DOI 查询及引用图谱调用成功 | 本次经典文献全文不可用，图谱未返回引用原文；不可把计数当作论证 |

MCP 配置已写入 `C:/Users/moushen/.codex/config.toml`，原有 `node_repl` 保留。Exa 开放 search/fetch 两项，Firecrawl 开放搜索、采集、站点发现、论文研究和额度查询共九项工具。当前会话通过独立 MCP 协议探针完成验证；需要在 Codex 设置中重载 MCP，必要时重启应用，才能确认客户端工具加载。新技能在后续会话加载。

最终验收：更新后用中文查询 `site:edu.cn 计算机 硕士 招生目录`，默认两引擎合计返回 30 条、无引擎错误，证据记录 `20260922T003902-ffbd3b13422a4c5587f072df7acd0f7c.meta.json`。这验证传输及留存，不表示 30 条内容均经过事实核验。5 项本地回归检查通过，覆盖中文 SSE、失败/空结果区分、部分失败及原始响应复用。配置读回与技能文件一致性检查通过，新脚本和文档未发现现有密钥明文。

## 使用

在项目根目录运行；Python 辅助工具依赖现有环境的 `requests`。CLI 使用已有 Node，不修改系统 PATH。

```powershell
# CLI 版本与搜索；包装器按需读取现有私人密钥并关闭反馈上传
./tools/research/firecrawl.ps1 --version
./tools/research/firecrawl.ps1 search 'site:moe.gov.cn 硕士研究生 招生 工作管理规定' --limit 3

# 检查 MCP 认证及工具列表，不打印密钥
python -B tools/research/mcp_check.py exa --anonymous
python -B tools/research/mcp_check.py firecrawl

# DOI 元数据；不将其当作已读论文
python -B tools/research/crossref.py --doi 10.1007/bf01737559

# SSH 调用仅监听虚拟机回环地址的搜索器
./tools/research/searxng.ps1 -Query 'site:edu.cn 计算机 硕士 招生目录'
./tools/research/searxng.ps1 -Health

# 无网络回归检查
python -B -m unittest discover -s tools/research -p 'test_*.py'
```

探针支持 `--tool 工具名 --args-file 参数.json`；参数结构以探针记录的官方工具 schema 为准。诊断快照位于 `.research/`，同名探针结果会覆盖，不能充当永久证据库。重要查询应另存带时间戳的记录。`.research/`、`.firecrawl/` 均被 Git 忽略。不要将学生个人资料、密钥或未公开材料作为公网查询文本。

## 虚拟机基础设施

已连接 `ms@192.168.43.150`，沿用 SearXNG、现有代理及 MySQL/Redis/RabbitMQ。SearXNG 继续仅监听 `127.0.0.1:8890`，通过 SSH 使用，无新增公网入口。

- 部署 `/opt/gradheat/search/gradheat_search.py`，记录引擎错误，区分 healthy、degraded、down、empty。成功返回内容也须人工核对相关性。
- 原始 JSON 以 SHA-256 命名，查询元数据单独按时间及 UUID 留档于 `/opt/gradheat/evidence/search`，目录权限 0700。原始记录可追溯，但未配置自动异机备份、保留期限或持续监控。
- 请求超时调整为 12 秒，上限 20 秒；添加 systemd 失败重启、5 秒重启间隔、UMask 0077；配置验证及服务 active 检查通过。
- 修复 SSH 私钥过宽 ACL，移除 TempAdmin 访问；原 ACL 备份位于本地忽略文件 `.tmp-ssh-key-acl.sddl`。不在文档保存私钥内容。

部署脚本 `infra/search/deploy_vm.py` 每次变更前备份配置、已有 helper 和 systemd drop-in 到 `/opt/gradheat/backups/search-<UTC时间>`。首次备份为 `search-20260922T003159Z`。回滚需选中相应备份恢复 settings.yml；首次部署前不存在的 helper/drop-in 需按实际情况移除，然后 daemon-reload 并重启 SearXNG。先核对文件差异，避免覆盖后续修改。

本地安装脚本 `tools/research/install_local.py` 已执行，不要重复运行；重复安装会主动中止。安装前配置备份位于 `~/.codex/config.toml.before-gradheat-*`。回滚时仅移除本次两个 MCP 段与 `gradheat-research` 技能；若整文件恢复备份，需先确认没有后续配置变更。CLI 固定目录可独立卸载。

## 可信度如何落实

### Scite 接入验收（2026-09-22）

当前会话已发现并调用 Scite 插件工具，无需另装同名 MCP。`search_literature(dois=["10.1007/bf01737559"], limit=1)` 返回 Rosenthal、1973 年及一致标题。返回 `contentDenied=true`，未取得该论文全文，证据等级仍为 metadata-only。

`citation_graph` 以同一 DOI 为种子，设置入向一跳、最多 3 条边及 include_snippets，成功返回 3 条引用关系，但未附引用原文；同时返回 truncated=true 和 low_coverage_seeds。本次仅作连接测试，不能据此判断整个研究领域、共识程度或缺乏反对证据。

后续流程：先确定 DOI，再查引用关系和引用语句；如有 snippet，记录引用方 DOI、被引 DOI、段落及分类，必要时回看引用方全文。无原文时降级为关系线索。supporting/contrasting 标签、引用数量和检索结果均不能替代理论前提核验。不开启自动购买、公开收藏或共享笔记。

检索器只负责发现，原始发布方负责事实出处；理论结论必须有正文证据和适用条件。执行 [证据与理论规范](RESEARCH-EVIDENCE-POLICY.md)，项目建模改进见 [决策审查](DECISION-REVIEW.md)。官方接入依据与开源项目记录见 [PRIOR-ART](PRIOR-ART.md)。
