# Hermes Integration

StudyHub Agent uses Hermes as a pinned upstream runtime. The upstream source is
not vendored into this repository.

- `upstream.lock.json` records the exact upstream commit and patch digest.
- `patches/0001-studyhub-branding.patch` contains the minimal CLI branding and
  project-owned skin override support.
- `skins/studyhub.yaml` contains the StudyHub visual identity.

Prepare or verify a checkout:

```bash
cd /data/chengjin/studyhub/studyhub-agent
scripts/setup-hermes.sh
scripts/setup-hermes.sh /data/chengjin/hermes-agent
```

The default clean checkout location is `studyhub-agent/.vendor/hermes-agent`,
which is ignored by Git. Dependency installation remains a separate Hermes
operation so this repository never commits its virtual environment,
`node_modules`, credentials, or messaging account state.
