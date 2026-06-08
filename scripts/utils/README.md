# scripts/utils

这里放通用辅助脚本。

## Health Check

```bash
bash scripts/utils/healthcheck.sh http://127.0.0.1:8211
```

可用于快速探测 backend 或其他 HTTP 服务是否正常响应。
默认使用 5 秒连接超时和 20 秒总超时，可用 `STUDYHUB_CURL_CONNECT_TIMEOUT` / `STUDYHUB_CURL_MAX_TIME` 调整，值必须是大于 0 的秒数。
