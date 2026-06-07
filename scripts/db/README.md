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
