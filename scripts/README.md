# studyhub scripts

`scripts/` 按用途拆成了几个子目录，避免开发脚本、部署脚本、worker 脚本和数据库脚本混在一起。

## 目录索引

- [`scripts/dev/`](dev/README.md)：本地开发与快速体验
- [`scripts/runtime/`](runtime/README.md)：preview / production 启停与 smoke check
- [`scripts/workers/`](workers/README.md)：worker 与 scheduler
- [`scripts/db/`](db/README.md)：数据库检查、备份、恢复
- [`scripts/utils/`](utils/README.md)：通用辅助脚本

## 常用入口

- 本地开发：`bash scripts/dev/docker-dev-up.sh`
- 轻量启动：`bash scripts/dev/local-dev-up.sh`
- 预发布运行：`bash scripts/runtime/preview-up.sh`
- 生产运行：`bash scripts/runtime/production-up.sh`

更具体的命令、环境变量和注意事项已经分别下沉到各子目录 README。
