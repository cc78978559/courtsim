# 阶段 1：可读址概率运行时

这一阶段只建立概率执行骨架，不宣称已有真实篮球参数。数值策略通过 `SegmentProbabilityPolicy` 注入；领域结构仍由阶段 0 的校验器控制。

## RandomFrame

每个行动段由以下地址确定一组随机数：

```text
master_seed
scenario_id
replicate_id
game_id
possession_index
segment_index
slot_id
```

`RandomFrame.uniform(slot)` 直接从完整地址派生，不依赖此前消费过多少随机数。因此，一次额外的前场篮板只增加新的 `segment_index`，不会让后续球权的随机序列整体错位。

`RandomSlot` 的 v1 编号采用 append-only 契约：

```text
TERMINAL=0
STEALER=1
FINISHER_ROUTE=2
FINISHER_PLAYER=3
SHOT_ZONE=4
CONTEST=5
SHOT_MAKE=6
REBOUND_SIDE=7
REBOUNDER=8
PLAY_FAMILY=9
PLAN_INITIATOR=10
PLAN_PARTNER=11
OFFBALL_TARGET=12
OFFBALL_SCREEN_SETTER=13
COVERAGE=14
```

改变槽位含义、候选类别集合或 inverse-CDF 排序规则都属于 RNG schema 升级，不能在 v1 中暗改。

## 概率节点

`sample_probability_node` 接受有稳定顺序的 `ProbabilityOption`：

```text
id
value
weight
```

它验证唯一 ID 和非负有限权重，归一化后使用对应槽位的同一个 uniform 进行 inverse-CDF 选择，并返回：

- 选中 ID 与值
- 原始选项
- 归一化概率
- 槽位
- 实际 uniform

这份结果可在后续转换成正式 `DecisionTrace`，但不会写入规范篮球事件。

候选顺序是 schema 的一部分。策略实现必须按枚举编号、阵容槽位和球员 ID 的固定规则生成 tuple，不能遍历 set 或依赖外部 dict 的来源顺序。

## 最小纵向切片

`sample_action_segment` 已贯通：

```text
terminal competing risk
├─ turnover
│  └─ stolen turnover 时选择 stealer
└─ shot opportunity
   ├─ route
   ├─ finisher within route
   ├─ zone
   ├─ contest
   │  ├─ blocked → rebound side → rebounder
   │  └─ live → make
   │             ├─ made
   │             └─ missed → rebound side → rebounder
   └─ ActionSegmentResult validation
```

封盖分支不会访问 `SHOT_MAKE` 槽位。所有路线、终结者、区域、防守者、封盖者和篮板候选在抽样前整组校验；即使非法候选权重为零，也不能藏在候选集中。

当前切片故意不提供生产默认参数。测试中的 `ScriptedPolicy` 只用于强制覆盖所有终止分支。下一步应实现版本化参数契约及编译层，再以有限的节点参数生成这些候选权重。
