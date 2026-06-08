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
- `production-up.sh` 默认先跑 `production-preflight.sh` 检查证书路径、数据库网络连通性和 P0 schema 缺字段；紧急场景可设置 `STUDYHUB_PRODUCTION_UP_PREFLIGHT=0` 显式跳过
- `production-preflight.sh` 默认检查 `market_items.source orders.uploader_id`，可用 `STUDYHUB_PRODUCTION_SCHEMA_CHECK_COLUMNS` 覆盖；设为空字符串时执行全量 schema 检查，全空白值会被视为配置错误
- `production-preflight.sh` 的网络连通性检查默认 5 秒超时，可用 `STUDYHUB_PREFLIGHT_TIMEOUT_SECONDS` 调整
- preview / production 不应隐式回退到 SQLite 或本地 fake provider
- 生产环境相关操作应保持显式、保守、可回滚
