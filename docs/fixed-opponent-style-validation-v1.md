# 固定对手球队风格验证 v1

## 结构改动

模型审计和实验矩阵现在可以为被测主队配置独立的 `opponent_profile`。未指定时仍
使用原有的对称自我对战，因此旧矩阵语义不变。manifest 只在两个阵容文件不同时
增加第四个输入及其 SHA-256。

分布审计新增 `team_metrics`，并暴露以下稳定指标路径：

```text
team.home.points_per_100_possessions
team.home.turnover_rate
team.home.assist_per_field_goal
team.home.block_rate
team.home.steal_rate
team.home.shot_zone_share.THREE
```

球队现实目标用 `--audit-team home` 直接绑定被测主队，不再使用双方混合指标。

## 首轮实验

配置：`demo-0.8.0`，200 场/cell，4 worker，共同种子，被测原型均对阵冻结的平衡
阵容。球队风格现实目标覆盖为 `6/12`；覆盖率只用于暴露缺口，不用于自动晋升。

相对同一固定对手的配对差异：

| 原型 | 被测方主要变化 | 对手主要变化 |
| --- | --- | --- |
| 外线产量 | 三分占比 `+0.0676`，百回合得分 `+2.70` | 进攻产量和出手结构基本不变 |
| 压迫防守 | 抢断率 `+0.0457` | 失误率 `+0.0427`，百回合得分 `-7.24` |
| 护框防守 | 盖帽率 `+0.0247` | 百回合得分 `-2.92` |
| 内线中枢 | 助攻/命中 `-0.0004`，接近无变化 | 进攻产量基本不变 |

四组比较共 15 项效应和隔离门禁全部通过。`interior-hub-current-limit` 验证的是
当前近零效应边界，不代表内线中枢已经表达成功。

球队分侧统计加入后，以正式种子重新运行 100 场，`games.jsonl` SHA-256 仍为
`653303286bb78c73b57375571eaac72a10f2d18a7e2cedfcccfc07db381cfedf`，证明只增加了
审计派生字段，没有改变比赛事件。新审计 SHA-256 为
`ca5a4f05eaa3948c23a441a38815aaeaef29ca8e9ccb2050efe7cbf6de0f1c10`，23 项既有
回归门禁继续通过。

## 暴露的结构缺口

当前 `assist_options` 的助攻发生概率只读取终结创造模式；球员 `playmaking` 和
`offensive_decision` 只影响发生助攻后选择哪名助攻者。因此提高内线球员的传球能力
无法提高全队助攻率。下一次结构版本应让潜在传球者特征进入助攻发生节点，并先建立
单因素方向门禁，不能靠调整基础助攻率掩盖。

节奏仍由固定球权秒数决定。主客队独立阵容已经消除了球队风格审计中更紧迫的攻防
耦合，但尚未解决节奏表达。

## 证据

- 矩阵：`experiments/matrices/demo-0.8.0-fixed-opponent-styles.json`
- 对照门禁：`experiments/contrasts/demo-0.8.0-fixed-opponent-styles-v1.json`
- 本地产物：`work/matrices/demo-0.8.0-fixed-opponent-styles-v2/`
- 对照报告：`work/contrasts/demo-0.8.0-fixed-opponent-styles-v1/contrast-report.json`
