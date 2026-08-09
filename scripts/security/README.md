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
- `deploy/nginx/studyhub-abuse-server.conf`：连接限制、慢请求保护、仅本机 metrics 与 Nginx status
- `deploy/systemd/studyhub-backend-hardening.conf`：Uvicorn 并发和 backlog 上限
- `runtime-abuse-monitor.py`：每分钟检查请求峰值、429、5xx、连接数、内存和负载

生产安装入口：

```bash
sudo STUDYHUB_ENABLE_UFW=1 bash scripts/security/install-runtime-guards.sh --apply
```

安装器会先把现有 Nginx 文件备份到被 Git 忽略的 `private/backups/`，注入两个 server block include，将普通 upstream 的 300 秒超时收敛为 120 秒、流式入口的 600 秒收敛为 300 秒，并把 upstream 连接超时收敛为 5 秒。执行 `nginx -t` 成功后才 reload，校验失败会自动恢复旧配置。`STUDYHUB_ENABLE_UFW=1` 会启用默认拒绝入站的 UFW，仅放行限速后的 SSH 和 80/443；SSH 使用非 22 端口时必须同时传入 `STUDYHUB_SSH_PORT`。

应用限流默认保留校园 NAT 突发空间，同时收紧登录、邮件验证码、投稿、AI 和 MCP。Nginx 对投稿保留当前 128MB body 上限，不改变站内 50MB 文件加预览图的业务能力。查看本机监控结果：

```bash
sudo systemctl status studyhub-abuse-monitor.timer
sudo journalctl -u studyhub-abuse-monitor.service --since today
sudo cat /var/lib/studyhub-security/runtime-abuse-status.json
```

该层可以缓解 HTTP/CC、暴力请求和资源耗尽，不能替代云端 L3/L4 流量清洗。`/api/metrics` 安装后仅允许从源站本机访问，生产 smoke 仍通过后端 loopback 地址检查指标。
