# NBA 本地数据流水线 v1

## 目标

原始逐回合文件只在本机缓存和处理。CourtSim、Git 和 AI 上下文只接收带来源哈希的
小型 JSON 汇总，从而避免把几十万行数据放进对话或模型上下文。

流水线没有运行时第三方依赖，支持普通 CSV、`.csv.gz`、`.csv.xz`、ZIP，以及只含
一个目标 CSV 的 `.tar.gz` / `.tar.xz`。

## 推荐来源

个人研究优先下载 SportsDataverse `hoopR` 的预构建赛季文件，或
`shufinskiy/nba_data` 的赛季压缩包。不要把原始文件提交到 CourtSim 仓库，也不要
依赖模拟运行时联网。

仓库已包含一个经过本机连接、内容哈希和表头验证的可选清单：
`experiments/nba-data/shufinskiy-nbastatsv3-2024.json`。它不需要账号或 API Key，
原始数据仍只进入本地缓存。

## 工作流

1. 将下载文件放在仓库外，或放入被忽略的 `.cache/nba-data`；本地 `path` 相对清单
   文件所在目录解析。
2. 复制示例清单并填写本地 `path` 或 HTTPS `url`。
3. 首次同步、流式构建，然后检查状态：

```powershell
Copy-Item experiments/nba-data/hoopr-pbp-manifest.example.json work/nba-data.json
# 将 nba_pbp_2025.csv.gz 放到 work/，与清单同目录
.\tools.cmd nba-data sync work/nba-data.json
.\tools.cmd nba-data build work/nba-data.json work/nba-2024-25-summary.json
.\tools.cmd nba-data status work/nba-data.json `
  --output work/nba-2024-25-summary.json
```

直接使用已验证的无 Key 2024-25 端点：

```powershell
.\tools.cmd nba-data sync experiments/nba-data/shufinskiy-nbastatsv3-2024.json
.\tools.cmd nba-data build experiments/nba-data/shufinskiy-nbastatsv3-2024.json `
  work/nba-2024-25-events-summary.json
```

默认缓存目录是 `.cache/nba-data/<dataset_id>/`。跨机器接续时传递原始数据文件，
或在新机器上再次执行 `sync`；Git 只需要传递清单和处理代码。

## 安全与增量规则

- URL 只允许 HTTPS。
- 清单可固定来源 SHA-256；不匹配的下载会立即删除。
- `sync --offline` 只接受已存在且通过校验的缓存。
- `sync --force` 显式重新复制或下载来源；默认优先复用缓存。
- `build` 流式逐行聚合，不会把完整赛季载入内存。
- 输入文件和清单哈希未变化时，`build` 直接复用现有汇总。
- `status` 只读取文件元数据与哈希，不读取原始 CSV 行。
- `--force` 可显式重建。

## 聚合清单

`build.metrics` 支持：

- `count`：计数匹配行；
- `distinct_count`：统计某列非空唯一值；
- `sum`：对某列流式求和；
- `ratio`：用两个已定义指标相除。

条件支持 `equals`、`not_equals`、`in`、`contains`、`not_contains`、
`contains_ci`、`not_contains_ci` 和 `truthy`；`_ci` 变体不区分大小写。
列名或事件文本必须与下载文件实际 schema 对齐；来源升级导致列变化时，构建会明确
失败，不会静默产生错误指标。

输出中的 `local_reduction.context_reduction_ratio` 是原始文件字节数相对紧凑汇总
的缩减比例，用于工程上下文预算，不冒充精确的模型 Token 计数。
