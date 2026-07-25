# CourtSim

一个本地优先的离散空间篮球模拟器底层工程。当前阶段只提供可复现模拟所需的基础工具，不绑定具体球员、联盟或玩法循环。

## 设计约束

- 默认完全离线运行，不依赖网络服务。
- Python 标准库即可执行测试和演示。
- 同一配置、同一主种子必须产生完全相同的事件流。
- 每一局使用独立随机流，批处理顺序或并行度不能改变结果。
- 原始事件使用 JSONL 保存，汇总结果可以随时重新计算。
- 输入文件和输出文件带 SHA-256 摘要，便于追踪实验来源。

## 快速开始

首次准备开发环境：

```powershell
.\tools.ps1 bootstrap
.\tools.ps1 doctor
.\tools.ps1 check
```

`bootstrap`优先使用 `tools/wheelhouse` 的本地安装包，可以在断网环境重建；在 Windows
上会依次查找 `python` 和 `py` 启动器中的 Python 3.11+。运行时模拟器本身仍然没有
第三方依赖。

常用模拟命令：

```powershell
.\tools.ps1 validate examples/minimal_scenario.json
.\tools.ps1 demo --seed 20260722 --output work/runs/demo
.\tools.ps1 batch --master-seed 20260722 --runs 100 --workers 4
.\tools.ps1 model-benchmark --games 100 --workers 4 --repeats 3
.\tools.ps1 replay work/runs/demo/events.jsonl --possession 3
.\tools.ps1 verify work/runs/demo/manifest.json
```

如果本机 PowerShell 禁止执行脚本，可直接使用 `python -m courtsim`，并把 `src` 加入 `PYTHONPATH`；无需修改全局执行策略。

如需安装本地命令（不会下载运行时依赖）：

```powershell
python -m pip install -e . --no-deps
courtsim doctor
```

## 目录

```text
src/courtsim/       核心库与命令行入口
data/               正式输入、测试夹具和参考数据边界
docs/               架构、工具和决策记录
examples/           可版本控制的最小输入样例
experiments/         可版本控制的实验定义
requirements/       依赖范围与本地锁定版本
tests/              标准库测试
tools/wheelhouse/    本机离线开发工具安装包
work/runs/          本地运行产物（不进版本库）
outputs/            需要交付给用户的成品
```

## 当前模型状态

最新机制和正式真实性基线均为结构 `demo-v1.12`、参数 `demo-1.4.0`。独立种子
`20260728` 的 100 场完整事件审计通过 10 项 NBA 核心目标、3 项罚球目标和
37 项回归门禁。当前模型已具备离散行动计划、球员感知概率、攻防交互、助攻、
篮板、失误、投篮与非投篮犯规、球队 bonus、逐次罚球、末节节奏与故意犯规续接。
它仍是无 UI、无连续坐标的概率比赛模型，尚不包含换人、体力、伤病、加时和赛季管理。

当前工程进度、验证结果和已知缺口见
[PROJECT_STATUS.md](PROJECT_STATUS.md)。

引擎、模型结构、参数和正式基线的版本规则及晋级门禁见
[docs/versioning-and-promotion-v1.md](docs/versioning-and-promotion-v1.md)；机器可读的
当前正式入口是 [governance/current-release.json](governance/current-release.json)。

开始阅读、向其他模型交接或准备下一阶段工作时，优先使用
[docs/current-state.md](docs/current-state.md)。该文件是当前架构、正式产物、
不变量和已知边界的精简入口；其他 `*-v1.md` 主要记录各阶段的详细契约和历史决策。

本地工具链、质量门禁、Replay和Trace边界详见 [docs/tooling.md](docs/tooling.md)。

真实模型的批量比赛、分片、分布指标和哈希审计详见
[docs/batch-audit-tooling-v1.md](docs/batch-audit-tooling-v1.md)。

多阵容、多参数版本的可续跑实验调度、候选排名和多种子稳健性审计详见
[docs/experiment-matrix-v1.md](docs/experiment-matrix-v1.md)。

配对种子的阵容/参数反事实方向门禁详见
[docs/matrix-contrast-v1.md](docs/matrix-contrast-v1.md)。

球员档案的可审计单因素覆盖与敏感性实验详见
[docs/player-profile-overlay-v1.md](docs/player-profile-overlay-v1.md)。

真实性目标的来源、激活和评分契约详见
[docs/realism-target-contract-v1.md](docs/realism-target-contract-v1.md)。

NBA 2024-25 常规赛核心来源快照、分母映射与首次偏差报告详见
[docs/nba-reference-targets-v1.md](docs/nba-reference-targets-v1.md)。

代表性五人夹具、参数覆盖工具、候选扫描和 `demo-0.5.0` 结构校准详见
[docs/structure-calibration-v1.md](docs/structure-calibration-v1.md)。

独立助攻判定、助攻者归属、投篮执行校准和 `demo-0.6.0` 冻结结果详见
[docs/assist-execution-calibration-v1.md](docs/assist-execution-calibration-v1.md)。

投篮犯规、逐次罚球、末次罚球篮板、官方罚球目标和 `demo-0.7.0` 冻结结果详见
[docs/foul-free-throw-calibration-v1.md](docs/foul-free-throw-calibration-v1.md)。
Current engine work includes an opt-in, versioned [`nba-v1` complete-game rule layer](docs/complete-game-rules-v1.md):
deterministic overtime, foul-out replacement, offensive fouls, final-two-minute team-foul
penalties, and technical free throws. The promoted probability baseline remains
`demo-v1.12 / demo-1.4.0`.

The opt-in [`rotation-v1 / fatigue-v1` layer](docs/rotations-and-fatigue-v1.md) adds full
rosters, clock-addressed rotations, canonical substitution and player-seconds ledgers, bounded
fatigue/recovery, and explicit ability feedback without changing the frozen probability baseline.
