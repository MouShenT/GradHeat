# 发布清单 v1

`release.schema.json` 定义最低发布清单，`tools/architecture/validate_release.py` 补充跨字段时间和能力门槛检查。使用现有 jsonschema 依赖；新环境安装 tools/architecture/requirements.txt。

```powershell
python -B tools/architecture/validate_release.py contracts/examples/descriptive.json
python -B -m unittest discover -s tools/architecture -p 'test_*.py'
```

样例是明确的合成 fixture，不是真实学校事实。校验器只验证声明的结构与相互一致性，不访问网络、数据库或证据文件，不验证哈希对应内容、审核身份或评审报告真实性。返回 valid 不能直接触发生产发布。

正式发布用例还必须解析 snapshot_id、fact_revision、pool_version、review_id 和 report_ref，核对权限、审核状态、原文哈希及文件存在性；确认清单涵盖结果实际使用的全部事实；验证代码/模型与报告一致，事务性冻结清单并切换发布指针。这些集成尚未实现。

live_snapshot 禁止使用 cutoff 后观察到的事实；reconstructed 必须给出发布时间证明引用，且在报告中披露重建限制。无可靠发布时间的事实不能进入历史发布清单，可保留在待核验候选区。

时间校验显式实现，不依赖 jsonschema 可选格式包是否安装：采用 RFC3339 的严格子集，大写 T/Z、秒、Z 或已知数字偏移；不接受缺失时区、未知偏移 -00:00 或闰秒。时区转换后比较真实时点。来源 URL 还检查主机存在且不含用户名/密码；它不是网络访问安全过滤器。

scenario 要求敏感性评审记录；probability 另外要求时间外验证、校准和适用范围评审。指标阈值由具体模型评审报告确定，不能仅填 passed 就视为科学验证。
