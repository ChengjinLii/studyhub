# studyhub scripts

`scripts/` 按用途拆成了几个子目录，避免开发脚本、部署脚本、worker 脚本和数据库脚本混在一起。

## 目录索引

- [`scripts/dev/`](dev/README.md)：本地开发与快速体验
- [`scripts/runtime/`](runtime/README.md)：preview / production 启停与 smoke check
- [`scripts/workers/`](workers/README.md)：worker 与 scheduler
- [`scripts/db/`](db/README.md)：数据库检查、备份、恢复
- [`scripts/utils/`](utils/README.md)：通用辅助脚本
- [`scripts/security/`](security/README.md)：仓库安全卫生检查

## 常用入口

- 本地环境诊断：`bash scripts/dev/doctor.sh`
- 本地开发：`bash scripts/dev/docker-dev-up.sh`
- 轻量启动：`bash scripts/dev/local-dev-up.sh`
- 预发布运行：`bash scripts/runtime/preview-up.sh`
- 生产运行：`bash scripts/runtime/production-up.sh`
- 清理源码缓存：`bash scripts/clean-generated.sh --source`
- 清理全部生成物并准备重新构建前端：`bash scripts/clean-generated.sh --all`
- 检查 shell 脚本语法：`bash scripts/check-shell-scripts.sh`
- 检查敏感文件误提交：`bash scripts/security/check-sensitive-files.sh`
- 非生产 CI 检查：`bash scripts/ci-check.sh`
- 发布前检查：`bash scripts/predeploy-check.sh`
- 浏览器加载性能预算：`npm --prefix frontend run test:perf`

`check-shell-scripts.sh` 只执行 `bash -n`，不会运行脚本主体，也不会连接数据库或修改运行态。

`scripts/dev/doctor.sh` 是只读诊断脚本，用来检查 Docker local-dev 和 shell quickstart 至少有一条路径是否可用；它不会启动服务、连接数据库、读取 private env 内容或修改运行态。

`ci-check.sh` 面向 PR / CI / 本地代码质量门禁，包含 shell 语法、敏感文件、后端测试、前端 check、前端 unit、Playwright critical 和代码体积检查；它不会运行 production preflight、nginx 检查或 systemd 状态检查。

`predeploy-check.sh` 会串起 shell 脚本语法、后端测试、前端检查、前端单测、Playwright critical tests、代码体积检查和生产预检。只想在本地跑代码质量门禁时，可以临时跳过生产环境检查：

```bash
STUDYHUB_PREDEPLOY_PRODUCTION_CHECKS=0 bash scripts/predeploy-check.sh
```

生产机器上，`predeploy-check.sh` 默认要求 `studyhub-backend.service`、`studyhub-frontend.service` 和 `studyhub-worker.service` 均为 active，避免后台结算、退款和维护任务在上线前被漏掉。只做本地代码门禁时可以跳过运行时检查：

```bash
STUDYHUB_PREDEPLOY_RUNTIME_CHECKS=0 STUDYHUB_PREDEPLOY_PRODUCTION_CHECKS=0 bash scripts/predeploy-check.sh
```

如某个部署形态确实不需要 worker，可以显式覆盖必需服务列表：

```bash
STUDYHUB_PREDEPLOY_REQUIRED_SYSTEMD_SERVICES="studyhub-backend.service studyhub-frontend.service" bash scripts/predeploy-check.sh
```

`predeploy-check.sh` 默认使用 `--source` 清理源码缓存和测试产物，并保留当前运行可能依赖的 Next.js 构建产物。若在本地或 CI 中准备重新构建前端，可以显式改用全量清理：

```bash
STUDYHUB_PREDEPLOY_CLEAN_MODE=all bash scripts/predeploy-check.sh
```

`STUDYHUB_PREDEPLOY_CLEAN_MODE` 只接受 `source` / `all`；`STUDYHUB_PREDEPLOY_PRODUCTION_CHECKS` 和 `STUDYHUB_PREDEPLOY_RUNTIME_CHECKS` 只接受 `auto` / `1` / `true` / `0` / `false`。

如果当前仓库带有 `private/.env.production` 或 `STUDYHUB_ENVIRONMENT=production`，`clean-generated.sh --all` 会拒绝删除 `frontend/.next`，除非额外设置 `YES_PRODUCTION_CLEAN_FRONTEND_BUILD=I_UNDERSTAND_REBUILD_FRONTEND`。

更具体的命令、环境变量和注意事项已经分别下沉到各子目录 README。

## 浏览器加载性能预算

`frontend/scripts/perf-budget.mjs` 会用 Chromium 打开页面并读取浏览器 Navigation Timing，默认按 `DOMContentLoaded p95 <= 200ms` 检查：

```bash
npm --prefix frontend run test:perf
```

常用配置：

```bash
PERF_BASE_URL=https://study-hub.cn npm --prefix frontend run test:perf
PERF_BASE_URL=https://110.42.223.173 PERF_ROUTES=/,/more,/market npm --prefix frontend run test:perf
PERF_DYNAMIC_ROUTES=/materials/1,/market/1 PERF_SAMPLE_RUNS=5 npm --prefix frontend run test:perf
```

默认会 warmup 一次，让浏览器缓存和 service worker 生效，再采样 3 次。要测完全冷启动，可以设置 `PERF_WARMUP_RUNS=0`。网络抖动会直接影响结果，所以这个检查是部署验证工具，不放进默认 `predeploy-check.sh`。
