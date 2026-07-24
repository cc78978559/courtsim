# 投篮犯规与罚球校准 v1

`demo-0.7.0` 增加投篮犯规、犯规者、逐次罚球和末次罚球篮板，补齐此前唯一明确缺失的
得分来源。该版本不模拟非投篮犯规、加罚规则以外的 bonus 状态、恶意犯规或技术犯规。

## 因果顺序

```text
投篮机会
→ 防守干扰（盖帽则走原盖帽分支）
→ 是否发生投篮犯规
→ 犯规者
→ 运动战是否命中
→ 命中时解析助攻
→ 1 / 2 / 3 次逐罚结果
→ 末次罚球不中时解析篮板
```

规则契约：

- 运动战命中并被犯规：进球有效，追加 1 次罚球。
- 两分投篮犯规且未命中：2 次罚球，不记 FGA。
- 三分投篮犯规且未命中：3 次罚球，不记 FGA。
- 只有末次罚球不中才产生篮板。
- 末次罚球的进攻篮板继续原回合；其他罚球序列终止回合。
- 犯规者必须属于防守阵容，助攻者仍必须属于进攻阵容且不能是终结者。

统计账本新增 `FTM`、`FTA`、`PF`，并保持全部得分可由事件重新归因。

## 结构与兼容

参数结构升级到 `demo-v1.5`，增加：

- `shooting_foul`
- `free_throw_make`

此前休眠的 `free_throw_shooting`、`foul_drawing`、`foul_discipline` 和
`contact_seek` 正式激活。旧 `demo-v1.3`、`demo-v1.4` 参数仍可加载，并在缺少新节点时
确定性返回“无投篮犯规”。

事件序列化升级到 v3：

- 继续读取 v1、v2 投篮事件；
- v3 显式保存犯规者、运动战结果、每次罚球、末次罚球篮板和助攻者；
- 随机槽只在既有槽 0～16 后追加 17～21。

结构迁移：

```powershell
.\tools.ps1 parameters-add-fouls `
  data/model_schema_demo_v1_5.json `
  data/model_parameters_demo_0.6.0.json `
  experiments/calibration/foul-free-throw-node-v1.json `
  work/candidates/foul-initial.json
```

## 官方罚球目标

NBA.com 2024-25 常规赛 30 队传统统计总计的补充投影冻结在：

```text
experiments/sources/nba-2024-25-team-free-throws.json
```

官方总计：

```text
FTM = 41,574
FTA = 53,312
FGA = 219,527
POSS = 246,289
```

派生目标：

| 指标 | 目标 | ±5% 校准区间 |
| --- | ---: | ---: |
| FT% | 77.9824% | 74.0833%～81.8816% |
| FTA/FGA | 0.24285 | 0.23071～0.25499 |
| FGA/100 | 89.1339 | 84.6772～93.5906 |

罚球目标与原 10 项核心目标保持为两个独立 active target set，防止修改旧来源快照和哈希。

## 分阶段校准

1. `foul-free-throw-node-v1`：增加结构与初始参数。
2. `foul-volume-v1`：只校准 FTA/FGA 与 FT%。
3. `execution-center-v2`：在正确 FGA 记账语义下重新居中运动战命中和盖帽风险。

第一组初始参数只有 `FTA/FGA=0.1312`；提高犯规产量后，训练样本达到
`FTA/FGA=0.2489`、`FT%=77.51%`。随后重新校准运动战执行，而不是把罚球得分直接叠加到
旧运动战模型。

## 独立复验

独立种子 `20260728`、100 场、19,200 个球队回合：

| 指标 | demo-0.7.0 | 状态 |
| --- | ---: | --- |
| 每百回合得分 | 117.99 | 核心区间内 |
| 总命中率 | 46.47% | 核心区间内 |
| 三分命中率 | 36.02% | 核心区间内 |
| 三分出手份额 | 42.35% | 核心区间内 |
| 助攻/命中 | 64.58% | 核心区间内 |
| 盖帽率 | 5.54% | 核心区间内 |
| 失误率 | 14.44% | 核心区间内 |
| 抢断率 | 8.33% | 核心区间内 |
| 进攻篮板率 | 25.86% | 核心区间内 |
| FGA/100 | 92.30 | 罚球区间内 |
| FTA/FGA | 0.2500 | 罚球区间内 |
| FT% | 78.60% | 罚球区间内 |

两个现实性门共 **13/13** 通过。这里的区间是首轮 ±5% 校准包络，不是抽样置信区间；
通过意味着模型具备可继续细化的总体统计结构，不表示所有比赛形态或球员分布已经拟真。

## 冻结产物

```text
data/model_schema_demo_v1_5.json
data/model_parameters_demo_0.7.0.json
data/baselines/model-audit-demo-0.7.0.json
experiments/model-audit-demo-0.7.0.json
experiments/model-audit-demo-0.7.0-regression-gates.json
experiments/nba-2024-25-regular-season-free-throws-v1.json
```
