# Runtime-SFT-v3.0 Source Audit

Status: `PASS`
Selected SHA-256: `a115d220841a0e56c8893a01e486c8399c24cb591143f221c78a926deee42783`
Benchmark prompt overlap: `0` / `73`

## Dataset Summary

| Item | Value |
| --- | ---: |
| Rows | 48,500 |
| Total tokens | 61,725,581 |
| Assistant-loss tokens | 9,062,215 |
| Assistant fraction | 14.68% |
| Action-only rows | 6,158 |
| Deterministic fixture rows | 20,000 |
| Teacher-verified rows | 0 |

The 6,158 action-only rows are ToolACE 5,753 and Hermes Function Calling 405. The 20,000 deterministic fixtures are StudyHub metadata 6,000, memory 4,000, ACL 4,000, Web 3,000, and state tools 3,000. `runtime_native` means runtime-schema compatible; it does not mean a teacher model autonomously executed the trajectory.

## Source Detail

| Source | Rows | Complete | Action-only | Runtime-native | Total tokens | Assistant tokens | Assistant % | Groups | Group p90/max | Template clusters | Largest template | Tool paths | Largest path |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| coig_exam | 4,500 | 4,500 | 0 | 0.0% | 1,564,599 | 337,898 | 21.6% | 4,500 | 1/1 | 4,470 | 0.1% | 1 | 100.0% |
| hermes_function_calling | 2,600 | 2,195 | 405 | 35.7% | 3,595,505 | 697,352 | 19.4% | 2,600 | 1/1 | 2,322 | 0.3% | 990 | 61.3% |
| studyhub_2wiki_replay | 12,000 | 12,000 | 0 | 100.0% | 24,260,902 | 2,902,971 | 12.0% | 12,000 | 1/1 | 11,999 | 0.0% | 2 | 97.3% |
| studyhub_acl_recovery | 4,000 | 4,000 | 0 | 100.0% | 3,905,071 | 690,700 | 17.7% | 1,905 | 4/13 | 2,559 | 1.9% | 1 | 100.0% |
| studyhub_memory_replay | 4,000 | 4,000 | 0 | 100.0% | 4,932,665 | 762,337 | 15.5% | 101 | 52/70 | 10 | 10.4% | 1 | 100.0% |
| studyhub_metadata_replay | 6,000 | 6,000 | 0 | 100.0% | 6,311,557 | 823,135 | 13.0% | 99 | 118/138 | 3,167 | 4.2% | 1 | 100.0% |
| studyhub_qasper_replay | 3,000 | 3,000 | 0 | 100.0% | 3,435,234 | 486,445 | 14.2% | 1,117 | 5/11 | 2,999 | 0.1% | 4 | 56.6% |
| studyhub_state_tools | 3,000 | 3,000 | 0 | 100.0% | 4,287,551 | 735,022 | 17.1% | 101 | 40/50 | 40 | 3.0% | 1 | 100.0% |
| studyhub_web_fallback | 3,000 | 3,000 | 0 | 100.0% | 3,294,585 | 664,303 | 20.2% | 101 | 40/49 | 4 | 26.0% | 1 | 100.0% |
| toolace | 6,400 | 647 | 5,753 | 10.1% | 6,137,912 | 962,052 | 15.7% | 6,400 | 1/1 | 6,382 | 0.0% | 6,256 | 0.0% |

## Provenance and Concentration

### coig_exam

- Quality tiers: `{"expert_complete": 4500}`
- Observation origin: `{"no_tool_observation": 4500}`
- Rows/group p50, p90, max: `1`, `1`, `1`
- Final-answer signatures: `3050`; largest exact normalized answer share: `8.31%`
- Language: `{"en": 21, "zh": 4479}`; citation rate: `0.00%`

### hermes_function_calling

- Quality tiers: `{"expert_action_only": 405, "expert_complete": 2195}`
- Observation origin: `{"no_complete_observation_and_final": 405, "no_tool_observation": 1268, "open_dataset_recorded_or_converted": 927}`
- Rows/group p50, p90, max: `1`, `1`, `1`
- Final-answer signatures: `2126`; largest exact normalized answer share: `0.15%`
- Language: `{"en": 2597, "zh": 3}`; citation rate: `0.00%`

### studyhub_2wiki_replay

- Quality tiers: `{"oracle_derived_expert_complete": 12000}`
- Observation origin: `{"oracle_derived_replay": 12000}`
- Rows/group p50, p90, max: `1`, `1`, `1`
- Final-answer signatures: `12000`; largest exact normalized answer share: `0.01%`
- Language: `{"en": 12000}`; citation rate: `100.00%`

### studyhub_acl_recovery

- Quality tiers: `{"deterministic_fixture_complete": 4000}`
- Observation origin: `{"deterministic_fixture": 4000}`
- Rows/group p50, p90, max: `2`, `4`, `13`
- Final-answer signatures: `982`; largest exact normalized answer share: `0.33%`
- Language: `{"zh": 4000}`; citation rate: `100.00%`

### studyhub_memory_replay

- Quality tiers: `{"deterministic_fixture_complete": 4000}`
- Observation origin: `{"deterministic_fixture": 4000}`
- Rows/group p50, p90, max: `41`, `52`, `70`
- Final-answer signatures: `404`; largest exact normalized answer share: `0.53%`
- Language: `{"zh": 4000}`; citation rate: `100.00%`

### studyhub_metadata_replay

- Quality tiers: `{"deterministic_fixture_complete": 6000}`
- Observation origin: `{"deterministic_fixture": 6000}`
- Rows/group p50, p90, max: `56`, `118`, `138`
- Final-answer signatures: `570`; largest exact normalized answer share: `0.47%`
- Language: `{"zh": 6000}`; citation rate: `100.00%`

### studyhub_qasper_replay

- Quality tiers: `{"oracle_derived_expert_complete": 3000}`
- Observation origin: `{"oracle_derived_replay": 3000}`
- Rows/group p50, p90, max: `2`, `5`, `11`
- Final-answer signatures: `2605`; largest exact normalized answer share: `10.13%`
- Language: `{"en": 3000}`; citation rate: `86.67%`

### studyhub_state_tools

- Quality tiers: `{"deterministic_fixture_complete": 3000}`
- Observation origin: `{"deterministic_fixture": 3000}`
- Rows/group p50, p90, max: `31`, `40`, `50`
- Final-answer signatures: `1147`; largest exact normalized answer share: `0.30%`
- Language: `{"zh": 3000}`; citation rate: `100.00%`

### studyhub_web_fallback

- Quality tiers: `{"deterministic_fixture_complete": 3000}`
- Observation origin: `{"deterministic_fixture": 3000}`
- Rows/group p50, p90, max: `31`, `40`, `49`
- Final-answer signatures: `404`; largest exact normalized answer share: `0.53%`
- Language: `{"zh": 3000}`; citation rate: `100.00%`

### toolace

- Quality tiers: `{"expert_action_only": 5753, "expert_action_synthetic_observation": 647}`
- Observation origin: `{"no_complete_observation_and_final": 5753, "synthetic_observation": 647}`
- Rows/group p50, p90, max: `1`, `1`, `1`
- Final-answer signatures: `750`; largest exact normalized answer share: `0.02%`
- Language: `{"en": 6398, "zh": 2}`; citation rate: `0.00%`

## Interpretation

The current v3.0 release is a valid frozen cold-start baseline, not a teacher-policy dataset. Oracle 2Wiki/QASPER rows teach successful evidence paths; deterministic StudyHub rows teach schemas and reproducible outcomes; action-only rows do not teach observation-following or final answers. The per-source template metric is a deterministic template proxy, not an embedding-based semantic cluster. These distinctions drive the separate v3.1 teacher candidate and prevent fixtures from being promoted to teacher quality.
