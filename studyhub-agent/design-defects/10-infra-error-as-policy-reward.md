# Runtime or provider failure as policy Reward

- **Defect:** a timeout, parser crash or provider failure can be recorded as a failed trajectory even when the policy did not cause it.
- **Discovery:** v2 incident and Reward audit.
- **Evidence:** experiment artifacts include context/runtime failures alongside policy failures; v2 Reward consumes the resulting trace state.
- **Scope:** Reward labels, family failure rates and model updates.
- **Why systemic:** infrastructure noise creates false negative advantages and can teach avoidance of healthy tools.
- **Competing explanations:** malformed calls and repeated policy-triggered timeouts are legitimate policy failures.
- **Minimal falsification:** classify failed rollouts by ownership and replay infrastructure failures with the same policy action.
- **Root cause:** the pilot lacked a first-class failure-owner field.
- **Fix:** record `POLICY`, `ENVIRONMENT`, `PROVIDER` or `INFRA` ownership; retry/exclude non-policy failures.
- **Regression:** Reward v3 refuses to score unclassified fatal failures and reports exclusion rates.
- **Before/after:** undifferentiated failure -> owned, replayable failure semantics.
- **Residual risk:** causality can be ambiguous when a policy induces pathological load.
- **Interview 60s:** explain why observability is part of Reward correctness.
- **Deep dive:** define retry budgets and contamination thresholds.
