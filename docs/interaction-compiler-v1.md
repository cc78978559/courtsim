# 阶段 5：确定性攻防交互编译器

阶段 5 将进攻计划、防守方案、十名球员档案和完整一对一对位编译为阶段 0 冻结的 `InteractionState`。该过程没有随机数，也不直接产生命中率、得分或技术统计。

参数版本升级为：

```text
schema_version:    demo-v1.3
parameter_version: demo-0.4.0
```

## 输入与防守者确定

输入包括 `OffensivePlan`、`Coverage`、双方阵容与档案、`DefensiveMatchups` 和参数。对位必须是完整五对五双射。

- BASE：保留原始一对一对位
- BALL_SCREEN × DROP/BLITZ：掩护者防守人成为主要协防者
- BALL_SCREEN × SWITCH：持球人与掩护者的主防人互换
- OFF_BALL_ACTION × SWITCH：预定目标与掩护者的主防人互换
- 其他帮助者：按防守意识与协防积极性的固定规则确定，平分按球员ID

Coverage 已经由上游给定。防守能力只用于执行该选择，不会替教练重新选择最优防守。

## 交互维度

内部计算：

```text
creator_edge
ball_pressure
pass_release
rim_access
rim_help
```

规范 `InteractionState` 保存全局压力、传球释放，以及每个 `(route, finisher_id)` 的可用性、干扰、篮下通道和防守者身份。其他维度被编译进候选档案，不重复存成第二份事实。

允许读取的原始能力只有：

- 外线持球创造
- 传球创造
- 无球移动
- 掩护质量
- 持球点防守
- 防守意识

护框、投篮、终结、篮板能力和名义标签在此阶段不可见。

## Play × Coverage

每种 Play 的 BASE 都是零向量参考。当前非零组合：

```text
BALL_SCREEN × DROP
BALL_SCREEN × SWITCH
BALL_SCREEN × BLITZ
ISOLATION × BLITZ
OFF_BALL_ACTION × SWITCH
```

没有重新引入早期草案中的 `ISOLATION × SWITCH`。SizeClass 只在换防后生成有利或不利错位偏移，不产生永久成功率加成。

## 候选完整性

- 固定终结路线恰好一个候选
- BALL_SCREEN 的 HELP_RELEASE 排除持球人与掩护者
- ISOLATION 的 HELP_RELEASE 排除发起者
- 每个弱侧球员有独立可用性和防守环境
- OFF_BALL_ACTION 只生成预定目标与发起者兜底
- 结果必须通过 `validate_interaction_state`

当前完整链路：

```text
PlayerProfile + Matchups
→ compile_interaction_state
→ PlayerAwareCompiledPolicy
→ sample_action_segment(RandomFrame)
→ ActionSegmentResult
→ StatAttribution
```

下一阶段应补齐计划、进攻参与者及 Coverage 的选择，使行动段不再要求调用者手工指定战术与防守响应。
