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

生成生产 additive 迁移计划时，先只选定已确认的缺字段，不会执行 SQL：

```bash
STUDYHUB_ENVIRONMENT=production bash scripts/db/db-plan-p0-schema.sh
```

该脚本默认只生成 `market_items.source` 和 `orders.uploader_id` 的计划。需要调整范围时可设置 `STUDYHUB_P0_SCHEMA_COLUMNS`，值为空格分隔的 `table.column` 列表。

确认备份、SQL 和 `planToken` 后才允许执行 `--yes`。production 执行时必须保留相同字段范围，并传入计划输出里的 token：

```bash
STUDYHUB_ENVIRONMENT=production \
STUDYHUB_P0_PLAN_TOKEN=<PLAN_TOKEN_FROM_PLAN_OUTPUT> \
YES_PRODUCTION_SCHEMA_ADD_COLUMNS=I_UNDERSTAND_ADD_COLUMNS \
bash scripts/db/db-apply-p0-schema.sh
```

`db-apply-p0-schema.sh` 会调用 `migrate-additive --yes`，只执行审计生成的 `ADD COLUMN` 语句。production 执行前默认要求最近 120 分钟内已有非空备份；如需调整窗口，可设置 `STUDYHUB_BACKUP_MAX_AGE_MINUTES`。

如果目标库已经由旧流程建好表，只需要记录当前迁移版本：

```bash
STUDYHUB_ENVIRONMENT=preview bash scripts/db/db-stamp-head.sh
```

备份：

```bash
STUDYHUB_ENVIRONMENT=preview bash scripts/db/db-backup.sh
STUDYHUB_ENVIRONMENT=production bash scripts/db/db-backup.sh private/backups/manual-prod.sql.gz
```

恢复 preview：

```bash
YES_PREVIEW_DB_RESTORE=I_UNDERSTAND_RESTORE \
STUDYHUB_ENVIRONMENT=preview \
bash scripts/db/db-restore-preview.sh /path/to/preview-backup.sql.gz
```

## 使用约束

- 默认以只读检查和备份为主
- production 不允许通过该目录下脚本直接恢复数据库
- preview 恢复和建表都需要显式确认环境变量
- migration 需要显式执行，不会在 Web 服务启动时自动修改 schema
