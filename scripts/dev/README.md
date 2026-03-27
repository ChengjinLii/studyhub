# scripts/dev

这里放本地开发相关脚本，分成两类：

- `docker-dev-*`：推荐的长期开发方式，使用 Docker Compose、本地 MySQL 和完整依赖
- `local-dev-*`：更轻的 shell quickstart，适合快速看页面、改样式或做短链路调试

## 推荐方式：Docker Local Dev

启动：

```bash
bash scripts/dev/docker-dev-up.sh
```

状态与日志：

```bash
bash scripts/dev/docker-dev-status.sh
bash scripts/dev/docker-dev-logs.sh
```

停止：

```bash
bash scripts/dev/docker-dev-down.sh
```

默认地址：

- frontend：`http://127.0.0.1:3100`
- backend：`http://127.0.0.1:8111/api/healthz`
- mysql：`127.0.0.1:3307`

默认开发账号：

- 用户名：`developer`
- 密码：`developer123`
- 邮箱：`developer@local.studyhub.dev`

## 备用方式：Shell Quickstart

启动：

```bash
bash scripts/dev/local-dev-up.sh
```

状态与停止：

```bash
bash scripts/dev/local-dev-status.sh
bash scripts/dev/local-dev-down.sh
```

这套方式默认使用本地 SQLite，不依赖 Docker，更适合快速体验和局部调试。
