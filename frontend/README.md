# Vue 前端

Vue 3、TypeScript、Vite、ECharts。招生筛选、历年录取、院校图览与档案、热度值、候选比较、偏好推荐、个人胜利指数和信息采集。

```powershell
npm ci --ignore-scripts
npm test
npm run build
npm run dev
```

开发地址固定为 http://127.0.0.1:5173/，/api/v1 代理到本机 Java 18731。可通过私有环境 GRADHEAT_DEV_API_URL 配置业务实例；生产资源由 Java jar 提供。常驻开发使用 ../tools/start-frontend.ps1，关闭聊天不停止，保存源码自动热更新。

个人条件在网页填写并保存本机草稿；页面展示热度与胜利指数，重要资料来自院校档案。页面不嵌入真实本地样本，不把参考指数展示成录取概率。

浏览器检查只使用合成数据，测试输出保存到忽略目录。
