# StudyHub Agent Router RL Maturity v2 Protocol

状态：**训练前预注册**  
范围：**完全隔离的研究环境；不上线；不访问生产 API、数据库、OSS 写接口或付费资料**

## 为什么需要 v2

v1 只完成了微型 Pilot：每个 seed 训练 16 个 state、48 个 rollout，训练是 state-level contextual bandit，且独立 Test 已经被读取。v1 Test 只允许用于定位历史问题，不允许参与 v2 的训练、选模、阈值调整或最终 Gate。

v1 双账本 blocker 的复核还发现投影器缺陷：

- “先核验详情，再决定是否读正文”被错误投影成 `read_pdf_evidence`。
- “不用搜索”没有被识别为否定搜索。
- 修复后对同一批冻结输出离线重评分，seed 3407 的平均 Raw→Executable Reward gap 由旧规则下的 `-0.0755` 变为 `+0.0829`，SFT 为 `+0.1145`；候选的依赖反而比 SFT 小 `0.0316`。

该复核不能使 v1 Test 重新有效，也不能把 v1 改判为成熟模型。v2 必须重新建集并重新训练。

## 完成定义

完整、机器可读的阈值位于：

`ml/agentic_platform/rl/configs/router_rl_maturity_v2_acceptance.json`

只有同时满足以下条件，才允许把“隔离环境内训练成熟”标记为完成：

1. 新建 Train / Validation / Test / Sealed 四个互斥 split。
2. material、规范化 query、episode template 和 exact prompt 均零跨 split 泄漏。
3. 至少 2,000 个训练 state、500 个训练 episode；Validation、Test、Sealed 各至少 400 state、100 episode。
4. 每个评测 split 的每个关键边界 family 至少 30 条。
5. 真正训练多步 trajectory return 和 credit assignment，不再只训练独立 state。
6. 比较 SFT、DPO 和 trajectory group-relative policy optimization。
7. 比较 LoRA rank 8 / 16 / 32，并对 LR、KL、group size、discount 做消融。
8. 正式配置运行 5 个独立 seed；每 seed 至少 10,000 rollout 和 500 optimizer update。
9. 记录真实 token entropy、更新后的 policy ratio、clip fraction、KL、梯度、长度、吞吐和显存。
10. Contract-gold Judge 至少 400 对，pairwise accuracy ≥ 98%，并通过顺序、长度和序列化偏差测试。
11. Validation 冻结候选后，Test 仅运行一次；Test 通过后 Sealed 仅运行一次。
12. 原始策略关键安全门全部为 100%，不能依赖 Executable 投影掩盖错误。
13. 最终候选 choice success ≥ 95%，episode success ≥ 90%，每个关键 family ≥ 90%。
14. 相对 SFT 的 Reward 配对 bootstrap 95% CI 下界 ≥ 0，且任何 family 不退化。
15. 完成本地离线模型包加载和回滚到 SFT v1.7 的演练；生产配置保持关闭。
16. 最终 HTML 中 26 个 RL 知识点均有直接证据，不能再出现 `PARTIAL`、`PILOT`、`BLOCKER` 或 `NO-GO`。

## 数据与封存纪律

- v1 Test：已消费，仅用于历史诊断。
- v2 Validation：允许用于模型与超参数选择。
- v2 Test：候选、阈值和代码哈希冻结后才可解封。
- v2 Sealed：仅在 Test Gate 通过后解封；失败后不得继续调参并重复使用。
- StudyHub 生产 final holdout：始终不读取。

## 算法边界

v2 的 trajectory group-relative 方法必须按完整 episode 采样多条轨迹，并使用 discounted return / return-to-go 将 terminal 成败传回前序动作。state-level reward 可以作为 shaping，但不能替代轨迹级 credit assignment。

DPO 只作为固定 preference baseline；它不能替代交互式 trajectory RL。所有算法使用同一个冻结 SFT v1.7 起点和同一组 Validation/Test/Sealed Gate。

## 上线边界

本协议不包含真实 shadow traffic、canary 或线上发布。所谓 release 只指本地 research package：可加载、可复现、可回滚。任何生产 provider、动态工具或 runtime constraint 默认开关都必须保持关闭。
