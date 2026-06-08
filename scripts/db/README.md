# scripts/db

这里放数据库检查、备份与恢复脚本。

## 常用命令

检查：

```bash
STUDYHUB_ENVIRONMENT=preview bash scripts/db/db-check.sh
```

默认会执行 `db_admin check-schema`，检查缺表和缺字段。只需要兼容旧行为检查缺表时，可以使用：

```bash
STUDYHUB_DB_CHECK_MODE=tables STUDYHUB_ENVIRONMENT=preview bash scripts/db/db-check.sh
```

建表：

```bash
ALLOW_PREVIEW_DB_CREATE=I_UNDERSTAND_CREATE_SCHEMA \
STUDYHUB_ENVIRONMENT=preview \
bash scripts/db/db-init-schema.sh
```

迁移：

```bash
STUDYHUB_ENVIRONMENT=preview bash scripts/db/db-migrate.sh
```

`db-migrate.sh` 在 production 默认拒绝直接执行 Alembic upgrade，避免绕过备份、计划 token 和 additive SQL 限制。生产 P0 schema 修复优先使用下面的 `db-prepare-p0-schema.sh` 与 `db-apply-p0-schema.sh`。确需在 production 执行 Alembic 时，必须额外设置：

```bash
YES_PRODUCTION_ALEMBIC_MIGRATION=I_UNDERSTAND_ALEMBIC_PRODUCTION \
STUDYHUB_ENVIRONMENT=production \
bash scripts/db/db-migrate.sh
```

生成生产 additive 迁移计划时，先只选定已确认的缺字段，不会执行 SQL：

```bash
STUDYHUB_ENVIRONMENT=production bash scripts/db/db-plan-p0-schema.sh
```

该脚本默认只生成 `market_items.source` 和 `orders.uploader_id` 的计划。需要调整范围时可设置 `STUDYHUB_P0_SCHEMA_COLUMNS`，值为空格分隔的 `table.column` 列表。

执行前准备备份和计划：

```bash
STUDYHUB_ENVIRONMENT=production bash scripts/db/db-prepare-p0-schema.sh
```

该脚本只执行备份和 `--plan`，不会执行 DDL。输出里的 `backupFile`、SQL 和 `planToken` 都需要人工确认。

验证 P0 字段是否已经补齐：

```bash
STUDYHUB_ENVIRONMENT=production bash scripts/db/db-verify-p0-schema.sh
```

该脚本只执行 `check-schema --only`，不会修改数据库。字段缺失时返回非 0，字段补齐后返回 0。

确认备份、SQL 和 `planToken` 后才允许执行 `--yes`。production 执行时必须保留相同字段范围，并传入计划输出里的 token：

```bash
STUDYHUB_ENVIRONMENT=production \
STUDYHUB_P0_PLAN_TOKEN=<PLAN_TOKEN_FROM_PLAN_OUTPUT> \
YES_PRODUCTION_SCHEMA_ADD_COLUMNS=I_UNDERSTAND_ADD_COLUMNS \
bash scripts/db/db-apply-p0-schema.sh
```

`db-apply-p0-schema.sh` 会调用 `migrate-additive --yes`，只执行审计生成的 `ADD COLUMN` 语句。production 执行前默认要求最近 120 分钟内已有非空备份；如需调整窗口，可设置 `STUDYHUB_BACKUP_MAX_AGE_MINUTES`。

迁移后验收：

```bash
STUDYHUB_ENVIRONMENT=production bash scripts/db/db-smoke-p0-schema.sh
```

该脚本会先验证 P0 字段已经补齐，再检查 health/ready、metrics 和关键只读接口。默认不跑 worker；需要验证 worker once 时设置 `STUDYHUB_P0_RUN_WORKER_ONCE=1`。
HTTP 检查默认使用 5 秒连接超时和 20 秒总超时，可用 `STUDYHUB_CURL_CONNECT_TIMEOUT` / `STUDYHUB_CURL_MAX_TIME` 调整。

检查近期日志是否还有 P0 schema 漂移错误：

```bash
STUDYHUB_ENVIRONMENT=production bash scripts/db/db-log-p0-schema.sh
```

默认检查 `studyhub-backend.service studyhub-worker.service` 最近 30 分钟日志中的 `market_items.source` 和 `orders.uploader_id` 缺字段错误。可用 `STUDYHUB_P0_LOG_SERVICES`、`STUDYHUB_BACKEND_SERVICE`、`STUDYHUB_WORKER_SERVICE` 和 `STUDYHUB_P0_LOG_SINCE` 调整服务名和时间窗口。

如果目标库已经由旧流程建好表，只需要记录当前迁移版本：

```bash
STUDYHUB_ENVIRONMENT=preview bash scripts/db/db-stamp-head.sh
```

production 默认也禁止直接 stamp head，避免在字段缺失时掩盖 schema 漂移。确需操作时，脚本会先强制运行只读 `db-verify-p0-schema.sh`，通过后才会继续执行 stamp；仍需额外设置：

```bash
YES_PRODUCTION_ALEMBIC_STAMP=I_UNDERSTAND_STAMP_PRODUCTION \
STUDYHUB_ENVIRONMENT=production \
bash scripts/db/db-stamp-head.sh
```

备份：

```bash
STUDYHUB_ENVIRONMENT=preview bash scripts/db/db-backup.sh
STUDYHUB_ENVIRONMENT=production bash scripts/db/db-backup.sh private/backups/manual-prod.sql.gz
```

`db-backup.sh` 的输出路径如果是相对路径，会按仓库根目录解析；上面的示例会写入 `/data/studyhub/private/backups/manual-prod.sql.gz`。
备份命令输出会包含 `backupSizeBytes` 和 `backupSha256`，用于人工确认备份文件大小和内容指纹。

恢复 preview：

```bash
YES_PREVIEW_DB_RESTORE=I_UNDERSTAND_RESTORE \
STUDYHUB_ENVIRONMENT=preview \
bash scripts/db/db-restore-preview.sh /path/to/preview-backup.sql.gz
```

`db-restore-preview.sh` 的输入路径如果是相对路径，也会按仓库根目录解析。

## 使用约束

- 默认以只读检查和备份为主
- production 不允许通过该目录下脚本直接恢复数据库
- production 直接 Alembic migration 默认禁用，P0 字段修复走受保护的 additive 脚本
- production 直接 Alembic stamp 默认禁用，避免掩盖尚未修复的 schema 漂移
- preview 恢复脚本只允许 `STUDYHUB_ENVIRONMENT=preview`，且恢复和建表都需要显式确认环境变量
- migration 需要显式执行，不会在 Web 服务启动时自动修改 schema
