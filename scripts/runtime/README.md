# scripts/runtime

这里放 preview / production 的启停与 smoke check 脚本，主要面向仓库维护者。

## Preview

```bash
bash scripts/runtime/preview-up.sh
bash scripts/runtime/preview-status.sh
bash scripts/runtime/preview-smoke.sh
bash scripts/runtime/preview-down.sh
```

默认端口：

- backend：`127.0.0.1:8211`
- frontend：`127.0.0.1:3200`

## Production

```bash
bash scripts/runtime/production-preflight.sh
bash scripts/runtime/production-up.sh
bash scripts/runtime/production-status.sh
bash scripts/runtime/production-smoke.sh
bash scripts/runtime/production-down.sh
```

默认端口：

- backend：`127.0.0.1:8311`
- frontend：`127.0.0.1:3300`

## 使用约束

- 运行前需要准备好 `private/.env.preview` 或 `private/.env.production`
- `preview-up.sh` 启动前默认运行只读 `db_admin check-schema`，避免带缺字段的 preview 服务启动
- `preview-smoke.sh` / `production-smoke.sh` 的 curl 默认使用 5 秒连接超时和 20 秒总超时，可用 `STUDYHUB_CURL_CONNECT_TIMEOUT` / `STUDYHUB_CURL_MAX_TIME` 调整，值必须是大于 0 的秒数
- `production-smoke.sh` 默认检查本机 backend / frontend，并会从 `private/.env.production` 的 `STUDYHUB_PUBLIC_SITE_BASE_URL`、`STUDYHUB_TRUSTED_SITE_ORIGINS` 自动派生公网域名做 health/root smoke；默认用当前 git short SHA 校验 `/api/healthz`，避免域名、CDN 或反代仍指向旧服务。可用 `STUDYHUB_PUBLIC_SMOKE_BASES="https://study-hub.cn https://study-hub.store"` 显式覆盖，或设为 `none` / `off` 临时关闭公网入口检查
- `production-up.sh` 默认先跑 `production-preflight.sh` 检查证书路径、数据库网络连通性和 P0 schema 缺字段；紧急场景可设置 `STUDYHUB_PRODUCTION_UP_PREFLIGHT=0` 显式跳过，该开关只接受 `1` / `true` / `0` / `false`
- `production-preflight.sh` 会输出 `site-origin-consistency`，用于提示主站、可信来源和支付宝回跳是否混用多个公网域名；该项为 warning，不会阻断当前服务启动，但正式切换主域名前应收敛为单一主站 origin
- `production-up.sh` 默认不会在前端进程仍运行且 `.next/BUILD_ID` 存在时重建前端，避免覆盖运行中 Next.js 进程使用的构建目录；如已停掉前端或确认要强制重建，可设置 `STUDYHUB_PRODUCTION_REBUILD_FRONTEND=1`
- 不要在生产服务目录直接运行 `next dev`、未隔离的 Playwright 或会写 `.next` 的前端命令；运行中的 `next start` 会读取当前 `.next`，中途覆盖会导致 `Cannot find module` / `MissingStaticPage`。仓库的 Playwright 配置默认使用 `.next-playwright-dev` / `.next-playwright-prod`，如手动执行类似命令也应设置 `NEXT_DIST_DIR` 到隔离目录
- 前端重启或生产构建后可运行 `bash scripts/runtime/frontend-build-integrity.sh`，确认 `.next` 关键产物、首页和 404 页面正常
- `production-preflight.sh` 默认检查 `market_items.source orders.uploader_id`，可用 `STUDYHUB_PRODUCTION_SCHEMA_CHECK_COLUMNS` 覆盖；值必须是空格分隔的 `table.column` 标识符，设为空字符串时执行全量 schema 检查，全空白值会被视为配置错误
- `production-preflight.sh` 的网络连通性检查默认 5 秒超时，可用 `STUDYHUB_PREFLIGHT_TIMEOUT_SECONDS` 调整
- `PREVIEW_BACKEND_PORT`、`PREVIEW_FRONTEND_PORT`、`PRODUCTION_BACKEND_PORT`、`PRODUCTION_FRONTEND_PORT` 必须是 1-65535 的 TCP 端口号，启动和状态脚本都会校验
- `preview-up.sh` / `production-up.sh` 只会把正整数 pid 文件视为已有进程
- `preview-down.sh` / `production-down.sh` 只会对正整数 pid 文件执行 `kill`，无效 pid 文件会被当作损坏状态处理
- preview / production 不应隐式回退到 SQLite 或本地 fake provider
- 生产环境相关操作应保持显式、保守、可回滚
- systemd 部署应安装 `deploy/systemd/studyhub-backend-hardening.conf`，将 Uvicorn 并发限制为 128、连接 backlog 限制为 512；shell runtime 使用相同默认值，可分别通过 `STUDYHUB_UVICORN_LIMIT_CONCURRENCY`、`STUDYHUB_UVICORN_BACKLOG`、`STUDYHUB_UVICORN_KEEPALIVE_SECONDS` 覆盖
