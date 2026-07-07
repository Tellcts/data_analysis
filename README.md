# 光器件产线品质数据可视化分析

模拟光器件生产测试数据，使用 SQLite 存储，基于 Pandas + Matplotlib 进行
良率统计、SPC 过程控制分析、缺陷趋势分析与可视化报告输出。
支持 CLI 一键分析和 Streamlit 交互式 Web 看板。

## 项目结构

```
data_analysis/
├── main.py              ← 主程序（CLI 分析流程）
├── streamlit_app.py     ← Web 看板（Streamlit Dashboard）
├── production.db        ← SQLite 数据库（运行时生成）
├── output/
│   ├── charts/          ← 基础图表（良率趋势、批次良率、缺陷分布）
│   ├── spc_charts/      ← SPC 控制图（X-bar-R 图、Cpk 汇总）
│   ├── report.csv       ← 批次良率报告
│   ├── spc_report.csv   ← SPC 分析报告
│   └── analysis_report.pdf ← PDF 正式报告
└── pyproject.toml       ← uv 项目配置
```

## 快速开始

```bash
# 克隆仓库到本地
git clone --depth=1 https://github.com/Tellcts/data_analysis.git

# 安装依赖（uv 自动管理）
cd data_analysis
uv sync

# 运行 CLI 分析
uv run main.py

# 启动 Web 看板
uv run streamlit run streamlit_app.py
```

## 功能模块

### 基础分析
- 按批次/日期统计良率
- 不良原因分布（饼图）
- 良率日趋势、批次对比图表

### SPC 过程控制
- X-bar-R 控制图（子组 n=5）
- 过程能力指数 Cpk 计算
- Western Electric 判异规则（规则1/2/4/5）
- 异常点自动检测与标记

### PDF 报告
- 使用 reportlab 生成正式 PDF 品质分析报告
- 包含 KPI 概览、SPC 汇总表、批次良率表
- 嵌入所有分析图表（良率趋势、SPC 控制图、Cpk 汇总等）

### Web 看板 (Streamlit)
- 交互式数据筛选（批次、日期范围、指标）
- 实时 SPC 控制图 + 过程参数面板
- 良率趋势对比 + Cpk 汇总
- 数据明细表格（可筛选 OK/NG）
- 缺陷分析（饼图 + 批次不良统计）

## 技术栈

| 工具        | 用途                 |
| ----------- | -------------------- |
| Python 3.14 | 编程语言             |
| Pandas      | 数据处理与分析       |
| Matplotlib  | 可视化图表           |
| NumPy       | 数值计算             |
| SQLite3     | 嵌入式数据库         |
| Streamlit   | Web 看板             |
| Tabulate    | 终端表格对齐         |
| ReportLab   | PDF 报告生成         |
| uv          | 依赖管理与虚拟环境   |
