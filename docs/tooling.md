# 本地工具链

## 原则

- 模拟器运行时保持零第三方依赖。
- 开发工具安装在项目内 `.venv`，不污染全局 Python。
- `requirements/dev.lock` 固定当前开发环境；`dev.in` 表达允许升级的范围。
- `tools/wheelhouse` 保存本机离线安装包，但不进入版本控制。
- 所有常用操作统一经过根目录 `tools.ps1`。

## 初次准备

```powershell
.\tools.ps1 bootstrap
.\tools.ps1 doctor
.\tools.ps1 check
```

`bootstrap` 优先使用本地 wheelhouse。没有本地安装包时才会联网下载。

## 日常命令

```powershell
.\tools.ps1 format
.\tools.ps1 lint
.\tools.ps1 typecheck
.\tools.ps1 test
.\tools.ps1 coverage
.\tools.ps1 check
```

`check`依次执行格式检查、静态检查、严格类型检查、测试和覆盖率门槛。

## 模拟产物工具

```powershell
.\tools.ps1 replay work/runs/demo/events.jsonl --possession 3
.\tools.ps1 verify work/runs/demo/manifest.json
```

Replay只读取已保存事件，不重新运行模拟。Verify会重新计算清单中输入和输出文件的SHA-256。

## Trace边界

正式事件记录“发生了什么”，Decision Trace记录“AI为什么这样选择”。Trace包含候选项、权重、概率、选中项和随机流名称，默认批跑时可以关闭。

