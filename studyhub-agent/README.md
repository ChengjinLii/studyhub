# StudyHub Agent V2

This directory is isolated from the StudyHub website runtime. The legacy Agent,
training, evaluation, memory, router, and orchestration implementations were
removed before the V2 rebuild.

The only retained historical asset is:

```text
ai_platform/rag_experiments/
```

It is a standalone retrieval research project and is not imported by
`backend/` or `frontend/`. Website data, authentication, authorization,
payments, storage, and database access remain owned by the main application.

Hermes integration will be bootstrapped separately from a clean pinned
upstream checkout. No legacy StudyHub router, memory implementation, patch, or
skin is carried into V2.
