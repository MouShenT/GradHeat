# 接口与运行配置

当前应用接口与消息定义见 application-v1/README.md。social-collection.json 定义采集输入约定。

runtime-connections.example.json 是模板，实际 VM/SSH 配置保存为私有 runtime-connections.json。运行配置、服务令牌和 Cookie 不提交；网页只访问 Java /api/v1，Python 内部调用需认证。

版本与原件按规范 JSON 字节和 SHA 核对，MySQL 保留不可变结果。未知值使用 null，不以零代替。旧实验发布契约已退役。
