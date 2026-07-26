# Agentic domain contract snapshots

`agentic-domain-schema-golden-v1.json` is the versioned golden manifest for the
Pydantic v2 domain schemas introduced in PR2. Its SHA-256 values are calculated
from sorted, compact UTF-8 JSON and are enforced by
`backend/tests/agentic_platform/test_domain_hashing.py`.

To inspect the complete export without checking generated bulk JSON into source
control, run from `backend/`:

```bash
../.venv/bin/python ../scripts/agentic/export-domain-schemas.py
```

Changing any public contract intentionally requires updating the model, tests,
and this manifest in the same review.
