# Upstream and Modification Notice

- Source: https://github.com/OmniJev/OneJev
- Copied revision: `81ce62f1597c91e46767d4d02d6ac2e18534fe94`
- Upstream commit date: 2026-10-01
- Copy date: 2026-10-05
- Upstream license: Apache-2.0, retained in `LICENSE`.

The snapshot was copied with `git archive`, without a nested Git repository or model weights.
The original `qev/`, `train/`, benchmarks, examples, assets and tests are retained as reference
and inference code. The upstream README was renamed to `README.onejev.md`.

StudyHub additions are `review_jev/`, `tests/test_review*.py`, review examples, this notice,
and the replacement README. Packaging and ignore rules were changed for the standalone fork.
Added code uses the same Apache-2.0 license. This is not an official OmniJev or TypeSafe release.

`qev/answers.py` retains its original notice for TypeSafe adapter-derived confidence formulas
(MIT License, Copyright (c) 2026 TypeSafe AI). Underlying model and dataset licenses and media
rights are separate from this code license. The fork does not grant redistribution rights to
user-submitted materials or upstream training media.

No StudyHub-specific weights have been trained. No moderation accuracy, latency, copyright
verification capability or StudyHub calibration is asserted by this development release.

The standalone layer additionally supports Qwen's Apache-2.0 Qwen3Guard-Gen-0.6B for text.
Default routing sends validated image-containing submissions to OneJev-4B and text-only
submissions to Qwen3Guard. Native categories are not represented as calibrated probabilities.
Uncovered custom policies require human review. Model weights remain outside the Git repository.
The default model revisions are pinned in `review_jev/config.py`; smoke testing uses synthetic
local content and does not connect to the website or a database.
