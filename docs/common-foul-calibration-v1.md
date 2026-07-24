# 非投篮犯规与 Bonus 校准 v1

## 结论

`demo-v1.6` / `demo-0.8.0` 正式启用非投篮防守犯规和按节球队 bonus。冻结节点在
每个行动段的 terminal 竞争之前运行，避免把普通犯规伪装成失误或投篮结果。

正式参数由两步可重建：

```powershell
.\tools.ps1 parameters-add-common-fouls `
  data/model_schema_demo_v1_6.json `
  data/model_parameters_demo_0.7.0.json `
  experiments/calibration/common-foul-node-v1.json `
  work/candidates/common-foul-initial.json

.\tools.ps1 parameters-overlay `
  data/model_schema_demo_v1_6.json `
  work/candidates/common-foul-initial.json `
  experiments/calibration/common-foul-final-v1.json `
  work/candidates/demo-0.8.0.json
```

## 参数边界

基础普通犯规概率分别为：

- `BALL_SCREEN = 0.055`
- `ISOLATION = 0.050`
- `OFF_BALL_ACTION = 0.040`

球队每节第五次防守犯规起进入 bonus。最后两分钟 penalty、进攻犯规、技术犯规、
恶意犯规和六犯离场均不在本阶段范围。

初始节点在固定 100 场样本中把 FTA/FGA 从原冻结版约 `0.250` 推高至 `0.286`。
因此不能只增加普通犯规而保留原投篮犯规量。最终覆盖把三类投篮犯规基础率统一
降低 12%，保留普通犯规节点本身不变。

## 候选矩阵

正式矩阵：

```text
experiments/matrices/demo-0.8.0-common-foul-balance.json
```

矩阵包含初始节点、两档投篮犯规削减候选和一档低普通犯规候选；每个 cell 使用
200 场、共同 `seed_group`。`balance-a` 是唯一同时通过 NBA 核心与罚球目标的候选：

```text
FTA/FGA                         0.2446
non_shooting_foul_rate          0.0564
bonus_non_shooting_foul_rate    0.0136
shooting_foul_rate              0.1257
defensive_foul_rate             0.1820
```

三种子稳健性审计共执行 12 个复现。`balance-a` 通过率为 `1.0`、最坏必需指标失败数
为 `0`；其余候选均未达到同一资格。排名与稳健性工具均明确
`automatic_promotion=false`，最终冻结是人工确认后的独立步骤。

## 独立冻结审计

正式独立审计使用主种子 `20260728`、100 场完整事件流：

```text
completed_possessions           19200
FTA/FGA                         0.2499716714
non_shooting_foul_rate          0.0591145833
bonus_non_shooting_foul_rate    0.0142187500
shooting_foul_rate              0.1260416667
defensive_foul_rate             0.1851562500
points_per_100_possessions      116.7135416667
```

10 项 NBA 核心目标和 3 项罚球目标全部通过。冻结 audit SHA-256：

```text
b50441a2a25b25d496868f9c81399abb1706d259eaf56c964de0b7d4093e5db0
```

哈希变化只来自后续增加的球员犯规份额与每百防守回合个人犯规审计字段；同一正式
运行的 `games.jsonl` SHA-256 仍为
`653303286bb78c73b57375571eaac72a10f2d18a7e2cedfcccfc07db381cfedf`，
比赛事件流没有改变。

这些结果只证明平衡校准阵容的总体分布达到当前门禁，不证明不同真实球员、对位或
裁判环境下的犯规差异已经拟真。
