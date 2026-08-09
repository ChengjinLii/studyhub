# scripts/security

这里放仓库安全卫生检查脚本。

## Sensitive Files

```bash
bash scripts/security/check-sensitive-files.sh
```

该脚本会检查当前 Git 已跟踪文件名和可见 Git 历史文件名，防止真实 `.env`、`private/`、私钥、证书等高风险文件误提交；`.env.example` 示例文件允许保留。

## Zero-cost Runtime Guards

仓库提供一组不修改数据库的运行时防护：

- `deploy/nginx/studyhub-abuse-zones.conf`：按全局、写请求、认证、AI、MCP 和 `/v1` 分桶限速
- `deploy/nginx/studyhub-abuse-server.conf`：连接限制、慢请求保护、仅本机 metrics 与 Nginx status，以及前端和 API 统一安全响应头
- `deploy/systemd/studyhub-backend-hardening.conf`：Uvicorn 并发和 backlog 上限
- `runtime-abuse-monitor.py`：每分钟检查请求峰值、429、5xx、连接数、CPU、内存、磁盘、inode、证书、服务和本机探针

生产安装入口：

```bash
sudo STUDYHUB_ENABLE_UFW=1 bash scripts/security/install-runtime-guards.sh --apply
```

安装器会先把现有 Nginx 文件备份到被 Git 忽略的 `private/backups/`，注入两个 server block include，将普通 upstream 的 300 秒超时收敛为 120 秒、流式入口的 600 秒收敛为 300 秒，并把 upstream 连接超时收敛为 5 秒。执行 `nginx -t` 成功后才 reload，校验失败会自动恢复旧配置。`STUDYHUB_ENABLE_UFW=1` 会启用默认拒绝入站的 UFW，仅放行限速后的 SSH 和 80/443；SSH 使用非 22 端口时必须同时传入 `STUDYHUB_SSH_PORT`。

应用限流默认保留校园 NAT 突发空间，同时收紧登录、邮件验证码、投稿、AI 和 MCP。Nginx 对投稿保留当前 128MB body 上限，不改变站内 50MB 文件加预览图的业务能力。详细 readiness 和 metrics 只允许源站本机访问，公网 health 只返回最小存活状态。

监控复用 `private/.env.production` 中的 SMTP 配置，向 unit 中声明的管理员地址发送已确认告警、每小时持续告警提醒和恢复通知；异常默认连续出现 3 次才发首封，之后连续健康 2 次才发一次恢复，失败通知每五分钟重试。单次 CPU 抖动或一分钟内完成的正常部署不会发信。查看本机监控结果：

```bash
sudo systemctl status studyhub-abuse-monitor.timer
sudo journalctl -u studyhub-abuse-monitor.service --since today
sudo cat /var/lib/studyhub-security/runtime-abuse-status.json
```

安装后可发送一次不改变告警状态的投递测试：

```bash
sudo /usr/bin/python3 scripts/security/runtime-abuse-monitor.py \
  --env-file private/.env.production \
  --alert-email 2731938007@qq.com \
  --alert-email 1643468233@qq.com \
  --test-notification
```

该层可以缓解 HTTP/CC、暴力请求和资源耗尽，不能替代云端 L3/L4 流量清洗。`/api/metrics` 安装后仅允许从源站本机访问，生产 smoke 仍通过后端 loopback 地址检查指标。

Nginx 会为页面、静态资源、API 和错误响应统一设置 HSTS、`nosniff`、frame、referrer 与 permissions 策略。HSTS 仅在 HTTPS 响应中发送；CSP 当前仅使用 `Content-Security-Policy-Report-Only`，违规报告匿名提交到 `/api/security/csp-reports`，不会阻断支付、OSS 预览或前端资源。上线后可运行：

```bash
bash scripts/security/check-security-headers.sh https://study-hub.cn
```

在决定启用强制 CSP 前，应至少观察 7～14 天报告，并实际验证 Next.js 水合、支付宝跳转、OSS 图片/预览和 AI 流式响应。切勿直接增加 `preload` 或删除当前兼容源。

## Redis Expiring State

Redis 只承载限流、验证码、注册/上传临时凭证和短期缓存，不保存文件、订单、结算或其他永久业务数据。生产安装入口：

```bash
sudo bash scripts/security/install-redis.sh --apply
bash scripts/security/check-redis.sh
```

安装器会备份原配置和私有生产环境文件，生成仅存于 `private/` 的随机 ACL 密码，并启用以下边界：仅监听 loopback、仅允许访问 `studyhub-fastapi:*`、数据内存上限 64MB、systemd 进程上限 128MB、关闭 RDB/AOF。Redis 故障时缓存和普通限流可以降级；注册与上传授权不得静默绕过。

若服务器为 APT 配置了本机代理，而腾讯云 Ubuntu 镜像应走内网或直连，可安装仓库中的单域名例外，避免代理故障阻断安全更新：

```bash
sudo install -m 0644 deploy/apt/studyhub-mirror-direct.conf /etc/apt/apt.conf.d/96studyhub-mirror-direct
sudo install -m 0644 deploy/apt/studyhub-unattended-security.conf /etc/apt/apt.conf.d/60studyhub-unattended-security
sudo apt-get update
```

第二个 drop-in 显式恢复 Ubuntu security pocket，并保持自动重启关闭。安装后应执行一次 `sudo unattended-upgrade --dry-run --debug`，确认输出中确实包含待升级包，而不只是 timer 成功退出。
