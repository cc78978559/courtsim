# NBA 2024-25 核心真实性目标 v1

首个可执行真实性目标集使用 NBA 2024-25 常规赛全部 30 队、2,460 个球队场次。
它独立于 `model-audit-demo-0.4.0` 回归基线：前者衡量像不像目标联赛，后者只检测代码或参数是否漂移。

## 固定来源

本地来源快照：

```text
experiments/sources/nba-2024-25-team-core.json
```

快照来自 NBA.com 的球队 Traditional 和 Advanced 表。仅投影计算所需列，但保留全部
30 队以及页面显示的原始数字字符串。目标文件加载时会重新核对快照 SHA-256。

固定筛选：

```text
Season=2024-25
SeasonType=Regular Season
PerMode=Totals
```

`PACE` 使用 Advanced 表的官方 48 分钟标准化字段。其余指标从球队赛季总计重新计算，
并刻意采用 `DistributionAudit` 的事件分母：

| 审计指标 | 来源计算 |
| --- | --- |
| `mean_team_possessions` | `sum(PACE * GP) / sum(GP)` |
| `points_per_100_possessions` | `100 * sum(PTS) / sum(POSS)` |
| `field_goal_percentage` | `sum(FGM) / sum(FGA)` |
| `three_point_percentage` | `sum(3PM) / sum(3PA)` |
| `shot_zone_share.THREE` | `sum(3PA) / sum(FGA)` |
| `turnover_rate` | `sum(TOV) / sum(POSS)` |
| `offensive_rebound_rate` | `sum(OREB) / (sum(OREB) + sum(DREB))` |
| `assist_per_field_goal` | `sum(AST) / sum(FGM)` |
| `block_rate` | `sum(BLK) / sum(FGA)` |
| `steal_rate` | `sum(STL) / sum(POSS)` |

当前上下界统一取目标值的相对 `±5%`。这是第一轮校准的工程验收带，不是置信区间，
也不表示真实 NBA 只会在该区间内波动。

## 本地重建

```powershell
.\tools.ps1 targets-build-nba `
  experiments/sources/nba-2024-25-team-core.json `
  experiments/nba-2024-25-regular-season-core-v1.json
```

构建器会拒绝：

- 不是 30 队的快照；
- 任一球队不是 82 场；
- Traditional 与 Advanced 球队集合不一致；
- 重复球队、负数、非有限数或零分母；
- 无法由目标文件目录内的可移植路径引用的来源。

## 首次评分

```powershell
.\tools.ps1 audit-score `
  data/baselines/model-audit-demo-0.4.0.json `
  experiments/nba-2024-25-regular-season-core-v1.json `
  --output work/runs/nba-2024-25-core-score-demo-0.4.0.json
```

当前 50 场冻结基线在 10 项中有 8 项越界，因此命令以退出码 `6` 明确失败。
最大偏差依次包括三分出手份额过高、盖帽率过低、进攻篮板率过低、抢断率过低和失误率过低。
这份结果是校准待办，不应通过修改目标范围来消除。

篮下与中距离出手份额仍只保留在 draft 计划中；在取得能与模拟区域枚举可靠映射的
NBA 投篮区域来源前，不进入 active 核心目标。
