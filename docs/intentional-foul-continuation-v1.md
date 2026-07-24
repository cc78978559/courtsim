# 非 bonus 故意犯规续接 v1

`demo-v1.12 / demo-1.4.0` 在 `demo-v1.11` 的 bonus-only 正式执行之上，
补齐非 bonus 故意犯规和末罚进攻篮板后的进攻续接。

## 时间与事件语义

```text
故意犯规阶段：3 秒
├─ bonus 且球权结束 → 本球权总耗时 3 秒
└─ 进攻方保有球权
   ├─ 非 bonus，界外球续接
   └─ 末罚不中且进攻篮板
      → 再执行一个正常进攻阶段：12 / 15 / 18 秒
```

因此非截断球权的合法总耗时新增 `15 / 18 / 21` 秒。比赛时间不足时仍按周期末
截断到零，这是原有比赛时钟契约。

犯规和续接属于同一个篮球球权、两个 action segment：

1. 第一段固定为 `NonShootingFoulSegmentResult`；
2. 非 bonus 第一段不产生罚球，记一次防守犯规并保留进攻球权；
3. 第二段使用新的 segment 地址，按正常进攻计划和概率节点采样；
4. bonus 末罚进攻篮板同样进入第二段；
5. 全部得分、犯规、投篮和篮板仍由正式事件账本归属。

## 版本隔离

- `demo-v1.10`：故意犯规仅 shadow；
- `demo-v1.11`：仅本次犯规触发 bonus 时正式执行；
- `demo-v1.12`：全部状态机会正式执行，保有球权时增加续接阶段。

参数 `intentional_foul_non_bonus_enabled` 在 v1.12 必须显式为 `true`。
旧版本不会静默改变行为。

## 审计字段

- `intentional_foul_opportunities`
- `intentional_fouls_committed`
- `intentional_foul_continuations`
- `intentional_foul_mean_observed_seconds`

三种子、每种子 100 场的初步结果：

| 种子 | 机会 | 执行 | 续接 | 平均总耗时 |
| --- | ---: | ---: | ---: | ---: |
| 20260728 | 34 | 34 | 10 | 5.735 秒 |
| 20260729 | 33 | 33 | 9 | 6.000 秒 |
| 20260730 | 25 | 25 | 7 | 5.640 秒 |

三组均满足“机会数等于执行数”。相对 bonus-only v1.11，新增正式执行
`9 / 7 / 6` 次；防守犯规率方向一致上升，罚球率近似不变，符合非 bonus
犯规不产生罚球的因果隔离要求。

证据位于：

- `work/audits/demo-1.4.0-seed-*`
- `work/benchmarks/demo-1.4.0-non-bonus-intentional-foul/benchmark.json`
- `work/benchmarks/demo-1.3.0-control-rerun/benchmark.json`

当前环境下性能中位数为 `21.03 games/s`，同轮 v1.11 对照为
`20.62 games/s`；两者均通过 `20 games/s` 门槛，未观察到运行速度回归。

## 可复现迁移

```powershell
.\tools.ps1 parameters-enable-non-bonus-intentional-foul `
  data/model_schema_demo_v1_12.json `
  data/model_parameters_demo_1.3.0.json `
  experiments/calibration/intentional-foul-non-bonus-v1.json `
  work/model_parameters_demo_1.4.0.json
```

固定语义哈希：

```text
parameter 3d935b77ec1239127aef824fc06f8a84cb11cb4c7ac8de30a997a37d32809950
schema    e32e210bfe6c672d2f214759603420d475342876491f400753452c9262950374
```

这仍是结构验证版本，尚未根据真实比赛逐回合数据校准故意犯规时机、犯规耗时
或续接进攻节奏。
