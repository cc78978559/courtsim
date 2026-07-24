# CourtSim Demo v1：阶段 0 领域契约

阶段 0 只冻结领域结构和合法性规则，不包含概率、参数或随机数。它的目标是让后续概率节点只能产生合法篮球事实，并让技术统计从一个结果对象唯一推导。

## 稳定编号

领域枚举使用显式 `IntEnum` 编号。版本内不得改变含义；未来只能在末尾追加，不得插入、重排或复用旧编号。

```text
PlayFamily:    BALL_SCREEN=0, ISOLATION=1, OFF_BALL_ACTION=2
Coverage:      BASE=0, DROP=1, SWITCH=2, BLITZ=3
FinisherRoute: INITIATOR_SELF=0, SCREENER_ROLL=1, SCREENER_POP=2,
               HELP_RELEASE=3, DESIGNED_OFF_BALL_TARGET=4,
               INITIATOR_BAILOUT=5
CreationMode:  SELF_CREATED=0, SCREEN_PARTNER_FEED=1,
               SPOT_UP_FEED=2, OFF_BALL_MOVEMENT_FEED=3
ShotZone:      RIM=0, MIDRANGE=1, THREE=2
TerminalChannel: SHOT_OPPORTUNITY=0, TURNOVER=1
```

`Coverage.BASE` 是以当前 `PlayFamily` 为条件的标准、非特殊防守响应。统计和校准必须解释为 `P(BASE | PlayFamily)`，不能把不同战术下的 `BASE` 当作同一种微观动作。

`Coverage.BLITZ` 在 v1 中表示对当前主要持球人的即时双人强压或夹击。挡拆夹击与单打夹击共享这一高层语义，但实际效果必须由 `PlayFamily × Coverage` 的交互参数决定。

未来扩展的层级固定为：`POST_UP`、`HANDOFF` 是新 `PlayFamily`；`TRANSITION`、`SECOND_CHANCE` 是 `PossessionPhase`；`CUT` 是 `OFF_BALL_ACTION` 下的新路线与创造方式。

## 合法计划与组合

进攻计划是判别联合：

- `BallScreenPlan(handler_id, screener_id)`
- `IsolationPlan(initiator_id)`
- `OffBallActionPlan(passer_id, target_id, screen_setter_id=None)`

计划参与者必须属于进攻阵容。无球计划中的传球者、目标和可选掩护者必须两两不同；没有掩护者时，`OFF_BALL_ACTION × SWITCH` 非法。

合法矩阵由 `plans.py` 集中定义：

- 挡拆：`BASE / DROP / SWITCH / BLITZ`
- 单打：`BASE / BLITZ`
- 无球：`BASE`，有掩护者时额外允许 `SWITCH`
- 每种 Play 的合法路线及每条路线的合法出手区域同样由常量矩阵定义

## 因果顺序

```text
OffensivePlan
→ DefensiveResponse (Coverage)
→ InteractionState
  → FinisherCandidateProfile(route, finisher_id)[]
→ turnover 或 shot opportunity
  → FinisherSelection
  → 派生 CreationMode / last passer / assist eligibility
  → ShotZone
  → ShotContestContext（此时才出现 block candidates）
  → BlockedAttempt 或 LiveAttempt
  → ActionSegmentResult
→ StatAttribution
```

候选机会按 `(route, finisher_id)` 唯一标识。固定终结者路线恰有一个候选；`HELP_RELEASE` 可以有多个弱侧候选，但不能是该计划的持球人、掩护人或发起人。

封盖候选不能出现在 `FinisherCandidateProfile` 中。只有选择出手区域后，才能生成 `ShotContestContext.block_candidate_ids`。`BlockedAttempt` 和 `LiveAttempt` 是互斥的中间结果：前者只能生成封盖投失，后者才能进入未来的命中模型。

`CreationMode`、`last_passer_id` 和助攻资格全部由 `plan + route` 派生，不写入序列化事件。规范结果也不保存单一 `advantage_creator_id`；如需解释多人贡献，应写入非规范的 `DecisionTrace`。

## 唯一事实与记账

`ActionSegmentResult` 是一个判别联合，也是单个行动段唯一的规范事实来源：

- `TurnoverSegmentResult`
- `MadeShotSegmentResult`：不能带篮板
- `MissedShotSegmentResult`：必须且只能带一个篮板
- `BlockedShotSegmentResult`：必须且只能带一个篮板

技术统计只能调用 `attribute_segment(ActionSegmentResult)`。`ContestResolution` 不单独记账，因此一次封盖不会被重复统计。

进攻篮板使 `possession_delta == 0`，后续应在同一回合创建新的 `ActionSegment`；阶段 0 不实现立即补篮。其他终止结果使 `possession_delta == 1`。

## 序列化与校验边界

结果 JSON 使用 `schema_version=1`、稳定数字枚举和显式 `kind` 判别字段。解码器拒绝未知字段、未知枚举和未知 schema 版本；派生字段根本不序列化，因此不会形成重复事实。

对象构造保证联合类型的形状；涉及阵容、战术矩阵和球员身份的规则由 `validate_action_segment_result`、`validate_interaction_state` 与 `validate_shot_contest_context` 在领域边界统一校验。

阶段 0 的测试不使用随机数。合法矩阵、非法身份、候选完整性、封盖时序、四种结果、统计归因和 JSON 往返都必须在进入概率模型前通过。
