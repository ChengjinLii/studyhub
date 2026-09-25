# SFT and Hermes RL action-space parity

- **Defect:** v2 SFT often answers from provided evidence, while RL expects the policy to search, read and act through Hermes.
- **Discovery:** 2026-08-27 v3 baseline audit.
- **Evidence:** `scripts/data/build_open_sft_bootstrap.py`, `scripts/data/build_open_rl_tasks.py`, and the 4B experiment report describe different policy-visible representations.
- **Scope:** SFT cold start, tool identity, citation grammar, context handling and subsequent GRPO exploration.
- **Why systemic:** a low SFT loss can initialize a policy outside the behavior space used during RL.
- **Competing explanations:** the 9B base may already bridge the representation gap; observed failures may instead come from Reward v2.
- **Minimal falsification:** replay 200 SFT records through the pinned Hermes exporter and require exact role, tool-call, observation, citation and loss-mask parity.
- **Root cause:** the original 3k SFT set was normalized before the final Hermes/AReaL runtime was fixed.
- **Fix:** build at least 70% of v3 SFT from runtime-native Hermes trajectories and validate every conversion.
- **Regression:** a parity checker blocks records with foreign tool text, missing observations or assistant loss on tool outputs.
- **Before/after:** v2 given-evidence imitation -> v3 policy-visible Agent trajectories.
- **Residual risk:** teacher trajectories can be runtime-correct but strategically poor.
- **Interview 60s:** explain why format validity is not action-space parity and how replay catches the difference.
- **Deep dive:** compare token/loss masks and the next observation at every Hermes step.
