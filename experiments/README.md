# 实验配置

这里保存可版本控制的实验定义和基准说明。具体运行产物写入 `work/experiments/`，并由运行清单记录配置哈希、引擎版本和种子。

真实性目标分为两类：

- `realism-targets-template-v1.json`：尚未可靠映射的完整 draft 计划；
- `nba-2024-25-regular-season-core-v1.json`：已固定来源并可执行的 active 核心目标。

NBA 核心目标的来源快照、分母映射和重建命令见
[`docs/nba-reference-targets-v1.md`](../docs/nba-reference-targets-v1.md)。

`calibration/` 保存只包含数值叶子变更的候选覆盖文件。区域扫描、事件率校准、
独立种子复验与 `demo-0.5.0` 冻结过程见
[`docs/structure-calibration-v1.md`](../docs/structure-calibration-v1.md)。

助攻节点迁移、投篮执行候选扫描与 `demo-0.6.0` 冻结过程见
[`docs/assist-execution-calibration-v1.md`](../docs/assist-execution-calibration-v1.md)。

投篮犯规/罚球节点、官方罚球目标与 `demo-0.7.0` 冻结过程见
[`docs/foul-free-throw-calibration-v1.md`](../docs/foul-free-throw-calibration-v1.md)。

非投篮防守犯规、球队 bonus、联合罚球量校准与 `demo-0.8.0` 冻结过程见
[`docs/common-foul-calibration-v1.md`](../docs/common-foul-calibration-v1.md)。

潜在传球者进入助攻发生概率、内线中枢响应和 `demo-0.9.0` 冻结过程见
[`docs/assist-occurrence-v2.md`](../docs/assist-occurrence-v2.md)。

球队级节奏、球权耗时分布和 `demo-1.0.0` 冻结过程见
[`docs/team-tempo-v1.md`](../docs/team-tempo-v1.md)。

末节比分情境节奏、确定性策略表和 `demo-1.1.0` 冻结过程见
[`docs/late-game-tempo-v1.md`](../docs/late-game-tempo-v1.md)。

末节攻防状态机、抢二打一执行和故意犯规 shadow 审计见
[`docs/late-game-strategy-v1.md`](../docs/late-game-strategy-v1.md)。

造犯规能力与防守纪律的单因素、多种子方向验证见
[`docs/foul-single-factor-validation-v1.md`](../docs/foul-single-factor-validation-v1.md)。

四套合成风格阵容的组合方向、串扰和多种子验证见
[`docs/synthetic-style-validation-v1.md`](../docs/synthetic-style-validation-v1.md)。

四个球队风格参照、cell 级目标覆盖和首轮表达缺口见
[`docs/team-style-target-contract-v1.md`](../docs/team-style-target-contract-v1.md)。

固定基准对手、球队分侧现实目标和攻防隔离验证见
[`docs/fixed-opponent-style-validation-v1.md`](../docs/fixed-opponent-style-validation-v1.md)。

`matrices/` 保存多 cell 调度规范；`contrasts/` 保存必须使用共同 `seed_group` 的
反事实方向门禁。首个阵容差异契约见
`contrasts/demo-0.7.0-profile-contrast-v1.json`，详细规则见
[`docs/matrix-contrast-v1.md`](../docs/matrix-contrast-v1.md)。

矩阵 cell 可以用自己的 `targets` 覆盖默认目标。目标集不同的矩阵只能运行
`matrix-style-coverage`，不能使用 `matrix-rank` 横向排名。

`profile-overlays/` 保存只修改既有球员评分叶子的单因素覆盖规范。派生阵容写入
`work/profiles/`，不进入版本控制；覆盖契约和首个三分倾向/能力隔离实验见
[`docs/player-profile-overlay-v1.md`](../docs/player-profile-overlay-v1.md)。
