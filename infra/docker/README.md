# GradHeat 基础设施部署

## 目标环境

| 项目 | 值 |
|------|-----|
| 虚拟机 | Kali (VMware)，`ms@192.168.43.150`，静态 IP |
| 网络 | VMware VMnet8 (NAT)，宿主机 `192.168.43.1`，网关 `192.168.43.2` |
| 部署目录 | `/opt/gradheat/infra/docker/` |
| 隔离 | 独立 compose 项目 `gradheat`、网络 `gradheat-net (172.23.0.0/16)`、容器名前缀 `gradheat-` |

## 服务清单

| 服务 | 容器名 | 网络内地址 | 说明 |
|------|--------|-----------|------|
| MySQL 8.0 | `gradheat-mysql` | `mysql:3306` | utf8mb4，健康检查已配 |
| Redis 7 | `gradheat-redis` | `redis:6379` | 密码保护，AOF 持久化，512MB LRU |
| RabbitMQ 3.13 | `gradheat-rabbitmq` | `rabbitmq:5672` | vhost `/gradheat`，管理插件内置 |

仓库 compose 未配置宿主机端口映射。容器间通过 Docker 网络访问；SSH 转发到 VM 的 127.0.0.1 端口只有在该端口确有监听时才成立，SSH 本身不会自动打通未发布的容器端口。

## 常用命令

```bash
cd /opt/gradheat/infra/docker

docker compose up -d          # 启动
docker compose ps             # 状态
docker compose logs -f mysql  # 日志
docker compose down           # 停止（保留数据卷）
docker compose down -v        # 停止并删除数据（慎用）
```

## 本地开发隧道

以下为条件示例：先在 VM 检查服务监听。若仍使用仓库中未发布端口的 compose，应通过容器内部操作，或评估增加仅绑定 127.0.0.1 的端口映射后再使用。当前文档修订未改变 VM 配置。

```bash
ssh -N \
  -L 13306:127.0.0.1:3306 \
  -L 16379:127.0.0.1:6379 \
  -L 15673:127.0.0.1:15672 \
  ms@192.168.43.150
```

映射后本地访问：

| 本地地址 | 对应服务 |
|---------|---------|
| `127.0.0.1:13306` | MySQL（库 `gradheat`，用户 `gradheat`） |
| `127.0.0.1:16379` | Redis |
| `http://127.0.0.1:15673` | RabbitMQ 管理台 |

## 凭据

运行凭据保存在本地/虚拟机 `.env`，不提交版本库；仓库仅保存不含真实密码的示例。内网部署不改变这一要求。

| 服务 | 用户 | 密码变量 |
|------|------|---------|
| MySQL | `root` / `gradheat` | `MYSQL_ROOT_PASSWORD` / `MYSQL_PASSWORD` |
| Redis | — | `REDIS_PASSWORD` |
| RabbitMQ | `gradheat` | `RABBITMQ_PASSWORD` |

## 数据卷

| 卷名 | 内容 |
|------|------|
| `gradheat-mysql-data` | MySQL 数据文件 |
| `gradheat-redis-data` | Redis AOF |
| `gradheat-rabbitmq-data` | RabbitMQ 队列与消息 |

## 故障排查

```bash
# 容器起不来
docker compose logs --tail=50 <service>

# 网络不通（容器间）
docker exec gradheat-rabbitmq ping -c 2 mysql

# 端口占用检查
sudo ss -tlnp | grep -E '3306|6379|5672'
```

## 已知坑

2026-10-03已核验MySQL 8.0.46并将当前68单位研究资料写入`gradheat`库。`crawler/run_import_research.py --vm`读取容器当前内部IP，以随机本地端口建立临时SSH转发并自动关闭；不依赖原本地13306隧道。原件文件仍在Windows项目，VM保存哈希及元数据。[实际入库及复现](../../docs/DATABASE-INGEST-20261003.md)。

1. **VM 的原 netplan 配置是死配置** —— 文件存在但 `netplan` 命令没装，已于 2026-09-18 备份为 `/etc/netplan/01-netcfg.yaml.disabled`。
2. **NetworkManager 原先 `managed=false`** —— ifupdown 插件把 eth0 标记为 unmanaged，导致始终拿不到 IP。已改为 `managed=true`，并在 NM 里建了 `eth0-static` 连接（192.168.43.150/24）。
3. **DHCP 残留地址** —— 之前 dhclient 拿的 `192.168.43.13x` 可能会以 secondary 地址形式短暂存在，`sudo dhclient -r eth0` 可清掉。
