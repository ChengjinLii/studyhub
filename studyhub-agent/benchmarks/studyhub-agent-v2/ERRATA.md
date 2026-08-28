# AgentBench v2.0 Errata and Governance Notes

This file clarifies claims around the frozen `studyhub-agentbench-v2` release. It
does not modify any task, environment, grader, hidden split, or manifest entry.
The frozen manifest SHA-256 remains
`da804b10f53dec585255598c3e256445b8ade3acf35fd8c766ca0ab4d759c88b`.

## Diversity terminology

The historical phrase "Development 51/51 semantic clusters" refers to a
capability-scoped lexical/Jaccard clustering audit. It is a structural and
lexical diversity proxy, not evidence that 51 tasks received independent
semantic review.

Independent human review and an external LLM judge remain `NOT_RUN`. The
recorded review is a Codex self-review and must not be described as human or
independent expert review.

## Statistical scope

Development contains 51 tasks. The Base calibration estimated an approximate
80% power minimum detectable effect of 17.865 percentage points. Smaller
changes are directional paired evidence only and do not establish a stable
capability improvement.

The split is concentrated in factual passage retrieval and cross-chunk
synthesis: 26 of 51 tasks belong to those two families. Web, recovery, long
horizon, state, and stop/cost behavior have only sparse coverage. Overall
strict success must therefore be reported with capability slices and cannot be
generalized to broad Agentic or Deep Research ability.

## Contamination wording

The original single phrase "Benchmark prompt overlap = 0" is replaced by the
following separate claims:

- Public prompt exact/hash overlap: `0 / 73` across Regression, Development,
  and Calibration Challenge public prompts.
- Sealed task and grader content was not read by the training pipeline.
- Sealed isolation is supported by source/material partitions, ignored hidden
  artifacts, and the access policy. It is not based on directly comparing all
  98 prompt texts inside the training audit.

On 2026-08-29, the legacy manifest validator performed one local integrity
pass over 18 hidden files because hidden validation was its default. It hashed
files and checked hidden-manifest binding; it did not parse task/grader
semantics, export content, run a model, or feed any result into training,
Teacher generation, checkpoint selection, or evaluation. This process
deviation is recorded in `HIDDEN_ACCESS_LEDGER.json`. The validator now
defaults to public-only validation; hidden integrity checks require both an
explicit flag and `STUDYHUB_ALLOW_SEALED_VALIDATION=YES`.

These statements must remain separate in future reports.

## Development exposure

Development has been used repeatedly for Base, Mixed-v3.0, and the invalid
Open-Only-v1 diagnostic run. It is an iteration set, not an untouched final
test. New uses must be appended to `DEVELOPMENT_EXPOSURE_LEDGER.json` before a
result is used for model selection.

Sealed-A and Sealed-B remain unused for model execution, scoring, training,
Teacher generation, and model selection. They may be opened for final model
evaluation once only after the dataset, recipe, checkpoint, promotion rule,
internal variance, and official external results are frozen.

## Allowed claim

AgentBench v2.0 is a small, product-aligned internal benchmark suitable for
runtime regression, paired checkpoint comparison, failure taxonomy, and
protocol/citation checks. It does not by itself establish broad Agent ability,
external validity, or final model confirmation.
