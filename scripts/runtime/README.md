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
- production 启动前建议先跑 `production-preflight.sh` 检查证书路径、数据库网络连通性和 schema 缺字段
- preview / production 不应隐式回退到 SQLite 或本地 fake provider
- 生产环境相关操作应保持显式、保守、可回滚
