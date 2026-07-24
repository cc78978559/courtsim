# Action Setup v1

阶段 6 将一个行动片段的前置决策实现为可追溯的条件概率链，而不是球场坐标模拟：

```text
球队策略
  -> 计划家族
  -> 发起者
  -> 条件参与者
  -> 合法 Coverage
  -> InteractionState
  -> ActionSegmentResult
```

## 选择契约

- 计划家族基准：`BALL_SCREEN=0.45`、`ISOLATION=0.25`、`OFF_BALL_ACTION=0.30`。
- 发起者来自持球角色自然份额；掩护者来自掩护角色份额；无球目标来自空间角色份额。
- 参与权重同时读取 `offensive_involvement` 和对应的 `play_role_mix` 相对偏好。
- 无球战术有独立的“无掩护”分支。无掩护时 Coverage 资格掩码只保留 `BASE`。
- 防守 Coverage 先按计划取得条件基准，再由护框角色份额加权的 `help_aggression` 和球队策略调整 logit。
- 球队策略只提供有限的 `[-2, 2]` logit 偏置，不能绕过参与者和 Coverage 资格掩码。

所有候选按枚举编号或球员 ID 排序。每个节点返回完整选项、归一化概率、随机数和最终选择。

## RNG 地址

RNG schema v1 以 append-only 方式增加：

```text
PLAY_FAMILY=9
PLAN_INITIATOR=10
PLAN_PARTNER=11
OFFBALL_TARGET=12
OFFBALL_SCREEN_SETTER=13
COVERAGE=14
```

分支跳过某个节点不会改变其他节点的随机数。

## 高层入口

`sample_action_setup()` 只生成计划、Coverage、动态角色和设置阶段 trace。

`sample_prepared_action_segment()` 串联：

```text
sample_action_setup
compile_interaction_state
PlayerAwareCompiledPolicy
sample_action_segment
```

调用方仍需显式提供五组一对一基础对位。自动换防和协防人选择由 Interaction Compiler 根据 Coverage 处理。

## 参数版本

```text
schema_version:    demo-v1.3
parameter_version: demo-0.4.0
schema_hash:       8fc2f9243e7f83711549ad67cc51435b8d078524d7221a0ec41e2d8f3c675ff0
parameter_hash:    c3592432913e940005ff69449c31e2e30a23355f1986e1d5a18a214daff22d38
```

这些数值仍是未校准先验，只用于冻结因果结构和验证工具链。
