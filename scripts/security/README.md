# scripts/security

这里放仓库安全卫生检查脚本。

## Sensitive Files

```bash
bash scripts/security/check-sensitive-files.sh
```

该脚本会检查当前 Git 已跟踪文件名和可见 Git 历史文件名，防止真实 `.env`、`private/`、私钥、证书等高风险文件误提交；`.env.example` 示例文件允许保留。
