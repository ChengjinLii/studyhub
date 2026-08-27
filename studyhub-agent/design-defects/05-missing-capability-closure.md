# Missing capability closure

- **Defect:** Web, Memory, abstention, fallback, recovery, conflict and long-horizon capabilities have adapters but no complete SFT/RL/Dev/Sealed chain.
- **Discovery:** 2026-08-27 capability audit.
- **Evidence:** `src/studyhub_agent/adapters/` exposes contracts, while v2 datasets and Eval32 cover mainly function calling and toy Search/Read.
- **Scope:** product relevance and every statement about an autonomous StudyHub Agent.
- **Why systemic:** interface existence can be mistakenly promoted to trained capability.
- **Competing explanations:** a strong base model may already perform some abilities zero-shot.
- **Minimal falsification:** run the 9B Base on a capability-stratified benchmark before assigning any trained state.
- **Root cause:** training scope followed readily available open datasets rather than the product capability matrix.
- **Fix:** make the 20-entry capability matrix the only scope source and require stage-specific evidence.
- **Regression:** capability states advance only through CONTRACT_ONLY, SFT, RL, DEV, SEALED and SUPPORTED_CLAIM evidence.
- **Before/after:** adapter inventory -> capability lifecycle with task and metric budgets.
- **Residual risk:** equal task counts do not imply equal task quality or difficulty.
- **Interview 60s:** describe why a tool schema proves compatibility, not learned policy.
- **Deep dive:** map each capability to data tags, environment variants and benchmark slices.
