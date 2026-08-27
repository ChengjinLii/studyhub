# StudyHub Agentic Post-Training v3: Primary-Source Review

Review date: 2026-08-27

Scope: training architecture, external evaluation, runtime-native data, path-agnostic reward, Agent RL algorithms and dual-H100 execution.

Rule: a decision below is a design input, not evidence that StudyHub has reproduced an external result.

## Decision summary

| Asset | Decision | StudyHub use |
|---|---|---|
| OpenAI Deep Research | ADAPT | Use its end-to-end browsing, synthesis, citation and prompt-injection threat model as a capability reference. |
| Hermes Agent | ADOPT | Keep as the only Agent loop; use its batch runner as a trajectory-generation mechanism after parity checks. |
| AReaL + SGLang | ADOPT | Keep the pinned rollout/update/serving stack; profile rather than assume 2-GPU efficiency. |
| BFCL V4 | ADOPT | Mandatory external function, multi-turn, Web and Memory evaluation under the official protocol. |
| tau3-bench / tau-Knowledge | ADAPT | External interaction slice and reference for replayable knowledge retrieval; do not replace StudyHub tools. |
| DeepResearch Bench | ADOPT | Mandatory long-form research evaluation with rubric and citation analysis. |
| BrowseComp | ADAPT | Difficult Web-search stress test; report full and subset protocols separately. |
| BrowseComp-Plus | DEFER | Audit its retriever/agent separation before deciding whether it adds information beyond BrowseComp. |
| GAIA / xbench-DeepSearch | DEFER | Optional broad and search-specific confirmation after mandatory external suites are affordable. |
| Anthropic research/eval guidance | ADAPT | Combine end-state, groundedness, coverage and source-quality graders; reject a new multi-agent architecture. |
| Search-R1 | ADAPT | Borrow interleaved search-RL and retriever evaluation ideas, not its runtime or gold-answer-only objective. |
| WebAgent-R1 / ReTool | DEFER | Use as mechanism references; their browser/code-tool environments do not match StudyHub's first main run. |
| WebRL / OpenWebRL / WebGym | DEFER | Audit curriculum and environment assets; do not introduce a visual-browser stack into the text-first mainline. |
| Agent-R1 | ADAPT | Borrow step-level observability and environment-owned transition checks; keep AReaL/Hermes. |
| SkyRL-Agent | DEFER | Long-horizon Gym abstraction is relevant, but a second trainer/Agent layer would duplicate the frozen stack. |
| OpenResearcher | DEFER | Candidate long-horizon SFT source pending license, teacher, length and runtime-parity audit. |
| HermesBench | DEFER | Third-party benchmark pending fixture, contamination and maintenance audit. |
| DAPO | DEFER | Enable dynamic sampling only when learnability calibration shows material zero-variance waste. |
| RLOO / REINFORCE++ / GSPO | DEFER | Use only when 9B diagnostics identify group-baseline, stability or sequence-ratio problems. |
| Dr. GRPO / CISPO / SAPO | DEFER | Keep as literature-only corrections for measured length, clipping or ratio pathologies. |
| OPD / KDRL | DEFER | Require a qualified teacher that can score student-visited action tokens and add capabilities beyond the student. |
| DPO / KTO / IPO | REJECT as mainline | Retain only as offline preference baselines; they do not train online tool interaction. |
| Outcome / Process Reward Model | ADAPT | Use calibrated learned graders only where deterministic end-state checks are insufficient. |
| Agent Lightning | DEFER | Its tracing/store separation is useful, but replacing the pinned stack has no current evidence value. |
| PPO / RLOO / REINFORCE / GSPO variants | DEFER | Enter GPU comparison only when an observed GRPO failure identifies a testable advantage. |

## Hermes Agent batch trajectories

- **Problem:** SFT must reflect the exact policy-visible Hermes loop instead of static foreign tool text.
- **Primary source:** [Hermes Agent repository](https://github.com/NousResearch/hermes-agent), [official batch-processing guide](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/features/batch-processing.md).
- **Mechanism:** isolated batch sessions export full conversation histories, tool statistics and structured trajectories.
- **Preconditions:** use the pinned Hermes commit; freeze tool schemas; verify assistant/tool roles, observations, final answers, context limits and loss masks.
- **Evidence:** the official guide states that batch processing is intended to generate trajectories at scale and exports ShareGPT-format histories with tool-use statistics.
- **Cost:** teacher inference, tool replay and quality review.
- **StudyHub difference:** trajectories must include StudyHub RAG, Web, Memory, ACL and learning tasks; generic Hermes traces alone do not provide product coverage.
- **Decision:** **ADOPT** the mechanism; generated records remain candidates until runtime parity and teacher-success gates pass.

## OpenAI Deep Research

- **Problem:** the target Agent must sustain multi-step browsing, pivot after new evidence, synthesize many sources and resist Web prompt injection.
- **Primary source:** [Deep Research System Card](https://openai.com/index/deep-research-system-card/), [product research description](https://openai.com/index/introducing-deep-research/).
- **Mechanism:** end-to-end reinforcement learning on browsing/reasoning tasks teaches search, interpretation, file reading, Python use and cited synthesis.
- **Preconditions:** StudyHub must use replayable Web environments, explicit source provenance, privacy controls and prompt-injection evaluation.
- **Evidence:** the system card states that Deep Research was trained on browsing datasets and RL tasks and identifies privacy, hallucination and prompt injection as specific risks.
- **Cost:** long trajectories, Web/tool execution and safety evaluation.
- **StudyHub difference:** StudyHub is a 9B open model with RAG/Memory/ACL constraints and cannot reproduce proprietary training data or system scale.
- **Decision:** **ADAPT** the capability, safety and evaluation principles; do not claim architectural or performance equivalence.

## AReaL and SGLang

- **Problem:** collect policy log probabilities and update a 9B policy while retaining the real Hermes loop.
- **Primary source:** [AReaL repository](https://github.com/areal-project/AReaL), [Agent workflow reference](https://github.com/areal-project/AReaL/blob/main/docs/en/reference/agent_workflow.md), [allocation and CLI reference](https://github.com/areal-project/AReaL/blob/main/docs/en/cli_reference.md).
- **Mechanism:** an Agent workflow generates grouped rollouts through an inference backend while FSDP2 performs policy updates; allocation strings support data/tensor parallel layouts and colocation strategies.
- **Preconditions:** remain on commit `cbff54d645d2cd8ee1f1c358a82f3f473588433d` until a versioned upgrade experiment; preserve token/logprob lineage and checkpoint publication.
- **Evidence:** the pinned checkout contains `fsdp:d2` parsing, SGLang tensor-parallel allocation and a two-GPU colocated example using memory saver. This proves availability, not Qwen3.5-9B LoRA compatibility.
- **Cost:** compatibility Gate, communication overhead, weight refresh and memory offload/onload.
- **StudyHub difference:** sub-process Hermes rollouts and long multi-tool trajectories are more variable than the official math examples.
- **Decision:** **ADOPT** the current stack; compare 1+1 and 2-GPU colocated layouts with equal trajectory/token budgets before choosing the main run.

## BFCL V4

- **Problem:** internal tests cannot establish externally comparable function, multi-turn, Web or Memory capability.
- **Primary source:** [Berkeley Function-Calling Leaderboard V4](https://gorilla.cs.berkeley.edu/leaderboard).
- **Mechanism:** executable evaluation covers agentic Web search, Memory, multi-turn calls, single-turn calls, hallucination and format sensitivity.
- **Preconditions:** pin the official evaluation package/commit and report category-level results; do not mix an adapted subset with the official leaderboard score.
- **Evidence:** the official V4 leaderboard explicitly publishes these categories and its evaluated code version.
- **Cost:** adapter work, inference and live-tool variability for applicable categories.
- **StudyHub difference:** BFCL does not cover StudyHub material ACL, citation support or learning personalization.
- **Decision:** **ADOPT** as a mandatory external benchmark, alongside rather than instead of StudyHub Dev/Sealed.

## tau3-bench and tau-Knowledge

- **Problem:** StudyHub needs realistic user-tool interaction and retrieval evaluation beyond static function-call matching.
- **Primary source:** [tau2/tau3 official repository](https://github.com/sierra-research/tau2-bench), [tau-Knowledge retrieval guide](https://github.com/sierra-research/tau2-bench/blob/main/src/tau2/knowledge/README.md), [leaderboard submission protocol](https://github.com/sierra-research/tau2-bench/blob/main/docs/leaderboard-submission.md).
- **Mechanism:** task environments combine user simulation, tools and knowledge retrieval; the repository exposes Gym/RL integration and BM25/dense retrieval choices.
- **Preconditions:** freeze simulator and retrieval configuration, run the required repeated trials, record costs and keep any adaptation visibly separate from official scores.
- **Evidence:** official documentation specifies knowledge retrieval modes and repeated leaderboard trials.
- **Cost:** user-model calls, environment adaptation and stochastic variance.
- **StudyHub difference:** StudyHub users seek educational evidence and recommendations rather than customer-service transactions.
- **Decision:** **ADAPT** for an external slice and environment-design reference; do not transplant its runtime.

## DeepResearch Bench

- **Problem:** short-answer and end-state tests do not measure open-ended synthesis, coverage, source quality or citation support.
- **Primary source:** [official repository](https://github.com/Ayanami0730/deep_research_bench), [paper](https://arxiv.org/abs/2506.11763).
- **Mechanism:** 100 expert-created tasks across multiple domains evaluate end-to-end deep-research reports with report- and citation-oriented graders.
- **Preconditions:** use the official task set and evaluation protocol; record judge model/version and inspect disagreement on a StudyHub-relevant sample.
- **Evidence:** the project documents 100 tasks across 22 domains and publishes its evaluation pipeline.
- **Cost:** long Web trajectories and judge calls.
- **StudyHub difference:** the product also needs private-corpus RAG, memory and permission-aware behavior.
- **Decision:** **ADOPT** as the mandatory open-ended external evaluation. DeepResearch Bench II remains **DEFER** until its rubric pipeline is audited and affordable.

## BrowseComp

- **Problem:** ordinary Web questions do not test persistent query reformulation and hard-to-find multi-hop evidence.
- **Primary source:** [OpenAI BrowseComp](https://openai.com/index/browsecomp/), [paper and official dataset reference](https://arxiv.org/abs/2504.12516).
- **Mechanism:** 1,266 difficult, verifiable, short-answer browsing tasks create an asymmetric search-versus-verification challenge.
- **Preconditions:** respect contamination guidance, distinguish full from subset runs and budget Web calls.
- **Evidence:** OpenAI reports that browsing alone is insufficient and that both strategic search and reasoning matter.
- **Cost:** potentially tens or hundreds of fetches per task; short answers do not measure report quality.
- **StudyHub difference:** StudyHub must also cite educational sources and explain results, so BrowseComp cannot be the sole Web benchmark.
- **Decision:** **ADAPT** as a Web stress test; use DeepResearch Bench for long-form quality.

## BrowseComp-Plus, GAIA and xbench-DeepSearch

- **Problem:** one browsing benchmark can conflate retriever quality, Agent policy and memorized/public answers.
- **Primary source:** [BrowseComp-Plus official project](https://github.com/texttron/BrowseComp-Plus), [GAIA benchmark hub](https://huggingface.co/gaia-benchmark), [xbench-DeepSearch official page](https://xbench.org/agi/aisearch).
- **Mechanism:** BrowseComp-Plus separates retriever and Agent effects; GAIA covers broad assistant tasks; xbench focuses on deep search and tool use.
- **Preconditions:** audit licenses, hidden-answer access, contamination, required modalities, official scoring and inference cost.
- **Evidence:** the official project pages describe these distinct scopes; none directly measures StudyHub personalization or ACL.
- **Cost:** additional adapters and potentially live Web/multimodal execution.
- **StudyHub difference:** mandatory BFCL, tau3 and DeepResearch Bench already cover the first external claim set.
- **Decision:** **DEFER** all three until the mandatory stack is operational; choose at most one based on the largest remaining capability gap.

## Anthropic research and Agent eval guidance

- **Problem:** path-dependent research admits multiple valid trajectories and cannot be graded by one gold sequence.
- **Primary source:** [Demystifying evals for AI agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents), [How we built our multi-agent research system](https://www.anthropic.com/engineering/multi-agent-research-system).
- **Mechanism:** combine end-state, groundedness, coverage and source-quality graders; capture complete multi-turn traces and evaluate outcomes relative to task rubrics.
- **Preconditions:** calibrate judges, retain grader disagreement and separate task success from cost.
- **Evidence:** Anthropic describes mixed-grader research evaluation and notes that research quality depends on task-specific coverage and sourcing.
- **Cost:** judge inference and human calibration.
- **StudyHub difference:** the architecture is frozen to one Hermes loop. Multi-agent delegation would change the research question and is not justified by current evidence.
- **Decision:** **ADAPT** the evaluator principles; **REJECT** a new multi-agent architecture in v3.

## Search-R1

- **Problem:** the v2 toy search path does not train query reformulation and multi-turn evidence acquisition in a modern retriever environment.
- **Primary source:** [Search-R1 repository](https://github.com/PeterGriffinJin/Search-R1), [retriever guide](https://github.com/PeterGriffinJin/Search-R1/blob/main/docs/retriever.md).
- **Mechanism:** interleave reasoning and search actions during GRPO; attach sparse BM25, dense E5/FAISS or online search backends.
- **Preconditions:** StudyHub must first freeze a Hybrid RAG snapshot and a path-agnostic outcome evaluator; the model must not see gold evidence.
- **Evidence:** the official repository demonstrates multi-turn search calling with GRPO and documents sparse, dense and online retrieval backends.
- **Cost:** retriever service, indexing and higher rollout latency.
- **StudyHub difference:** Search-R1 commonly grades short QA against a ground truth; StudyHub needs ACL, Memory, claim-level citation and open research rubrics.
- **Decision:** **ADAPT** its interleaved search-training mechanism and retrieval comparisons; do not copy its runtime over Hermes/AReaL.

## WebAgent-R1 and ReTool

- **Problem:** the model must learn when and how to invoke tools across multiple turns rather than imitate a fixed sequence.
- **Primary source:** [WebAgent-R1 official repository](https://github.com/weizhepei/WebAgent-R1), [ReTool ICLR paper](https://proceedings.iclr.cc/paper_files/paper/2026/hash/4038c9208dfc22644c60ad39c24e5c53-Abstract-Conference.html).
- **Mechanism:** WebAgent-R1 performs end-to-end multi-turn RL in WebArena; ReTool interleaves reasoning and code execution with outcome-based RL.
- **Preconditions:** a compatible browser or code environment, objective outcomes and a reason to add those tool families.
- **Evidence:** the primary publications demonstrate learning tool strategy from environment outcomes, not universal transfer to other tools.
- **Cost:** WebArena/Docker or code-sandbox infrastructure and a changed task distribution.
- **StudyHub difference:** v3 first needs text Web, educational RAG and Memory in the existing Hermes loop.
- **Decision:** **DEFER** execution; retain both as mechanism references for later Web or code-tool experiments.

## WebRL, OpenWebRL and WebGym

- **Problem:** hard Web tasks can produce mostly failed rollouts, making a static curriculum inefficient.
- **Primary source:** [WebRL official repository](https://github.com/THUDM/WebRL), [OpenWebRL official repository](https://github.com/OpenWebRL/OpenWebRL), [WebGym/AsyncWebRL repository](https://github.com/microsoft/webgym).
- **Mechanism:** WebRL evolves curriculum from failures; OpenWebRL and WebGym provide visual browser environments and online multi-turn RL; AsyncWebRL builds asynchronous execution on AReaL.
- **Preconditions:** visual-model scope, isolated browser infrastructure, environment licenses, deterministic replay and measured value beyond text search/fetch.
- **Evidence:** official repositories publish the respective curricula and browser-training stacks; OpenWebRL still lists Qwen3.5 RL support as unfinished.
- **Cost:** browser containers, VLM compute, environment maintenance and substantially longer trajectories.
- **StudyHub difference:** current Qwen3.5-9B mainline is text-first and has only two H100s.
- **Decision:** **DEFER** visual-browser training; **ADAPT** failure-driven curriculum and AReaL async profiling only if v3 evidence triggers them.

## Agent-R1

- **Problem:** append-only trajectories obscure per-step state, action, failure and context-management evidence.
- **Primary source:** [Agent-R1 repository](https://github.com/AgentR1/Agent-R1), [Step-level MDP documentation](https://github.com/AgentR1/Agent-R1/blob/main/docs/core-concepts/step-level-mdp.md).
- **Mechanism:** model every interaction as environment state, full model action, transition and reward, retaining step-level observability.
- **Preconditions:** the current AReaL workflow must preserve equivalent per-step prompts, token IDs, log probabilities and observations.
- **Evidence:** official documentation identifies retokenization drift and rigid append-only context as failure modes addressed by step-level records.
- **Cost:** richer artifact volume and more complex context auditing.
- **StudyHub difference:** replacing AReaL would discard a working integration; the useful contribution is an audit model, not a framework migration.
- **Decision:** **ADAPT** step-level evidence and context checks; keep Hermes/AReaL.

## SkyRL-Agent

- **Problem:** long-horizon tools benefit from a clean environment step interface and explicit state transitions.
- **Primary source:** [SkyRL official repository](https://github.com/NovaSky-AI/SkyRL), [official Agent integration guide](https://docs.skyrl.ai/docs/tutorials/agent-integration).
- **Mechanism:** SkyRL-Agent and Gym generators expose task-specific `init/step/close` behavior and support asynchronous, step-wise training.
- **Preconditions:** a measured blocker in the current Hermes/AReaL workflow that cannot be solved without migration.
- **Evidence:** official documentation confirms long-horizon Agent and Gym support, while also noting ongoing repository reorganization.
- **Cost:** a second Agent/training abstraction, migration risk and broken checkpoint lineage.
- **StudyHub difference:** Hermes is deliberately the only Agent loop and AReaL already owns optimization.
- **Decision:** **DEFER** adoption; use its environment-contract ideas only during the v3 environment review.

## OpenResearcher

- **Problem:** 45k SFT trajectories require a credible source of long-horizon Web behavior.
- **Primary source:** [OpenResearcher repository](https://github.com/TIGER-AI-Lab/OpenResearcher).
- **Mechanism:** the project publishes a large collection of long-horizon deep-research trajectories and training/evaluation recipes.
- **Preconditions:** verify exact revision, license, teacher identity, task contamination, source availability, trajectory success, context length and Hermes conversion loss.
- **Evidence:** the official repository advertises 96K long-horizon trajectories; this count is not itself a quality guarantee.
- **Cost:** audit, conversion, token budget and potentially aggressive truncation.
- **StudyHub difference:** generic Web research does not teach StudyHub RAG, Memory, ACL or Chinese learning interactions.
- **Decision:** **DEFER** inclusion until a Dataset Card passes; reserve at most 6k of the proposed 45k final SFT set initially.

## HermesBench

- **Problem:** a Hermes-native external harness could expose parser, recovery, Web and Memory regressions.
- **Primary source:** [third-party HermesBench repository](https://github.com/am423/hermes-bench-tool-call).
- **Mechanism:** real Hermes-harness tasks and trace export.
- **Preconditions:** audit repository provenance, fixtures, hidden answers, data contamination, maintenance quality and compatibility with the pinned Hermes commit.
- **Evidence:** this is not a NousResearch official benchmark, so its name is not sufficient evidence of validity.
- **Cost:** audit and adapter maintenance.
- **StudyHub difference:** task fixtures may not represent StudyHub outcomes or permissions.
- **Decision:** **DEFER**; no claim until the audit is complete.

## DAPO and conditional algorithm changes

- **Problem:** GRPO can waste compute on all-correct/all-failed groups and can suffer length or entropy pathologies.
- **Primary source:** [DAPO official repository](https://github.com/BytedTsinghua-SIA/DAPO).
- **Mechanism:** decoupled clipping, dynamic sampling, token-level policy-gradient loss and overlong reward shaping target stability and useful exploration.
- **Preconditions:** first measure group reward variance, entropy, response length, effective-group rate and overlong truncation on the 9B policy.
- **Evidence:** the official project reports dynamic sampling and length/entropy monitoring as central components; its published result is on math, not Agent tool use.
- **Cost:** additional sampling and changed optimization semantics, which weaken attribution if enabled without a diagnosed problem.
- **StudyHub difference:** trajectories include tools, environment failures and variable horizons; all-zero groups may reflect broken tasks rather than algorithm weakness.
- **Decision:** **DEFER** as the default. **ADAPT** dynamic sampling only after learnability calibration demonstrates material zero-variance waste.

## RLOO, REINFORCE++ and GSPO

- **Problem:** GRPO may fail because of group-normalization waste, unstable token-level ratios or unnecessary critic/reference cost rather than bad data.
- **Primary source:** [AReaL GRPO-series documentation](https://github.com/areal-project/AReaL/blob/main/docs/en/algorithms/grpo_series.md), [REINFORCE++ paper](https://arxiv.org/abs/2501.03262), [GSPO paper](https://arxiv.org/abs/2507.18071).
- **Mechanism:** RLOO uses the other group samples as a leave-one-out baseline; REINFORCE++ applies PPO-like stability techniques without a critic; GSPO clips sequence-level rather than token-level importance ratios.
- **Preconditions:** diagnose the relevant symptom with reward variance, entropy, KL, ratio tails, sequence length and off-policy measurements; confirm support in the pinned AReaL version.
- **Evidence:** AReaL documents RLOO and GSPO configuration, while the primary papers report their intended optimization trade-offs on other task distributions.
- **Cost:** an additional controlled run and changed attribution; algorithms do not repair a bad benchmark or Reward.
- **StudyHub difference:** multi-turn tool trajectories include environment and infrastructure failures that must be classified before estimator comparison.
- **Decision:** **DEFER** by default. Test RLOO/REINFORCE++ for demonstrated group-baseline issues and GSPO for demonstrated sequence-ratio/off-policy instability.

## Dr. GRPO, CISPO and SAPO

- **Problem:** different failures can look like generic "GRPO instability": response-length bias, hard-clipped gradient loss and sequence-level importance-ratio outliers are not the same problem.
- **Primary source:** [Dr. GRPO paper](https://arxiv.org/abs/2503.20783), [MiniMax-M1 CISPO report](https://arxiv.org/abs/2506.13585), [Qwen Soft Adaptive Policy Optimization paper](https://arxiv.org/abs/2511.20347) and [official Qwen note](https://qwen.ai/blog?id=sapo).
- **Mechanism:** Dr. GRPO removes group-standard-deviation and response-dependent length normalizations identified as biased in its analyzed formulation; CISPO clips detached token importance weights rather than zeroing gradients through a PPO min surrogate; SAPO applies smooth, temperature-controlled attenuation with sequence coherence and token adaptivity.
- **Preconditions:** first observe the matching symptom in 9B metrics, reproduce the exact baseline loss in the pinned trainer and register a one-factor comparison. SAPO here means Qwen's **Soft Adaptive Policy Optimization**, not other methods with the same acronym.
- **Evidence:** the papers report their mechanisms on reasoning, MoE or long-context settings. They do not establish a benefit for a 9B dense Hermes Agent with tool and environment failures.
- **Cost:** loss implementation and numerical validation, a same-budget run, and weaker attribution if enabled together with data or Reward changes.
- **StudyHub difference:** long outputs may be legitimate deep research, and ratio outliers may originate from stale serving weights or parser mismatch rather than the policy objective.
- **Decision:** **DEFER / LITERATURE_ONLY**. Dr. GRPO is triggered by incorrect-response length inflation, CISPO by a high useful-token clipping rate, and SAPO by demonstrated hard-gating instability after simpler fixes fail.

## OPD and KDRL

- **Problem:** sparse Agent outcomes may not provide enough signal to retain protocol behavior or transfer capabilities from a stronger compatible teacher.
- **Primary source:** [AReaL distillation documentation](https://github.com/areal-project/AReaL/blob/main/docs/en/algorithms/distillation.md), [Rethinking On-Policy Distillation](https://arxiv.org/abs/2604.13016) and [KDRL paper](https://arxiv.org/abs/2506.02208).
- **Mechanism:** OPD scores tokens from student-generated trajectories with a teacher and minimizes reverse KL on student-visited states; KDRL combines that dense teacher signal with an online RL objective on the same trajectories.
- **Preconditions:** the teacher must expose token log probabilities for the student's actual action tokens, share a compatible policy representation, add information beyond the student and pass a cost/latency qualification. A normal chat completion is not teacher-token scoring.
- **Evidence:** AReaL documents rollout-engine teacher scoring and a joint GRPO plus reverse-KL loss. The OPD study shows that a nominally stronger teacher can still fail when thinking patterns or incremental information do not align.
- **Cost:** an additional inference model, token-level scoring, possible tokenizer alignment and a loss-weight ablation.
- **StudyHub difference:** a teacher may imitate fluent but unsafe or permission-invalid tool behavior; independent end-state and ACL evaluation remains authoritative.
- **Decision:** **DEFER / DIAGNOSTIC_CONDITIONAL** until the GRPO baseline exists and a teacher-qualification report demonstrates compatible, incremental signal. Any KDRL run must report separate RL and distillation losses.

## DPO, KTO, IPO and learned Reward models

- **Problem:** offline preference tuning and learned grading are often described as alternatives to online Agent RL even though they solve different problems.
- **Primary source:** [DPO](https://arxiv.org/abs/2305.18290), [KTO](https://arxiv.org/abs/2402.01306), [IPO theory](https://arxiv.org/abs/2310.12036), [InstructGPT outcome Reward modeling](https://arxiv.org/abs/2203.02155) and [process supervision](https://arxiv.org/abs/2305.20050).
- **Mechanism:** DPO and IPO learn from chosen/rejected pairs; KTO can use unpaired desirable/undesirable labels; outcome Reward models score completed outputs; process Reward models score intermediate steps.
- **Preconditions:** preference provenance, reference-policy identity, contamination control and independent evaluation are required. A process rubric must accept alternative valid Agent paths rather than encode one teacher trajectory.
- **Evidence:** these methods can improve offline preference fit or provide learned Reward signals, but none alone creates interaction with StudyHub RAG, Web, Memory or ACL environments.
- **Cost:** preference or step labels, reference/Reward model inference, calibration and reward-hacking audits.
- **StudyHub difference:** the main research question is autonomous online policy improvement under real Hermes observations.
- **Decision:** **REJECT** DPO/KTO/IPO as the mainline; retain them as optional offline baselines. **ADAPT** outcome or process Reward models only for semantic dimensions that deterministic Reward v3 cannot verify, with separate Dev and Sealed graders.

## Agent Lightning and other Agent RL frameworks

- **Problem:** tracing, rollout storage and algorithm/runner separation can improve reproducibility.
- **Primary source:** [Agent Lightning repository](https://github.com/microsoft/agent-lightning), [architecture guide](https://github.com/microsoft/agent-lightning/blob/main/docs/deep-dive/birds-eye-view.md).
- **Mechanism:** a store decouples algorithms and runners while tracing prompts, responses and rewards.
- **Preconditions:** a migration must solve a measured AReaL blocker and preserve Hermes policy-visible behavior.
- **Evidence:** official docs describe the algorithm/runner/store split and trace-to-training records.
- **Cost:** a second RL stack, duplicate operations and loss of current reproduction lineage.
- **StudyHub difference:** equivalent evidence capture already exists in the v2 AReaL pipeline.
- **Decision:** **DEFER** framework adoption; **ADAPT** only missing observability concepts.

## Research triggers after launch

The review must be revised when any of the following appears: Reward rises while Dev falls; more than the accepted compute budget is spent on zero-variance groups; entropy, KL or ratio tails become abnormal; external and StudyHub scores diverge; a dual-GPU layout is OOM or materially idle; Web/Memory judge disagreement exceeds its calibration bound. Each revision must record the primary source, falsifiable hypothesis, minimum experiment and decision change.

## Benchmark v2 measurement-validity decisions

This section records the correction made after Benchmark v1 passed structural checks but failed a source-level measurement-validity review. Benchmark v1 remains immutable evidence for runtime and Infra behavior. Formal 9B capability conclusions move to v2.

| Source and pinned review revision | Mechanism reviewed | Decision for v2 |
| --- | --- | --- |
| BFCL V4, Gorilla `6ea57973c7a6097fd7c5915698c54c17c5b1b6c8` | Relevant prompts require an appropriate function call; irrelevant prompts test withholding calls without telling the model the policy. | **ADOPT** for direct-answer/tool-relevance scenarios. Remove “do not use tools” hints and expose the same broad tool inventory in both positive and negative cases. |
| tau2/tau3-bench `a2c024725189473d2d7cea3a5cfdbcc67478e41f` | Evaluate equivalent end state rather than equality to one action sequence; reference actions can remain diagnostic. | **ADOPT** for state-changing tasks. **DO NOT COPY BLINDLY**: the upstream evaluation notes that permissive no-op paths can falsely pass, so StudyHub assertions remain fail-closed. |
| OpenAI simple-evals BrowseComp `652c89d0ca9df547706735883097e9537d40dc47` | Hard-to-find but short, objectively verifiable answers separate search effort from answer verification. | **ADAPT** for Web stress and query reformulation. The pinned evaluator snapshot is audited before use; official provenance does not exempt parsing code from local tests. |
| DeepResearchBench II `087c1b8d4a0ed46fd3dd8615a0b5e93ce3acf6f8` | Atomic content-bearing rubrics, explicit evidence and separate information/analysis/presentation dimensions, with evaluator-human calibration. | **ADAPT** for multi-source synthesis. Exact facts, ACL and citations remain deterministic; open entailment and synthesis dimensions require semantic grading and retain disagreement. |

### v2 operational changes

- Rename the internal retrieval claim to **deterministic lexical RAG replay** because the frozen environment is BM25, not Hybrid RAG. A real frozen BM25 + dense + fusion snapshot is a separate retrieval experiment and will not delay the post-training baseline.
- Split direct calculation, insufficient-evidence handling and tool relevance so user text does not reveal the desired policy.
- Require query reformulation to change the normalized query and produce evidence gain; a repeated retry is not recovery.
- Split **permission avoidance** from **post-denial recovery** so avoiding an obvious ACL probe is rewarded rather than penalized.
- Treat `horizon_tier` as intended budget metadata and report `realized_successful_policy_steps` separately. Long-horizon tasks must contain an observation-dependent chain whose minimum successful action count is auditable.
- Rename the internal `deep_research` family to **multi_source_synthesis**. Broad Deep Research claims require external BrowseComp/DeepResearchBench results.
- Report micro success, macro capability success, material-cluster bootstrap intervals and template-cluster bootstrap intervals; generated tasks are not described as IID.
- Publish a metric-coverage matrix that distinguishes “task family present” from “metric operationalized”.
- The v1 rule script is relabeled structural review. v2 records Codex inspection only as `self_review`; it is not human or independent-provider review. The failed Xiaomi 401 contributes no result, and independent review remains `NOT_RUN` until actually performed.
