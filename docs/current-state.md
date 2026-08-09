# CourtSim 当前状态

这是给开发者和外部模型使用的低上下文入口。除非任务涉及历史原因或某个节点的
详细公式，否则先读本文件，再按下方路由读取少量相关源码或阶段文档。
跨机器接续使用 `docs/handoff-v0.55.md`；`handoff-v0.52.md` 和
`handoff-v0.54.md` 只保留为历史快照。

## 当前冻结版本

- 引擎候选版本：`0.54.0`
- 模型结构：`data/model_schema_demo_v1_12.json`
- 模型参数：`data/model_parameters_demo_1.4.0.json`
- 球员夹具：`examples/calibration_lineup_v1.json`
- 独立审计基线：`data/baselines/model-audit-demo-1.4.0.json`
- 实验清单：`experiments/model-audit-demo-1.4.0.json`
- 回归门禁：`experiments/model-audit-demo-1.4.0-regression-gates.json`
- 正式发布清单：`governance/current-release.json`
- NBA 核心目标：`experiments/nba-2024-25-regular-season-core-v1.json`
- NBA 罚球目标：`experiments/nba-2024-25-regular-season-free-throws-v1.json`
- 30 队快速模拟：`nba-quick-sim-executor-v6`
- 交易和工资帽完整赛季循环：`nba-franchise-v6`
- 压缩且可迁移的原子存档：`nba-franchise-artifact-v4`
- 带保留策略的多赛季恢复运行器：`nba-franchise-runner-v4`

独立种子 `20260728` 的 100 场审计通过 10 项核心目标、3 项罚球目标和
37 项回归门禁。冻结审计 SHA-256：
`6a13f3b29afff85831d41d7a215902ba73a2e3d43cbccf287818a975c61c4c68`。

## 模型语义

模型不是连续坐标球场，也不是逐帧物理模拟。每个球权由有限个行动片段组成：

```text
选择进攻计划
→ 选择进攻参与者
→ 选择防守 Coverage
→ 编译当前攻防交互
→ 解析非投篮防守犯规及球队 bonus
→ 竞争失误或投篮机会
→ 选择终结路线、终结者和区域
→ 解析封盖、干扰、投篮犯规和命中
→ 必要时解析助攻、罚球和篮板
→ 由事件账本归属统计
```

当前进攻计划处于同一语义层级：

```text
BALL_SCREEN
ISOLATION
OFF_BALL_ACTION
```

球员由 20 项能力和 17 个倾向数值驱动。人工输入使用 `0..100`，运行时按节点
明确映射为中心化特征。不存在综合能力值，也不允许名义位置标签直接改变模拟。

## 核心模块

| 任务 | 首先读取 |
| --- | --- |
| 领域事件和合法性 | `src/courtsim/domain/results.py` |
| 单行动因果顺序 | `src/courtsim/model/segment_sampler.py` |
| 行动计划与防守选择 | `src/courtsim/model/action_setup.py` |
| 攻防交互编译 | `src/courtsim/model/interaction_compiler.py` |
| 球员能力如何进入概率 | `src/courtsim/model/player_aware_policy.py` |
| 球员档案单因素覆盖 | `src/courtsim/player_profile_overlay.py` |
| 参数结构和加载 | `src/courtsim/parameters.py` |
| 球权与比赛循环 | `src/courtsim/model/possession_runtime.py`、`game_runtime.py` |
| 统计归属 | `src/courtsim/stats/attribution.py` |
| 分布审计与现实目标 | `src/courtsim/analysis/` |
| 多阵容、多参数实验矩阵 | `src/courtsim/analysis/experiment_matrix.py` |
| 异构球队风格覆盖审计 | `src/courtsim/analysis/matrix_style_coverage.py` |
| 多种子稳健性审计 | `src/courtsim/analysis/matrix_robustness.py` |
| 配对种子反事实门禁 | `src/courtsim/analysis/matrix_contrast.py` |
| 多种子反事实聚合 | `src/courtsim/analysis/matrix_contrast_robustness.py` |
| 生涯、选秀和休赛期 | `src/courtsim/career.py` |
| 合同和自由市场 | `src/courtsim/management.py` |
| 白盒经理 Shadow 决策 | `src/courtsim/manager_ai.py` |
| 经理反事实证据与发布回滚 | `src/courtsim/manager_evaluation.py` |
| 可续跑经理实验编排 | `src/courtsim/manager_experiment.py` |
| 真实联盟经理实验适配 | `src/courtsim/manager_league_adapter.py` |
| 年度新秀班生成 | `src/courtsim/prospects.py` |
| 白盒经理轮换和上场时间 | `src/courtsim/manager_rotation.py` |
| 命令入口 | `src/courtsim/cli.py`、`tools.ps1` |

详细阶段契约按需读取：

- `domain-demo-v1.md`：枚举、事件和因果边界；
- `model-parameters-demo-v1.md`：结构与数值参数分离；
- `player-profile-v1.md`、`player-aware-model-v1.md`：球员属性与节点映射；
- `player-profile-overlay-v1.md`：可审计覆盖与单因素敏感性；
- `batch-audit-tooling-v1.md`：批量、分片、清单和回归门禁；
- `realism-target-contract-v1.md`：来源、指标和评分契约；
- `experiment-matrix-v1.md`、`matrix-contrast-v1.md`：候选调度、稳健性与差异门禁；
- `team-style-target-contract-v1.md`：多球队目标映射、覆盖审计和首轮表达缺口；
- `fixed-opponent-style-validation-v1.md`：主客队独立阵容、球队分侧指标和隔离门禁；
- `assist-occurrence-v2.md`：潜在传球者如何进入助攻发生概率及 v0.9 冻结；
- `assist-execution-calibration-v1.md`、`foul-free-throw-calibration-v1.md`：
  最近两次结构校准；
- `career-draft-v1.md`：成长、衰退、退休、选秀与休赛期；
- `manager-ai-v1.md`：经理档案、白盒评分、Shadow 选秀和自由市场建议。
- `manager-evidence-v1.md`：多赛季配对证据、晋级门禁和策略回滚。
- `manager-experiment-v1.md`：双臂多赛季编排、续跑和完整性清单。
- `manager-league-adapter-v1.md`：真实赛季、季后赛和休赛期实验适配。
- `prospect-generation-v1.md`：稳定身份、逐项能力/潜力和年度选秀输入。
- `manager-rotation-v1.md`：首发、轮换组、分钟和培养反馈。

## 必须保持的不变量

1. 同一输入、主种子和比赛索引必须生成逐位相同的事件流。
2. worker 数量、任务顺序和分片方式不能改变结果。
3. 新枚举值和随机槽只能追加，不能重排已有编号。
4. 统计必须从正式事件账本重新归属，不能另造结果事实。
5. 结构契约、数值参数、实验覆盖和现实目标必须保持分离。
6. 旧参数和旧事件只通过显式版本兼容读取，不能静默改变语义。
7. 校准先按因果节点分阶段进行，最后只允许有限的端到端残差修正。

## 日常验证

```powershell
.\tools.cmd project-status
.\tools.cmd check-static
.\tools.cmd check-fast
.\tools.cmd check
.\tools.cmd check-franchise
.\tools.ps1 verify work/runs/<run>/manifest.json
.\tools.ps1 audit-check <audit.json> <regression-gates.json>
.\tools.ps1 audit-score <audit.json> <realism-targets.json>
.\tools.ps1 model-benchmark --games 100 --workers 4 --repeats 3
.\tools.ps1 experiment-matrix <spec.json> --output work/matrices/<name>
.\tools.ps1 matrix-rank work/matrices/<name>/matrix-report.json --output <ranking.json>
.\tools.ps1 matrix-style-coverage work/matrices/<name>/matrix-report.json --output <coverage.json>
.\tools.ps1 matrix-robustness work/matrices/<name>/matrix-report.json --output <directory> --replicates 5 --resume
.\tools.ps1 matrix-contrast work/matrices/<name>/matrix-report.json <contrast-spec.json> --output <directory>
.\tools.ps1 matrix-contrast-robustness <robustness-report.json> <contrast-spec.json> --output <report.json>
.\tools.ps1 profile-overlay <base-lineup.json> <overlay.json> <output-lineup.json>
.\tools.ps1 model-audit --profile <tested.json> --opponent-profile <baseline.json> ...
```

`project-status` 是面向代理和跨机器接续的单行 JSON 入口；它验证冻结治理哈希并
报告版本、Git 状态和可用能力。`check-fast` 排除显式标记的慢速完整 NBA/franchise
路径；`check` 包含全部测试和 85% 覆盖率门槛。Windows 优先使用 `tools.cmd`，
它不会修改系统 PowerShell 执行策略；下方历史命令仍可经 `tools.ps1` 调用。
大型校准运行不进入默认门禁，参数或概率结构改变后必须手动生成独立种子审计。
版本轴、人工晋级和回退规则见 `docs/versioning-and-promotion-v1.md`。

只需要分布指标时可以使用：

```powershell
.\tools.ps1 model-audit --trace-mode aggregate-only ...
```

该模式不写 `games.jsonl`，不能回放或进行磁盘分片合并。正式冻结仍使用默认
`full`，以保留完整事件证据。

## 当前性能

2026-07-24 本机基准，标准 48 分钟比赛：

- 单进程、纯内存：约 `5.69 games/s`；
- 4 进程、完整审计产物：约 `19.58 games/s`；
- 单进程、`aggregate-only`：约 `8.93 games/s`；
- v0.9 结构下，4 进程、`aggregate-only` 三次基准中位数：约
  `25.24 games/s`；
- v1.0 结构下，4 进程、`aggregate-only` 三次基准中位数：约
  `26.01 games/s`；
- v1.1 结构下，加入末节情境审计后的三次基准中位数：约
  `24.61 games/s`；
- v1.2 状态机与 shadow 审计下，三次基准中位数：约
  `23.47 games/s`；
- v1.0 中性节奏的 100 场审计共有 19,333 个球队球权。

动态角色按照不可变五人阵容进行有界缓存。不得为了速度改变语义随机地址或跳过
事件合法性；`aggregate-only` 只能省略中间 Trace 与落盘事件，不能改变正式事件
解析和统计归属。

## 当前边界

当前仍未闭环的主要边界包括：把只读 draft obligation/freeze ledger v3 接入规范交易
生成、执行与结算；把已经实现的 three-team-market v2 合同谈判树晋级并接入每赛季
franchise；从战术可观测性推进到配对种子的因果战术实验；Shadow 之外的人工批准流程；
以及完整玩法 UI。

已经实现的联盟层包括 30 队 1,230 场赛程、play-in、完整季后赛、疲劳和伤病连续、
乐透与选秀权结算、球探不确定性、球员成长/衰退/退休、完整休赛期、鸟权/工资匹配/
交易特例、完整七年 Stepien、条件选秀权、四至八轮双边谈判、draft obligation/freeze
ledger v3 只读审计、three-team-market v2 合同谈判树、白盒经理交易与轮换、
对手级战术、跨赛季经理学习、2K 快速模拟比较入口、压缩/保留/迁移的原子 franchise
存档，以及不重放已完成赛季的多赛季恢复运行器。最新进度和测试数
以 `PROJECT_STATUS.md` 与 `governance/current-release.json` 为准。

固定对手和球队分侧审计已落地；球队级 `tempo` 已通过 12/15/18 秒有界分布改变
回合数。v1.9 进一步在末节最后 120 秒按 6 分分差调整节奏：三个种子上落后球权
平均缩短约 0.558 秒，领先球权延长约 0.488 秒，中性情境与全场效率保持隔离。
v1.10 已把末节判断提升为显式攻防状态机；v1.11 正式执行 bonus 故意犯规，
v1.12 进一步执行非 bonus 犯规并在进攻方保有球权时续接正常进攻阶段。
实验矩阵的单种子结果必须再经过多种子稳健性审计；不要在单一平衡阵容
通过总体指标后直接宣称球员分布或对位已经拟真。

`demo-v1.6` 已启用非投篮犯规概率节点、相关防守人 hazard、按节球队犯规累计和
第五次犯规起的 bonus。单因素反事实已经确认 `foul_drawing` 与
`foul_discipline` 的方向在三个种子上稳定；四套合成风格阵容的 16 项组合方向与
串扰门禁也全部通过。但这些结果尚未证明真实球员之间的效应量拟真。具体契约见
`non-shooting-foul-bonus-v1.md`、`common-foul-calibration-v1.md`、
`foul-single-factor-validation-v1.md` 与 `synthetic-style-validation-v1.md`。
多球队目标与首轮缺口见 `team-style-target-contract-v1.md`。
固定对手证据见 `fixed-opponent-style-validation-v1.md`。

## 给外部模型的输入建议

普通技术问题只提供：

1. 本文件；
2. 与问题对应的 1～3 个核心源码文件；
3. 当前参数文件中相关节点，而不是整份 JSON；
4. `audit.json` 或目标集，不提供大型 `games.jsonl`。

只有排查单场因果链时才附对应的少量事件和 Decision Trace。`work/` 是本地产物，
默认不应进入版本控制或通用上下文。
