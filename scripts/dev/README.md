# scripts/dev

这里放本地开发相关脚本，分成两类：

- `docker-dev-*`：推荐的长期开发方式，使用 Docker Compose、本地 MySQL 和完整依赖
- `local-dev-*`：更轻的 shell quickstart，适合快速看页面、改样式或做短链路调试

仓库内 `backend/Dockerfile` 和 `frontend/Dockerfile` 面向本地/开发验证；preview / production 运行优先使用 `scripts/runtime/` 下的显式脚本和 `private/.env.*` 配置。

## 推荐方式：Docker Local Dev

开始前可以先运行只读诊断：

```bash
bash scripts/dev/doctor.sh
```

它会检查 Docker Compose、Node/npm、根目录 `.venv`、前端依赖、本地 pid 文件和默认端口响应情况；不会启动服务、连接数据库或读取 private env 内容。

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
