# 合成风格阵容验证 v1

## 范围

本阶段验证多属性组合能否形成可区分的球队风格，不把合成夹具声明为真实球队。四套
阵容都由 `calibration_lineup_v1.json` 的严格 profile overlay 派生：

- `foul-pressure-core`：核心持球人提高造犯规与主动对抗；
- `disciplined-defense`：主要外线、锋线和护框者提高犯规纪律；
- `rim-wall`：两名内线提高护框与追帽；
- `five-out`：两名内线提高三分能力与三分区域倾向。

每份覆盖只包含解释该风格所需的数值叶子，并由物化清单记录输入、规范和输出哈希。

## 指标语义

球队组合不能只读 `player_foul_share`。当多名球员同时减少犯规时，队内相对份额可能
上升。因此审计同时公开：

```text
player_foul_share.<team>.<player>
player_fouls_per_100_defensive_possessions.<team>.<player>
```

前者回答“队内犯规由谁承担”，后者回答“该球员的绝对犯规频率是多少”。

## 首次共同种子结果

每个 cell 运行 200 场：

```text
造犯规核心：
  non-shooting foul delta     +0.0331
  shooting foul delta         +0.0452
  total defensive foul delta  +0.0782

纪律防线：
  non-shooting foul delta     -0.0210
  shooting foul delta         -0.0344
  home player 1 PF/100 def    -1.7344
  home player 5 PF/100 def    -3.6406

护框阵容：
  block rate delta            +0.0236
  non-shooting foul delta     +0.0003
  three-point share delta     -0.0007

五外阵容：
  three-point share delta     +0.0705
  three-point percentage      +0.0061
  non-shooting foul delta      0.0000
```

护框和五外的非目标指标门禁用于发现明显串扰，而不是要求所有次级指标逐位相等。

## 多种子结论

三种子稳健性共执行 15 个 cell。四项 comparison、16 项方向与串扰门禁全部
`3/3` 通过：

- 造犯规核心稳定增加两类犯规；
- 纪律防线稳定降低总量和关键球员绝对犯规率；
- 护框阵容稳定提高盖帽，同时基本不改变普通犯规和出手区域；
- 五外阵容稳定提高三分出手份额，同时基本不改变普通犯规。

上游现实目标稳健排名没有候选获得自动晋升资格。这是合理结果：极端风格夹具用于
反事实敏感性验证，不应被当作联盟平均参数。正式报告仍固定
`automatic_promotion=false`。

## 尚未证明

这些实验没有使用真实球队或真实球员级目标，因此只证明模型可以产生稳定、可解释的
风格差异。下一步需要准备来源明确的多球队目标或至少多套独立校准阵容，才能评估
效应量是否接近真实篮球。
