# 末节策略状态机 v1

## 状态契约

`demo-v1.10` 将末节决策分成同时存在的进攻和防守状态：

```text
进攻：STANDARD | COMEBACK | PROTECT_LEAD | TWO_FOR_ONE
防守：STANDARD | INTENTIONAL_FOUL
```

状态解析是确定性的，不消耗随机数。优先级如下：

1. 非第四节始终为 `STANDARD`；
2. 第四节剩余 32～40 秒、分差绝对值不超过 5 时，进攻进入 `TWO_FOR_ONE`；
3. 否则沿用最后 120 秒的追分或保领先状态；
4. 最后 30 秒，防守方落后 3～8 分时标记 `INTENTIONAL_FOUL`。

进攻和防守状态不互斥。例如领先方可能处于 `PROTECT_LEAD`，同时落后方防守处于
`INTENTIONAL_FOUL`。

## 当前执行边界

`TWO_FOR_ONE` 已正式执行：有效节奏增加 15，再复用 12/15/18 秒耗时分布。

`INTENTIONAL_FOUL` 仍是 shadow-only：

- 会计入 `intentional_foul_opportunities`；
- 不生成犯规事件；
- 不增加球队或球员犯规；
- 不产生罚球；
- 不提前结束球权。

只有在故意犯规的犯规人选择、时间消耗、bonus、罚球和球权切换契约全部明确后，
才能将其从 shadow 提升为正式行为。

## 反事实结果

v1.9 shadow 基准与 v1.10 执行版本使用共同种子、每格 300 场。三个种子中：

- 抢二打一窗口球权耗时平均缩短 `0.509` 秒；
- 各种子范围为 `-0.635..-0.353` 秒；
- 故意犯规机会数增量严格为零，证明两版本识别相同情境；
- 全场平均回合增量约 `+0.0006`；
- 每百回合得分增量约 `-0.0007`；
- 命中率逐位不变。

五项方向及隔离门禁在 3/3 个种子上全部通过。证据入口：

- `experiments/matrices/demo-1.2.0-late-game-strategy.json`
- `experiments/contrasts/demo-1.2.0-late-game-strategy-v1.json`
- `work/contrasts/demo-1.2.0-late-game-strategy-robustness.json`
- `experiments/model-audit-demo-1.2.0.json`
