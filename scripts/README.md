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
- 清理源码缓存：`bash scripts/clean-generated.sh --source`
- 清理全部生成物并准备重新构建前端：`bash scripts/clean-generated.sh --all`
- 发布前检查：`bash scripts/predeploy-check.sh`
- 浏览器加载性能预算：`npm --prefix frontend run test:perf`

`predeploy-check.sh` 会串起后端测试、前端检查、前端单测、Playwright critical tests、代码体积检查和生产预检。只想在本地跑代码质量门禁时，可以临时跳过生产环境检查：

```bash
STUDYHUB_PREDEPLOY_PRODUCTION_CHECKS=0 bash scripts/predeploy-check.sh
```

`predeploy-check.sh` 默认使用 `--all` 清理生成物，适合本地和 CI。若必须在生产机器上检查源码但要保留当前运行中的 Next.js 构建产物，可以改用：

```bash
STUDYHUB_PREDEPLOY_CLEAN_MODE=source bash scripts/predeploy-check.sh
```

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
