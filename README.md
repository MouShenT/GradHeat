# GradHeat

> 11408 考研院校专业热度评估与择校分析平台

多维度评估 11408（政治 + 英一 + 数一 + 408）相关考研院校/专业的热度，以网站形式呈现。

**核心原则：承认数据缺失，用可量化的方式表达可信度，而不是假装数据完整。**

## 文档

- [设计方案](docs/DESIGN.md) —— 维度框架、技术选型、架构、真实性保障机制

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
| 后端 | Spring Boot 3 + Java 17 + MyBatis-Plus |
| 存储 | MySQL 8.0 / Redis 7 |
| 消息 | RabbitMQ 3.13 |
| 采集 | Python + Scrapy + Playwright |

## 环境

基础设施部署在 Kali VM（`192.168.43.150`）的 Docker 内，详见 [infra/docker/README.md](infra/docker/README.md)。

```bash
# 启动基础设施
ssh ms@192.168.43.150 "cd /opt/gradheat/infra/docker && docker compose up -d"

# 本地开发隧道
ssh -N -L 13306:127.0.0.1:3306 -L 16379:127.0.0.1:6379 -L 15673:127.0.0.1:15672 ms@192.168.43.150
```

## 状态

Phase 0 准备中 —— 详见 [设计方案](docs/DESIGN.md) 路线图。