# scripts/workers

这里放 worker 与 scheduler 相关脚本。

## Worker

```bash
STUDYHUB_ENVIRONMENT=preview bash scripts/workers/worker-up.sh
STUDYHUB_ENVIRONMENT=preview bash scripts/workers/worker-status.sh
STUDYHUB_ENVIRONMENT=preview bash scripts/workers/worker-down.sh
```

常用环境变量：

- `WORKER_JOB=all|settlement|request-maintenance|request-refund|payout-transfer`
- `WORKER_INTERVAL_SECONDS=60`

## Scheduler

```bash
STUDYHUB_ENVIRONMENT=preview bash scripts/workers/scheduler-up.sh
STUDYHUB_ENVIRONMENT=preview bash scripts/workers/scheduler-status.sh
STUDYHUB_ENVIRONMENT=preview bash scripts/workers/scheduler-down.sh
```

当前 `scheduler-*` 是对 `worker-*` 的便捷包装，默认以 `WORKER_JOB=all` 运行。
