# 数据边界

后续数据按用途拆分：

- `schemas/`：机器可验证的格式定义
- `fixtures/`：测试用极小数据集
- `fictional/`：虚构球员与球队
- `reference/`：只读参考统计及来源说明
- `curated/`：由参考数据清洗出的正式输入

大型批跑结果不放入本目录，应写入 `work/experiments/`。

