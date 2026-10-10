# 当前采集适配器

四平台通过已有 MediaCrawler 本机登录会话和 GradHeat 适配器采集；独立 Python CLI 管理冻结输入、分页、去重、原件与断点。抖音采用实际可见综合搜索，不能标成最新排序。

现有全局和平台锁保持串行浏览器访问。已有采集优先，后续等待。用户确认某平台可以搜索后只允许该平台一次有界复查，失败记缺口继续其他任务，不自动解除其他平台限制。

公开互动计数、正文和图片分别记录取得状态；未知不填零，未取得正文不能拿视频说明或搜索摘要冒充。每次得到部分材料也先冻结，超时/中断可从原件恢复。

百度搜索热度采用固定版本 Qdata，与社交采集分开。账户、Cookie、签名、请求头和会话 HTML 不进入 Git 或交接包。源码入口位于 tools/research/collect_social_sources.py、mediacrawler_worker.py、collect_search_indices.py。
