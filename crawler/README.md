# 采集与资料存储

当前采集入口是 Python 服务的 collection_cli 和 ../tools/run-collection.ps1。本目录提供官网访问、原件归档、MySQL、已提交资料发布和基础静态引用。

原件保存在本地忽略目录并幂等写入 MySQL，保留 SHA 与冻结 manifest。Redis 是缓存。平台受限、空内容和异常记缺口后继续，未成功材料可续传；完整原件不重采。

迁移目录按编号追加。已应用 SQL 保持原字节；旧全量清库入口已退役。应用消息迁移通过 run_migrate_application.py，院校档案迁移通过 ../tools/research/refresh_school_intelligence.py。初建数据库与已有数据库迁移分开操作。

静态 refs 是采集路由与院校分类配置。生成查询、JSONL、真实记录、原件、院校 Markdown、数据库导出和日志均不进入 Git。

详细操作见 ../docs/AUTONOMOUS-COLLECTION-RUNBOOK.md，当前任务见 ../docs/TASKS.md。
