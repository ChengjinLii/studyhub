# scripts/db

这里放数据库检查、备份与恢复脚本。

## 常用命令

检查：

```bash
STUDYHUB_ENVIRONMENT=preview bash scripts/db/db-check.sh
```

建表：

```bash
ALLOW_PREVIEW_DB_CREATE=I_UNDERSTAND_CREATE_SCHEMA \
STUDYHUB_ENVIRONMENT=preview \
bash scripts/db/db-init-schema.sh
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
