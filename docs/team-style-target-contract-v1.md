# 多球队风格目标契约 v1

## 目的

联盟平均目标只能回答“总体分布像不像 NBA”，不能回答同一套属性体系能否表达不同
球队。首个多球队契约使用固定的 NBA.com 2024-25 球队快照，把少量可观察风格轴
绑定到不同阵容原型：

| 阵容原型 | 现实风格参照 | 首批目标轴 |
| --- | --- | --- |
| 外线产量 | Boston Celtics | 节奏、三分占比、三分命中率 |
| 内线中枢 | Denver Nuggets | 助攻/命中、总命中率、三分占比 |
| 压迫防守 | Oklahoma City Thunder | 抢断率、百回合得分、失误率 |
| 护框防守 | Orlando Magic | 节奏、盖帽率、百回合得分 |

这些映射是模型能力探针，不是球队复刻声明。当前审计使用同一阵容的对称自我对战；
真实球队数据则来自完整赛季的不同对手样本，因此只能比较选定的风格轴。

## 契约边界

`targets-build-nba-team` 从固定来源快照生成 active 目标集：

```powershell
.\tools.ps1 targets-build-nba-team `
  experiments/sources/nba-2024-25-team-core.json `
  experiments/nba-2024-25-boston-style-v1.json `
  --team "Boston Celtics" `
  --metric mean_team_possessions `
  --metric shot_zone_share.THREE `
  --metric three_point_percentage
```

每个目标仍包含来源路径、来源哈希、日期、分母一致的指标和显式容差。球队级首版不
使用 `offensive_rebound_rate`：现有快照没有逐队对手防守篮板，不能可靠重建该
分母。

实验矩阵允许 cell 用 `targets` 覆盖矩阵默认目标。不同 cell 可以承担不同球队风格
目标，但这种矩阵禁止使用 `matrix-rank` 横向排名，因为各 cell 的问题不同。应运行：

```powershell
.\tools.ps1 matrix-style-coverage `
  work/matrices/demo-0.8.0-team-style-proxies/matrix-report.json `
  --output work/matrices/demo-0.8.0-team-style-proxies/style-coverage.json
```

覆盖报告会重新验证 cell 输入、manifest、audit、来源目标及评分，然后只报告覆盖率
和缺口；`cross_cell_ranking` 与 `automatic_promotion` 永远为 `false`。

## 首轮证据

配置：`demo-0.8.0`，每个原型 200 场，4 worker，共同种子组。

| 原型 | 目标内指标 | 主要缺口 |
| --- | ---: | --- |
| 外线产量 | 2/3 | 三分占比 `0.4914`，略低于下界 `0.4956` |
| 内线中枢 | 1/3 | 助攻进入区间；三分占比过高，总命中率略低 |
| 压迫防守 | 0/3 | 抢断过高、进攻失误过高、得分略低 |
| 护框防守 | 2/3 | 盖帽率 `0.0789`，高于上界 `0.0746` |

总覆盖为 `5/12`。这不是正式真实性通过率，而是当前属性与节点体系的表达能力快照。

## 结构性发现

两个包含节奏目标的 cell 都得到精确相同的
`mean_team_possessions = 96.0`。原因是当前比赛时钟用固定 15 秒球权推进，节奏不是
球员或球队可表达属性。后续若加入节奏，应该新增显式的球队策略输入和有界球权耗时
分布，并保持每个球权内部有限行动机会；不需要改为连续坐标或逐帧球场模拟。

后续固定对手实验已经支持主客队使用不同阵容，并增加了球队分侧审计。原始对称
自我对战报告保留为历史探针；新的球队风格判断应读取
`fixed-opponent-style-validation-v1.md`。

## 下一步顺序

1. 让潜在传球者能力进入助攻发生节点；
2. 将节奏实现为球队级概率策略，而不是固定时钟常量；
3. 对固定对手反事实门禁运行多种子复验；
4. 通过后才扩大球队数量和目标指标。
