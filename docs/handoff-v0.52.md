# CourtSim v0.52 跨机器交接

本文是 `v0.52.0` 开发分支的跨机器接续入口。远端分支 HEAD、`PROJECT_STATUS.md`
和 `governance/current-release.json` 共同构成交接事实源；不要从本机生成目录恢复
项目状态。

## 仓库与分支

- 仓库：`https://github.com/cc78978559/courtsim`
- 交接分支：`agent/franchise-v052-handoff`
- 基线分支：`main`
- Draft PR：`https://github.com/cc78978559/courtsim/pull/44`
- 分支基点：`ab30e9c86fc3aaadc7b8f2bc6cdd7a3573c17ce7`
- 最后一个功能提交：`75e0998520b7b194e28ecb486c71403faebab5c6`
- Python：`3.11+`
- 运行时依赖：仅 Python 标准库

交接文档提交本身位于最后一个功能提交之后，因此实际接续提交必须以远端交接
分支 HEAD 为准，不应硬编码本文中的功能提交作为 checkout 目标。

## 当前能力

当前分支包含从完整比赛、轮换、体力、伤病、赛季和合同，到以下联盟管理闭环：

- 30 队、1,230 场常规赛、play-in 和 15 轮季后赛系列；
- 季后赛疲劳、伤病、出场时间和职业负荷连续；
- 14 队 NBA 乐透、交易后选秀权结算和 30 人经理选秀；
- 球员隐藏潜力球探、成长、衰退、伤病负担和退休；
- 鸟权、工资帽层级、工资匹配和交易特例；
- 双边/三方交易市场和白盒经理审批；
- 对手级轮换、攻防策略、节奏调整和跨赛季经理学习；
- 外部快速模拟比较、批量恢复和原子结果；
- 完整 franchise season、严格状态 JSON、SHA-256 存档和多赛季恢复 runner。

引擎版本为 `0.52.0`。概率模型冻结基线仍是
`demo-v1.12 / demo-1.4.0`，联盟功能升级没有冒充新的现实数据校准。

## 验证快照

- Ruff format：通过
- Ruff lint：通过
- mypy strict：通过
- pytest：481 通过
- Windows symlink 权限测试：1 跳过
- 覆盖率：85%
- Linux GitHub Actions：通过
- Windows GitHub Actions：通过

## 关键注意事项

1. **当前成果在交接分支，不在 `main`。** 新机器必须 checkout
   `origin/agent/franchise-v052-handoff`。PR #44 保持 Draft，不能因为 clone 成功就
   假定 `main` 已包含这些功能。
2. **GitHub 只保存源码和治理契约。** `work/` 下的 franchise checkpoint、模拟输出、
   本地实验中间状态和 manifest 不会上传。如果需要接续某个正在运行的具体联盟，
   必须单独复制对应 checkpoint 目录，并用 artifact/runner 的 SHA-256 校验加载；
   只 clone 仓库只能接续代码开发，不能恢复本机未另行传输的联盟存档。
3. **不要上传虚拟环境、缓存或本机构建物。** `.venv`、`dist`、coverage 缓存和
   wheelhouse 均不属于源码交接。离线机器需要通过其他受控渠道传输 wheelhouse。
4. **不要修改冻结现实基线来“匹配”新联盟功能。** 当前概率基线仍是
   `demo-v1.12 / demo-1.4.0`；赛程、经理和 franchise 功能完成不等于 NBA 2K 或真实
   球员级校准已经完成。
5. **经理 AI 保持白盒与权限治理。** Shadow/Assist/Active 的阶段权限、执行收据和
   证据门禁不能在接续时简化成无审计的自动执行。
6. **不要 force push、重写 47 个阶段提交或直接提交到 `main`。** 新工作继续从交接
   分支创建 `agent/*` 分支，并通过 Draft PR 合并。
7. **不要仅凭版本字符串判断恢复成功。** 必须同时确认远端 HEAD、干净工作树、
   `governance/current-release.json` 哈希检查和完整本地门禁。

## 新机器恢复

Windows PowerShell：

```powershell
git clone https://github.com/cc78978559/courtsim.git
cd courtsim
git fetch origin
git switch --track origin/agent/franchise-v052-handoff
git rev-parse HEAD
powershell -ExecutionPolicy Bypass -File .\tools.ps1 bootstrap
powershell -ExecutionPolicy Bypass -File .\tools.ps1 check
```

POSIX shell：

```bash
git clone https://github.com/cc78978559/courtsim.git
cd courtsim
git fetch origin
git switch --track origin/agent/franchise-v052-handoff
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements/build.lock
.venv/bin/python -m pip install -r requirements/dev.lock
.venv/bin/python -m pip install --no-build-isolation --no-deps -e .
.venv/bin/python -m ruff format --check .
.venv/bin/python -m ruff check .
.venv/bin/python -m mypy
.venv/bin/python -m coverage run -m pytest -q
.venv/bin/python -m coverage report
```

恢复后确认：

```powershell
git status --short
git log -1 --oneline
python -c "import courtsim; print(courtsim.__version__)"
```

应得到干净工作树和版本 `0.52.0`。若 HEAD 与远端交接分支不同，先停止开发并检查
是否 checkout 了 `main` 或旧的 `agent/phase8-career-draft`。

如果要恢复具体 franchise 存档，在源码门禁通过后再复制存档目录，并先执行只读
加载验证。不要覆盖新机器上已有的同名 run 目录；runner 使用单写者语义。

## 阅读顺序

1. `docs/handoff-v0.52.md`
2. `PROJECT_STATUS.md`
3. `governance/current-release.json`
4. `docs/current-state.md`
5. `CHANGELOG.md`
6. 与下一任务直接相关的 `docs/*-v1.md` 和对应治理 JSON

无需从头读取全部阶段文档。治理注册表中的版本、路径和 SHA-256 是判断当前实现
是否被正式接入的机器可读依据。

## 不随 Git 传输的内容

以下路径被有意忽略：

- `.venv/`
- `dist/` 和 `build/`
- `work/` 与本地模拟输出
- coverage、pytest、ruff 和 mypy 缓存
- `tools/wheelhouse/*.whl`
- 本机生成的治理报告

在线机器可通过锁定依赖重建开发环境。离线目标机需要另外传输 wheelhouse；不要
把本机虚拟环境或缓存提交到仓库。

## 已知后续方向

优先级较高的后续工作：

1. 将双边/三方交易市场和 cap ledger 正式编排并持久化到 30 队 franchise 闭环；
2. franchise checkpoint 的保留、压缩、归档和 schema 迁移；
3. 更高级的条件选秀权和七年 Stepien 边界；
4. 四轮以上及合同条件的交易谈判；
5. 战术与经理学习的因果实验；
6. 人工批准工作流和玩法/UI 层。

继续开发时保持本地优先、确定性随机地址、严格治理 JSON、全量门禁和 Draft PR
工作流。不要直接 force push 或把生成物加入版本控制。

## PR 合并条件

PR #44 当前应保持 Draft。只有满足以下条件后才转为 Ready：

- 新机器已从远端交接分支完成 bootstrap；
- 新机器完整 `tools.ps1 check` 或等价 POSIX 门禁通过；
- GitHub Linux 与 Windows CI 仍为绿色；
- 工作树干净，未混入 checkpoint、wheelhouse、缓存或秘密；
- `PROJECT_STATUS.md`、`governance/current-release.json` 与引擎版本一致。

合并时建议保留阶段提交历史，不做 force push。合并完成后才能在 `main` 的最终提交
上创建 `v0.52.0` 标签；不要给尚未合并的分支提交创建正式发布标签。
