# StudyHub QQ Bot

StudyHub QQ Bot 是一个面向 QQ 群的资料推荐引流机器人。它通过 OneBot v11 HTTP 网关接收群消息，检索 StudyHub 公开资料目录，并只回复资料页链接。

## 安全边界

- 只推荐 StudyHub 站内资料页链接。
- 不返回下载链接、OSS 签名 URL、网盘链接、提取码或文件内容。
- 不使用用户登录态，不代用户购买或下载。
- 只响应配置的命令前缀，默认不会监听群内所有聊天。
- 可配置群号 allowlist 和 webhook secret，避免被未知来源调用。

## 运行

```bash
cd /data/studyhub
STUDYHUB_QQ_BOT_STUDYHUB_BASE_URL=https://study-hub.store \
STUDYHUB_QQ_BOT_PUBLIC_SITE_BASE_URL=https://study-hub.store \
STUDYHUB_QQ_BOT_ONEBOT_API_BASE_URL=http://127.0.0.1:3000 \
STUDYHUB_QQ_BOT_ONEBOT_ACCESS_TOKEN=<onebot-token> \
STUDYHUB_QQ_BOT_WEBHOOK_SECRET=<webhook-secret> \
.venv/bin/python -m bots.qq_studyhub_bot
```

服务默认监听 `0.0.0.0:8321`，OneBot 反向 HTTP 上报地址配置为：

```text
http://127.0.0.1:8321/onebot/events
```

如果配置了 `STUDYHUB_QQ_BOT_WEBHOOK_SECRET`，上报请求必须带：

```text
X-StudyHub-QQ-Bot-Secret: <webhook-secret>
```

## 环境变量

| 变量 | 说明 |
| --- | --- |
| `STUDYHUB_QQ_BOT_STUDYHUB_BASE_URL` | StudyHub 后端/站点 API 基址，默认 `https://study-hub.store` |
| `STUDYHUB_QQ_BOT_PUBLIC_SITE_BASE_URL` | 生成资料页链接的公开站点基址，默认同上 |
| `STUDYHUB_QQ_BOT_ONEBOT_API_BASE_URL` | OneBot HTTP API 地址，例如 `http://127.0.0.1:3000` |
| `STUDYHUB_QQ_BOT_ONEBOT_ACCESS_TOKEN` | OneBot API token，可选但建议配置 |
| `STUDYHUB_QQ_BOT_WEBHOOK_SECRET` | 反向上报 webhook secret，可选但建议配置 |
| `STUDYHUB_QQ_BOT_ALLOWED_GROUP_IDS` | 逗号分隔的群号 allowlist；为空表示不限制 |
| `STUDYHUB_QQ_BOT_COMMAND_PREFIXES` | 逗号分隔的命令前缀，默认 `/studyhub,/sh,资料,求资料,找资料` |
| `STUDYHUB_QQ_BOT_MAX_RESULTS` | 每次最多推荐数量，默认 3，最大 6 |
| `STUDYHUB_QQ_BOT_TIMEOUT_SECONDS` | 请求超时，默认 8 秒 |

## 群内用法

```text
资料 概率论 真题
/studyhub 随机信号 期末
/sh 数据结构 复习
```

机器人会回复资料标题、价格/免费状态、学校学院、标签、推荐理由和 StudyHub 资料页链接。

## OneBot 说明

该服务只依赖 OneBot v11 的两个能力：

- 反向 HTTP 上报群消息事件到 `/onebot/events`
- HTTP API `send_group_msg` 发送群消息

因此可以放在 QQ 网关旁边独立部署，也可以放在 StudyHub 后端同机部署。

