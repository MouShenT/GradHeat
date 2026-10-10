# Python 服务

gradheat_python 是内部 API、采集与消息 worker；gradheat_core 是共享算法。没有旧网页服务器，网页只访问 Java /api/v1。API 直接读已提交 MySQL 版本，不依赖本地院校材料才能启动。

```powershell
python -m pip install -r python_service/requirements.txt
python -m unittest discover -s python_service/tests
$env:PYTHONPATH = "$PWD/python_service"
python -m gradheat_python.api
```

内部请求使用至少 32 字符的专用令牌。/health 是进程探针，/internal/v1/ready 验证资料就绪。开发服务使用 18732，由独立启动器配置环境。

接口包括 admissions、dashboard、heat、school-indices、school-dossier、recommendations、victory-index、game-scenario 和 comparisons/evaluate。计算输入绑定 data_version，版本变化返回冲突；个人分数未填返回待填写，未知值不填零。

采集 CLI 接受冻结 JSON，按既有锁执行；原件先保存、SHA 核对再入 MySQL。持久档案、搜索序列、个人比较和凭据不提交 Git。运行与消息约定见 ../docs/APPLICATION-RUNBOOK.md 和 ../contracts/application-v1/README.md。

Docker 镜像包含共享核心、当前采集依赖、配置模板与迁移源码；数据库配置运行时注入，浏览器采集在具备用户登录会话的本机 worker 执行。
