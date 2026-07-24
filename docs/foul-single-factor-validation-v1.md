# 犯规属性单因素验证 v1

## 目的

总体犯规率正确并不能证明球员属性真正进入了对应因果节点。本实验在冻结的
`demo-0.8.0` 上只改变一个球员数值叶子，并用共同随机数检查方向：

- `player 1 foul_drawing: 60 -> 20`
- `player 1 foul_discipline: 65 -> 95`

校准阵容会被映射到主客双方，因此主队 player 1 与客队 player 11 是同一个阵容
槽位的镜像。所有覆盖均由 `profile-overlay` 生成并带哈希清单。

## 事件溯源指标

分布审计新增 `player_foul_shares`。每项只从正式
`NonShootingFoulSegmentResult` 和 `ShootingFoulSegmentResult` 的
`fouler_id` 汇总，分母是该防守球队的全部防守犯规。它不参与模拟决策。

每项同时提供 `fouls_per_100_defensive_possessions`。份额用于检查犯规人在队内的
分配；绝对率用于多名防守者同时变化时，避免“总量下降但相对份额上升”的误读。

可用于门禁的指标形如：

```text
player_foul_share.home.1
player_foul_share.away.11
player_fouls_per_100_defensive_possessions.home.1
```

旧审计没有该字段时仍可读取；只有新生成的审计公开球员犯规份额。新旧审计做
`audit-diff` 时，缺失的动态球员犯规项按未观测的零基线展示，其余静态指标仍要求
集合严格一致。

## 共同种子结果

矩阵 `demo-0.8.0-single-factor-fouls.json` 每个 cell 运行 200 场。首次配对结果：

```text
foul_drawing 低值：
  non_shooting_foul_rate delta   -0.0194
  shooting_foul_rate delta       -0.0273
  defensive_foul_rate delta      -0.0467
  FTA/FGA delta                  -0.0647

foul_discipline 高值：
  non_shooting_foul_rate delta   -0.0092
  shooting_foul_rate delta       -0.0107
  home player 1 foul share       -0.0831
  away player 11 foul share      -0.0811
```

方向门禁使用比首次观测更宽的范围，而不是冻结具体 delta。

## 多种子结果

三个共同种子共运行 9 个 cell 复现。两项 comparison、八项方向门禁全部达到
`3/3`：

- 低造犯规能力始终降低普通犯规、投篮犯规、总防守犯规和罚球出手率；
- 高防守纪律始终降低普通犯规、投篮犯规以及该阵容槽位自身的犯规份额。

该实验验证的是属性传导方向和犯规人归属，不证明当前系数幅度与真实 NBA 球员差异
一致。下一步需要引入多套差异阵容或外部球员级目标，才能讨论效应量校准。
