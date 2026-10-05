# StudyHub PWA 技术说明

本文记录手机端安装、缓存、更新和验收方式。

---

## 安装方式

通过 HTTPS 打开 StudyHub，点击手机端右下角的下载箭头进入安装流程。

| 环境 | 操作 |
| --- | --- |
| 支持 `beforeinstallprompt` 的浏览器 | 打开浏览器原生安装窗口，由用户确认 |
| iPhone | 使用分享菜单中的“添加到主屏幕” |
| 微信等内嵌浏览器 | 按提示在系统浏览器中打开 |

PWA 安装沿用网页应用，不下载 APK，也不绕过浏览器的确认流程。

---

## 缓存与更新

PWA 使用原有页面、账户和 API，不新增数据库表。登录、文件下载、支付和投稿通过在线服务完成。

Service Worker 缓存版本化前端资源、应用图标和无用户信息的离线提示页；API、资料文件、订单和账户页面不进入缓存，写操作也不排队重试。

更新不会强制刷新正在使用的页面。关闭所有旧窗口后，新 Worker 才会激活。

---

## 图标与验收

图标源文件为 `frontend/public/icons/studyhub-app.svg`，生成命令：

```bash
node frontend/scripts/build-pwa-icons.mjs
```

生成结果包括 PNG 与 maskable 图标。安装、缓存和更新检查纳入 `test:unit`、`test:critical` 与 `test:critical:prod`；iOS / Android 真机安装及支付宝返回流程另行验收。
