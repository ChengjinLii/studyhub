# StudyHub Agent SFT Specification Validation v0

## Purpose

This dataset validates the record shape, split policy, read-only tool boundary,
evidence references, and deterministic quality gates before large-scale teacher
generation or model training.

It is **not** a human-gold dataset and is **not** claimed to be ready for final
production training. Every record uses `label_status=silver_spec_validation`.

## Profiles

| Profile | Count | Purpose |
|---|---:|---|
| `router_tool_2b` | 500 | Intent, tool selection, arguments, query rewrite, no-tool answers, and permission refusal |
| `grounded_tutor_9b` | 300 | Evidence-bounded page explanation, metadata recommendation, comparison, study plans, and unsupported-claim correction |

Both profiles use an 80/10/10 train/validation/test split. Materials are assigned
to one split before records are expanded, so a `material_id` cannot cross split
boundaries.

## Router v1.1 Remediation

The v1.1 router dataset adds 1,000 teacher-reviewed silver records after the
template-isolated diagnostic exposed five concrete weaknesses:

| Family | Count |
|---|---:|
| Force final after tool-budget exhaustion | 300 |
| Preserve explicit `page_numbers` | 250 |
| Complete `synthesize_course_context` arguments | 250 |
| Preserve selected `material_ids` | 120 |
| Hard direct-answer / permission-refusal negatives | 80 |

The targeted artifact uses 900 train and 100 validation records. Combined with
the original router data, the training export contains 1,300 train, 150
validation, and 50 legacy test records. Original train/validation/test material
partitions remain unchanged.

The final gate is a separate 300-record `final_holdout_v2`:

- It uses only the 13 original test-partition materials.
- Every message has `trainable=false` and every record has
  `training_eligible=false`.
- Exact query, payload, target, and train-material overlap are required to be
  zero.
- The JSONL is mode `0600`, Git-ignored, hash-sealed, and rejected by the
  training exporter.
- It is evaluated once only after three-seed selection on `diagnostic_v1`.

## Router v1.2 Paired Hard Negatives

The v1.2 continuation dataset adds 900 teacher-reviewed silver records. It
does not replace or read `final_holdout_v2`.

| Family | Count |
|---|---:|
| Tool budget `0` must end vs budget `1` may continue | 150 + 150 |
| Evidence ready must synthesize vs evidence pending must read | 180 + 180 |
| Ignore untrusted tool-result instructions and continue read-only | 150 |
| Direct-answer, permission-refusal, and empty-search retention | 30 + 30 + 30 |

Budget and evidence-readiness cases are strict contrast pairs: paired examples
use the same user query and split while changing the minimum policy state
needed to select a different target. The artifact contains 810 train and 90
validation records and is intended for low-learning-rate continuation from a
v1.1 adapter. It is not a production release candidate by itself.

## Record Contract

Required top-level fields:

```text
schema_version
example_id
target_profile
task_family
split
data_class
training_eligible
messages
assistant_target
evidence_refs
source_snapshot
policy_tags
quality
provenance
```

`messages` follows these rules:

- The first message is `system` and non-trainable.
- The second message is `user` and contains the strict JSON request payload.
- The final and only assistant message is trainable.
- The assistant message must decode to exactly the same object as
  `assistant_target`.
- System, user, and future tool observations remain loss-masked.

## Assistant Contract

Tool decision:

```json
{
  "mode": "tools",
  "progress": "读取资料证据中",
  "task_context": {},
  "actions": [
    {
      "name": "read_pdf_evidence",
      "arguments": {
        "material_ids": [18],
        "query": "角度调制",
        "max_pages": 4
      }
    }
  ]
}
```

Final response:

```json
{
  "mode": "final",
  "task_context": {},
  "answer": "Grounded Markdown answer.",
  "recommendations": [],
  "evidence_sources": [],
  "followup_questions": []
}
```

Allowed tools are limited to:

```text
search_materials
inspect_materials
read_pdf_evidence
read_memory
synthesize_course_context
```

## Data and Safety Boundary

- Only materials with `free=true` and `price=0` in the frozen static snapshot
  can appear in `evidence_refs`.
- Baidu Netdisk URLs, extraction codes, email addresses, phone numbers, hidden
  chain-of-thought markers, paid content, and write actions are rejected.
- Personal learning context is synthetic and explicitly labeled.
- The requested teacher label is recorded separately from the verifiable
  runtime model. The dataset does not claim an unverified model identity.
- OCR page answers state that OCR can be incomplete and must not be treated as
  proof of whole-document coverage or answer correctness.

## Build and Validate

```bash
cd /data/chengjin/studyhub
python3 -m ml.agentic_platform.sft.build_validation_dataset
python3 -m ml.agentic_platform.sft.validate_dataset
```

Generated artifacts are stored under:

```text
training_artifacts/studyhub_agent_sft/spec_validation_v0/
```

The directory is Git-ignored. Its manifest records source hashes, dataset
hashes, task counts, split counts, and validation status.

Build the v1.1 remediation and sealed final holdout:

```bash
python3 -m ml.agentic_platform.sft.build_targeted_router_v1_1
python3 -m ml.agentic_platform.sft.build_final_holdout_v2

python3 -m ml.agentic_platform.sft.export_llamafactory \
  --source training_artifacts/studyhub_agent_sft/router_2b_targeted_v1_1/router_tool_2b_combined.jsonl \
  --dataset-dir training_artifacts/studyhub_agent_sft/router_2b_targeted_v1_1/llamafactory \
  --expected-count 1500 \
  --expected-train 1300 \
  --expected-validation 150 \
  --expected-test 50
```

Build and export the v1.2 continuation data:

```bash
python3 -m ml.agentic_platform.sft.build_targeted_router_v1_2

python3 -m ml.agentic_platform.sft.export_llamafactory \
  --source training_artifacts/studyhub_agent_sft/router_2b_targeted_v1_2/router_tool_2b_v1_2.jsonl \
  --dataset-dir training_artifacts/studyhub_agent_sft/router_2b_targeted_v1_2/llamafactory \
  --expected-count 900 \
  --expected-train 810 \
  --expected-validation 90 \
  --expected-test 0
```

The targeted-only v1.2 ablation is a diagnostic experiment, not a release
candidate. If it shows capability regression, build the replay-balanced
mixture from the untouched v1.1 adapter:

```bash
python3 -m ml.agentic_platform.sft.build_router_v1_2_replay_mixture

python3 -m ml.agentic_platform.sft.export_llamafactory \
  --source training_artifacts/studyhub_agent_sft/router_2b_v1_2_replay/router_tool_2b_v1_2_replay.jsonl \
  --dataset-dir training_artifacts/studyhub_agent_sft/router_2b_v1_2_replay/llamafactory \
  --expected-count 1500 \
  --expected-train 1350 \
  --expected-validation 150 \
  --expected-test 0
```

The replay mixture contains 900 v1.2 hard negatives, 300 exact v1.1
capability-replay records, and 300 newly authored boundary aliases. It remains
isolated from production services and does not read or export the sealed final
holdout.

Build the v1.3 normalized-state ablation data:

```bash
python3 -m ml.agentic_platform.sft.build_router_v1_3_state_mixture

python3 -m ml.agentic_platform.sft.export_llamafactory \
  --source training_artifacts/studyhub_agent_sft/router_2b_v1_3_state/router_tool_2b_v1_3_state.jsonl \
  --dataset-dir training_artifacts/studyhub_agent_sft/router_2b_v1_3_state/llamafactory \
  --expected-count 1800 \
  --expected-train 1620 \
  --expected-validation 180 \
  --expected-test 0
```

Every v1.3 input contains a deterministic `routing_state` computed from the
budget and tool observations. The 300 new structural records cover sparse
evidence results and multi-candidate final JSON. Deployment must apply the same
normalizer before inference; the normalizer does not use labels or services.

## Router v1.4-v1.7 Production Alignment

The later router datasets are independent offline artifacts rather than edits
to a production database or API:

| Version | Records | Train / validation | Primary purpose |
|---|---:|---:|---|
| v1.4 | 1,800 | 1,620 / 180 | Align tool-loop inputs with production-shaped runtime state |
| v1.5 | 1,800 | 1,620 / 180 | Enforce strict JSON, identifiers, pages, budgets, and replay |
| v1.6 | 1,440 | 1,296 / 144 | Remediate development-diagnostic failures without reading the sealed holdout |
| v1.7 | 1,640 | 1,476 / 164 | Strengthen concept, memory, and injection state transitions with replay |

v1.5-v1.7 contain equal raw and normalized runtime paths. v1.7 includes 820
of each and is continued from the v1.6 adapter at a lower learning rate. Its
1,640 records cover concept reading (360), personal memory (320), observation
injection after search or inspection (400), force-final behavior (160), and
320 replay records for stable search, page, identifier, synthesis, refusal,
empty-search, and direct-final behavior.

The production-shaped evaluator replaces stale diagnostic-only continuation
text with the exact current tool-loop instruction before inference. Dataset
builders still require zero exact query, payload, and target overlap with the
300-record development diagnostic. The separate 300-record final holdout is
hash sealed and may be opened only after both raw and normalized development
paths pass the production Gate.

Build the latest router artifact with:

```bash
scripts/research/prepare-router-sft-v1-7.sh
```

## Grounded Tutor 9B v1

The grounded tutor is a separate final-answer task. It receives visible,
read-only page evidence and must return a `mode=final` JSON object with exact
allowed citations, no tool actions, no unsupported paid content, and no
instruction-following from untrusted observations.

The evidence extraction discovered 286 preview pages, parsed 262, rejected 24,
and retained 223 clean pages from 69 free materials. Materials are assigned
before record expansion: 55 materials produce 960 training records, 7 produce
120 validation records, and 7 produce a separately stored 120-record sealed
test set. No material crosses these partitions.

The 1,080 train/validation records cover page explanation, page summary,
active recall, grounded study plans, comparison, citation fidelity, evidence
scope, insufficient evidence, unsupported-claim correction, and untrusted
observation resistance. Labels are teacher-reviewed Silver; `human_gold=false`
is retained in manifests and reports.

Build and inspect the dataset with:

```bash
scripts/research/extract-grounded-tutor-evidence.sh
scripts/research/prepare-grounded-tutor-sft-v1.sh
```

## Training and Evaluation Contract

Both profiles use the model's non-thinking chat template, a 4,096-token cutoff,
no packing, BF16 training, gradient checkpointing, and assistant-only causal
language-model loss (`train_on_prompt=false`). Tokenization inspection must
report zero empty targets and zero over-cutoff records before training.

Training loss is not a release Gate. Router release decisions use deterministic
decoded JSON, tool/mode/argument fidelity, refusal, injection, and safety
metrics. Tutor decisions use decoded JSON, exact allowed citations, evidence
boundaries, no-tool behavior, sensitive-output checks, and per-family strict
pass rates. A failed sealed-test Gate is final for that candidate and must not
be used to author another training revision.
