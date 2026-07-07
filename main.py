"""
光器件产线品质数据可视化分析

模拟光器件生产测试数据（插损、回损等关键指标），
使用 SQLite 存储，基于 Pandas + Matplotlib 进行
良率统计、缺陷趋势分析与可视化报告输出。

新增：SPC 过程控制分析（X-bar-R 控制图、Cpk 过程能力指数、
Western Electric 判异规则）。
"""

import random
import sqlite3
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from tabulate import tabulate

matplotlib.rcParams["font.sans-serif"] = [
    "Microsoft YaHei",
    "SimHei",
    "WenQuanYi Micro Hei",
    "Noto Sans CJK SC",
]
matplotlib.rcParams["axes.unicode_minus"] = False

# ============================================================
# 配置
# ============================================================
DB_PATH = Path(__file__).parent / "production.db"
OUTPUT_DIR = Path(__file__).parent / "output"
CHART_DIR = OUTPUT_DIR / "charts"
SPC_CHART_DIR = OUTPUT_DIR / "spc_charts"
REPORT_PATH = OUTPUT_DIR / "report.csv"
SPC_REPORT_PATH = OUTPUT_DIR / "spc_report.csv"

# 光器件测试指标阈值
SPEC = {
    "IL_1310nm": 2.0,  # 插入损耗上限 (dB)
    "IL_1550nm": 2.2,
    "RL": 45.0,  # 回波损耗下限 (dB)，低于此值不合格
}

# SPC 子组大小
SPC_N = 5

# X-bar-R 控制图常数（子组大小 n=5）
SPC_CONSTANTS = {
    "A2": 0.577,  # X-bar 控制界限系数
    "D3": 0.0,  # R 图下控制界限系数
    "D4": 2.114,  # R 图上控制界限系数
}


# ============================================================
# 终端打印工具（解决中文对齐问题）
# ============================================================


def print_table(df: pd.DataFrame, title: str | None = None) -> None:
    """使用 tabulate 打印对齐的数据表（自动处理 CJK 字符宽度）"""
    if title:
        print(f"\n  {title}")
    work = df.copy()
    # 若有命名索引则转为列
    if work.index.name is not None:
        work = work.reset_index()
    # 将索引列重命名为空字符串以对齐
    if not isinstance(work.columns[0], str) or work.columns[0] == "index":
        pass
    print(
        tabulate(
            work,
            headers="keys",
            tablefmt="simple_outline",
            showindex=False,
            numalign="decimal",
            stralign="left",
        )
    )


# ============================================================
# SQLite 数据库操作
# ============================================================


class ProductionDB:
    """产线测试数据 SQLite 数据库管理"""

    def __init__(self, db_path: Path | str = DB_PATH):
        self.db_path = str(db_path)

    @property
    def conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.db_path)
        c.row_factory = sqlite3.Row
        return c

    def init_table(self):
        c = self.conn
        c.execute("""
            CREATE TABLE IF NOT EXISTS test_records (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                serial_no    TEXT    NOT NULL,
                batch        TEXT    NOT NULL,
                test_time    TEXT    NOT NULL,
                IL_1310nm    REAL    NOT NULL,
                IL_1550nm    REAL    NOT NULL,
                RL           REAL    NOT NULL,
                result       TEXT    NOT NULL,
                fail_reason  TEXT
            )
        """)
        c.commit()
        c.close()

    def insert_df(self, df: pd.DataFrame):
        c = self.conn
        df.to_sql("test_records", c, if_exists="append", index=False)
        c.commit()
        c.close()

    def load_df(self) -> pd.DataFrame:
        c = self.conn
        df = pd.read_sql("SELECT * FROM test_records", c)
        c.close()
        return df

    def clear(self):
        c = self.conn
        c.execute("DROP TABLE IF EXISTS test_records")
        c.close()
        self.init_table()
        print("  数据库已清空并重建。")


# ============================================================
# 数据生成（模拟光器件测试数据）
# ============================================================


def generate_test_data(num_records: int = 1000) -> pd.DataFrame:
    """
    模拟生成光器件产线测试数据。

    每件器件测试两个波长的插入损耗 (IL) 和回波损耗 (RL)，
    按正态分布随机生成数值，超出 SPEC 阈值的标记为不合格。
    """
    random.seed(42)
    np_random = random.Random()

    records = []
    base_time = datetime(2026, 5, 1, 8, 0, 0)

    for i in range(1, num_records + 1):
        batch_num = (i - 1) // 100 + 1
        batch = f"B{batch_num:03d}"
        day_offset = (i - 1) // 300
        minute_offset = ((i - 1) % 300) * 2
        test_time = base_time + timedelta(days=day_offset, minutes=minute_offset)
        serial_no = f"TS-{batch}-{i % 1000:04d}"

        il_1310 = round(np_random.gauss(1.2, 0.4), 3)
        il_1550 = round(np_random.gauss(1.3, 0.45), 3)
        rl = round(np_random.gauss(48.0, 3.0), 2)

        fail_reasons = []
        if il_1310 > SPEC["IL_1310nm"]:
            fail_reasons.append("IL_1310超标")
        if il_1550 > SPEC["IL_1550nm"]:
            fail_reasons.append("IL_1550超标")
        if rl < SPEC["RL"]:
            fail_reasons.append("RL不达标")

        result = "OK" if not fail_reasons else "NG"
        fail_reason = ";".join(fail_reasons) if fail_reasons else None

        records.append(
            {
                "serial_no": serial_no,
                "batch": batch,
                "test_time": test_time.strftime("%Y-%m-%d %H:%M:%S"),
                "IL_1310nm": il_1310,
                "IL_1550nm": il_1550,
                "RL": rl,
                "result": result,
                "fail_reason": fail_reason,
            }
        )

    return pd.DataFrame(records)


# ============================================================
# 基础数据分析
# ============================================================


def analyze_by_batch(df: pd.DataFrame) -> pd.DataFrame:
    """按批次统计：总件数、合格数、良率、平均插损/回损"""
    agg = df.groupby("batch").agg(
        总件数=("result", "count"),
        合格数=("result", lambda s: (s == "OK").sum()),
        IL1310均值=("IL_1310nm", "mean"),
        IL1550均值=("IL_1550nm", "mean"),
        RL均值=("RL", "mean"),
    )
    agg["良率"] = (agg["合格数"] / agg["总件数"] * 100).round(1)
    agg["IL1310均值"] = agg["IL1310均值"].round(3)
    agg["IL1550均值"] = agg["IL1550均值"].round(3)
    agg["RL均值"] = agg["RL均值"].round(2)
    return agg


def analyze_by_day(df: pd.DataFrame) -> pd.DataFrame:
    """按日统计良率趋势"""
    df2 = df.copy()
    df2["日期"] = pd.to_datetime(df2["test_time"]).dt.date
    agg = df2.groupby("日期").agg(
        总件数=("result", "count"),
        合格数=("result", lambda s: (s == "OK").sum()),
    )
    agg["良率"] = (agg["合格数"] / agg["总件数"] * 100).round(1)
    return agg.reset_index()


def analyze_defects(df: pd.DataFrame) -> pd.DataFrame:
    """统计各类不良原因分布"""
    ng = df[df["result"] == "NG"].copy()
    if ng.empty:
        return pd.DataFrame(columns=["不良原因", "数量"])
    reasons: list[str] = []
    for raw in ng["fail_reason"].dropna():
        reasons.extend(raw.split(";"))
    counter = Counter(reasons)
    return pd.DataFrame(
        {"不良原因": list(counter.keys()), "数量": list(counter.values())}
    ).sort_values("数量", ascending=False)


# ============================================================
# SPC 过程控制分析
# ============================================================


def build_subgroups(series: pd.Series, n: int = SPC_N) -> pd.DataFrame:
    """将数据划分为子组，返回子组均值和极差"""
    values = series.dropna().values
    n_groups = len(values) // n
    truncated = values[: n_groups * n].reshape(n_groups, n)
    x_bar = truncated.mean(axis=1)
    r = np.ptp(truncated, axis=1)
    return pd.DataFrame({"subgroup": range(1, n_groups + 1), "x_bar": x_bar, "r": r})


def calc_spc_bounds(sub_df: pd.DataFrame) -> dict:
    """计算 X-bar 和 R 图的控制界限"""
    xbb = sub_df["x_bar"].mean()
    rb = sub_df["r"].mean()
    A2, D3, D4 = SPC_CONSTANTS["A2"], SPC_CONSTANTS["D3"], SPC_CONSTANTS["D4"]
    return {
        "x_center": xbb,
        "x_ucl": xbb + A2 * rb,
        "x_lcl": xbb - A2 * rb,
        "r_center": rb,
        "r_ucl": D4 * rb,
        "r_lcl": D3 * rb,
    }


def calc_cpk(
    values: np.ndarray, usl: float | None = None, lsl: float | None = None
) -> float | None:
    """计算过程能力指数 Cpk。IL 用单侧上限，RL 用单侧下限。"""
    if len(values) < 2:
        return None
    mu = values.mean()
    sigma = values.std(ddof=1)
    if sigma == 0:
        return float("inf")
    cpu = (usl - mu) / (3 * sigma) if usl is not None else float("inf")
    cpl = (mu - lsl) / (3 * sigma) if lsl is not None else float("inf")
    return round(min(cpu, cpl), 2)


def detect_spc_anomalies(sub_df: pd.DataFrame, bounds: dict) -> pd.DataFrame:
    """
    Western Electric 判异规则，检测以下异常模式：
    - 规则1: 单点超出 ±3σ 控制线
    - 规则4: 连续7点在中心线同侧 (Run)
    - 规则5: 连续6点递增或递减 (Trend)
    - 规则2: 连续3点中有2点在 ±2σ 之外（同侧）
    """
    anomalies = pd.DataFrame(
        {
            "subgroup": sub_df["subgroup"],
            "x_bar": sub_df["x_bar"],
            "flagged": False,
            "reason": "",
        }
    )
    x = sub_df["x_bar"].values
    center = bounds["x_center"]
    ucl = bounds["x_ucl"]
    lcl = bounds["x_lcl"]
    n = len(x)
    two_sigma = (ucl - center) * 2 / 3

    for i in range(n):
        # 规则1: 超出控制线
        if x[i] > ucl or x[i] < lcl:
            anomalies.at[i, "flagged"] = True
            anomalies.at[i, "reason"] = "规则1:超出控制线"

    # 规则4: 连续7点在同侧
    for i in range(6, n):
        if all(x[i - j] > center for j in range(7)):
            for j in range(7):
                if not anomalies.at[i - j, "flagged"]:
                    anomalies.at[i - j, "flagged"] = True
                    anomalies.at[i - j, "reason"] = "规则4:连续7点在中心线上方"
        if all(x[i - j] < center for j in range(7)):
            for j in range(7):
                if not anomalies.at[i - j, "flagged"]:
                    anomalies.at[i - j, "flagged"] = True
                    anomalies.at[i - j, "reason"] = "规则4:连续7点在中心线下方"

    # 规则5: 连续6点递增或递减
    for i in range(5, n):
        window = x[i - 5 : i + 1]
        if all(window[k] >= window[k - 1] for k in range(1, 6)):
            for j in range(6):
                if not anomalies.at[i - j, "flagged"]:
                    anomalies.at[i - j, "flagged"] = True
                    anomalies.at[i - j, "reason"] = (
                        f"规则5:连续6点递增({i - 4}~{i + 1})"
                    )
        if all(window[k] <= window[k - 1] for k in range(1, 6)):
            for j in range(6):
                if not anomalies.at[i - j, "flagged"]:
                    anomalies.at[i - j, "flagged"] = True
                    anomalies.at[i - j, "reason"] = (
                        f"规则5:连续6点递减({i - 4}~{i + 1})"
                    )

    # 规则2: 连续3点中有2点在 ±2σ 之外（同侧）
    for i in range(2, n):
        window = x[i - 2 : i + 1]
        above = sum(1 for v in window if v > center + two_sigma)
        below = sum(1 for v in window if v < center - two_sigma)
        if above >= 2:
            for j in range(3):
                if not anomalies.at[i - j, "flagged"]:
                    anomalies.at[i - j, "flagged"] = True
                    anomalies.at[i - j, "reason"] = "规则2:3点中2点超+2σ"
        if below >= 2:
            for j in range(3):
                if not anomalies.at[i - j, "flagged"]:
                    anomalies.at[i - j, "flagged"] = True
                    anomalies.at[i - j, "reason"] = "规则2:3点中2点超-2σ"

    return anomalies


def spc_analysis(
    df: pd.DataFrame, column: str, usl: float | None = None, lsl: float | None = None
) -> dict:
    """对单个指标执行完整 SPC 分析，返回所有结果"""
    sub = build_subgroups(df[column])
    bounds = calc_spc_bounds(sub)
    anomalies = detect_spc_anomalies(sub, bounds)
    cpk = calc_cpk(df[column].dropna().values, usl, lsl)
    return {
        "column": column,
        "subgroups": sub,
        "bounds": bounds,
        "anomalies": anomalies,
        "cpk": cpk,
        "n_groups": len(sub),
        "n_flagged": int(anomalies["flagged"].sum()),
    }


def print_spc_summary(metrics: list[dict]):
    """打印 SPC 汇总表"""
    rows = []
    for m in metrics:
        b = m["bounds"]
        rows.append(
            {
                "指标": m["column"],
                "子组数": m["n_groups"],
                "X-bar均值": round(b["x_center"], 4),
                "X-UCL": round(b["x_ucl"], 4),
                "X-LCL": round(b["x_lcl"], 4),
                "R-bar": round(b["r_center"], 4),
                "R-UCL": round(b["r_ucl"], 4),
                "Cpk": m["cpk"],
                "异常点数": m["n_flagged"],
            }
        )
    summary = pd.DataFrame(rows)
    print_table(summary, "SPC 分析汇总")


def export_spc_report(metrics: list[dict], filepath: Path):
    """导出 SPC 分析报告 CSV"""
    rows = []
    for m in metrics:
        b = m["bounds"]
        cpk = m["cpk"]
        # Cpk 评级
        if cpk is None:
            grade = "N/A"
        elif cpk >= 1.33:
            grade = "A (良好)"
        elif cpk >= 1.0:
            grade = "B (可接受)"
        else:
            grade = "C (需改善)"
        rows.append(
            {
                "指标": m["column"],
                "子组数": m["n_groups"],
                "X-bar均值": round(b["x_center"], 4),
                "X-UCL": round(b["x_ucl"], 4),
                "X-LCL": round(b["x_lcl"], 4),
                "R均值": round(b["r_center"], 4),
                "R-UCL": round(b["r_ucl"], 4),
                "Cpk": cpk,
                "Cpk评级": grade,
                "异常子组数": m["n_flagged"],
            }
        )
        # 附加每个异常子组的详情
        anom = m["anomalies"]
        flagged = anom[anom["flagged"]]
        if len(flagged) > 0:
            for _, row in flagged.iterrows():
                rows.append(
                    {
                        "指标": f"  └ 子组 {int(row.subgroup)}",
                        "子组数": "",
                        "X-bar均值": "",
                        "X-UCL": "",
                        "X-LCL": "",
                        "R均值": "",
                        "R-UCL": "",
                        "Cpk": "",
                        "Cpk评级": "",
                        "异常子组数": row["reason"],
                    }
                )
    pd.DataFrame(rows).to_csv(filepath, index=False, encoding="utf-8-sig")


# ============================================================
# 可视化
# ============================================================


def plot_yield_trend(day_stats: pd.DataFrame) -> Path:
    """良率日趋势折线图"""
    CHART_DIR.mkdir(parents=True, exist_ok=True)
    path = CHART_DIR / "yield_trend.png"
    fig, ax = plt.subplots(figsize=(10, 4.5))
    dates = [str(d) for d in day_stats["日期"]]
    yield_pct = day_stats["良率"].values
    ax.plot(dates, yield_pct, marker="o", color="#2980B9", linewidth=2, markersize=6)
    ax.axhline(y=95, color="#E74C3C", linestyle="--", alpha=0.7, label="95% 良率基准线")
    ax.fill_between(range(len(dates)), yield_pct, alpha=0.15, color="#2980B9")
    for i, y in enumerate(yield_pct):
        ax.annotate(
            f"{y:.1f}%",
            (i, y),
            textcoords="offset points",
            xytext=(0, 10),
            fontsize=8,
            ha="center",
            color="#2C3E50",
        )
    ax.set_title(
        "光器件产线良率日趋势", fontsize=14, fontweight="bold", color="#2C3E50"
    )
    ax.set_xlabel("日期", fontsize=11)
    ax.set_ylabel("良率 (%)", fontsize=11)
    ax.set_ylim(70, 102)
    ax.legend(fontsize=9)
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def plot_batch_yield(batch_stats: pd.DataFrame) -> Path:
    """各批次良率柱状图"""
    CHART_DIR.mkdir(parents=True, exist_ok=True)
    path = CHART_DIR / "batch_yield.png"
    fig, ax = plt.subplots(figsize=(10, 4.5))
    batches = batch_stats.index.tolist()
    yield_pct = batch_stats["良率"].values
    colors = [
        "#27AE60" if y >= 95 else "#E67E22" if y >= 90 else "#E74C3C" for y in yield_pct
    ]
    bars = ax.bar(batches, yield_pct, color=colors, edgecolor="white", linewidth=0.5)
    ax.axhline(y=95, color="#E74C3C", linestyle="--", alpha=0.5, label="95% 基准线")
    for bar, val in zip(bars, yield_pct):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 0.5,
            f"{val:.1f}%",
            ha="center",
            fontsize=8,
            color="#2C3E50",
        )
    ax.set_title("各批次良率对比", fontsize=14, fontweight="bold", color="#2C3E50")
    ax.set_xlabel("批次", fontsize=11)
    ax.set_ylabel("良率 (%)", fontsize=11)
    ax.set_ylim(70, 102)
    ax.legend(fontsize=9)
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def plot_defect_pie(defect_stats: pd.DataFrame) -> Path:
    """不良原因饼图"""
    CHART_DIR.mkdir(parents=True, exist_ok=True)
    path = CHART_DIR / "defect_pie.png"
    fig, ax = plt.subplots(figsize=(6, 6))
    labels = defect_stats["不良原因"].tolist()
    values = defect_stats["数量"].tolist()
    colors = ["#E74C3C", "#E67E22", "#F39C12"]
    wedges, texts, autotexts = ax.pie(
        values,
        labels=labels,
        autopct="%1.1f%%",
        colors=colors[: len(labels)],
        startangle=90,
        textprops={"fontsize": 10},
    )
    for t in autotexts:
        t.set_color("white")
        t.set_fontweight("bold")
    ax.set_title("不良原因分布", fontsize=14, fontweight="bold", color="#2C3E50")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


# --- SPC 控制图 ---


def plot_spc_xbar_r(metric: dict) -> Path:
    """
    绘制 X-bar-R 控制图（上下双面板），标记异常点。
    上：X-bar 图，下：R 图。
    """
    SPC_CHART_DIR.mkdir(parents=True, exist_ok=True)
    col = metric["column"]
    sub = metric["subgroups"]
    bounds = metric["bounds"]
    anomalies = metric["anomalies"]
    safe_name = col.replace("_", "-")
    path = SPC_CHART_DIR / f"spc_{safe_name}.png"

    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(12, 7), sharex=True, gridspec_kw={"height_ratios": [2.5, 1.5]}
    )

    sg = sub["subgroup"].values
    x_vals = sub["x_bar"].values
    r_vals = sub["r"].values

    # ── X-bar 图 ──
    ax1.plot(
        sg, x_vals, "o-", color="#2980B9", linewidth=1.2, markersize=5, label="X-bar"
    )
    ax1.axhline(
        bounds["x_center"],
        color="#2C3E50",
        linestyle="-",
        linewidth=1.5,
        label=f"CL={bounds['x_center']:.4f}",
    )
    ax1.axhline(
        bounds["x_ucl"],
        color="#E74C3C",
        linestyle="--",
        linewidth=1.2,
        label=f"UCL={bounds['x_ucl']:.3f}",
    )
    ax1.axhline(
        bounds["x_lcl"],
        color="#E74C3C",
        linestyle="--",
        linewidth=1.2,
        label=f"LCL={bounds['x_lcl']:.3f}",
    )
    # 异常点标红
    flagged = anomalies[anomalies["flagged"]]
    if len(flagged) > 0:
        ax1.scatter(
            flagged["subgroup"],
            flagged["x_bar"],
            color="red",
            s=80,
            zorder=5,
            marker="o",
            edgecolors="darkred",
            linewidths=1,
            label=f"异常点 ({len(flagged)}个)",
        )
    ax1.set_ylabel(f"{col} 子组均值", fontsize=11)
    ax1.set_title(
        f"SPC X-bar-R 控制图 —— {col}", fontsize=14, fontweight="bold", color="#2C3E50"
    )
    ax1.legend(fontsize=8, loc="upper right", ncol=2)
    ax1.grid(alpha=0.3)

    # ── R 图 ──
    ax2.plot(
        sg, r_vals, "o-", color="#27AE60", linewidth=1.2, markersize=5, label="R (极差)"
    )
    ax2.axhline(
        bounds["r_center"],
        color="#2C3E50",
        linestyle="-",
        linewidth=1.5,
        label=f"CL={bounds['r_center']:.4f}",
    )
    ax2.axhline(
        bounds["r_ucl"],
        color="#E74C3C",
        linestyle="--",
        linewidth=1.2,
        label=f"UCL={bounds['r_ucl']:.3f}",
    )
    if bounds["r_lcl"] > 0:
        ax2.axhline(
            bounds["r_lcl"],
            color="#E74C3C",
            linestyle="--",
            linewidth=1.2,
            label=f"LCL={bounds['r_lcl']:.3f}",
        )
    ax2.set_xlabel("子组编号 (n=5)", fontsize=11)
    ax2.set_ylabel("极差 R", fontsize=11)
    ax2.legend(fontsize=8, loc="upper right", ncol=2)
    ax2.grid(alpha=0.3)

    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def plot_cpk_summary(metrics: list[dict]) -> Path:
    """Cpk 汇总柱状图，按颜色标注等级"""
    SPC_CHART_DIR.mkdir(parents=True, exist_ok=True)
    path = SPC_CHART_DIR / "cpk_summary.png"

    fig, ax = plt.subplots(figsize=(8, 4.5))
    names = [m["column"] for m in metrics]
    cpks = [m["cpk"] or 0 for m in metrics]
    colors = [
        "#27AE60" if c >= 1.33 else "#F39C12" if c >= 1.0 else "#E74C3C" for c in cpks
    ]

    bars = ax.bar(
        names, cpks, color=colors, edgecolor="white", linewidth=0.5, width=0.4
    )
    ax.axhline(
        y=1.33, color="#27AE60", linestyle="--", alpha=0.6, label="Cpk=1.33 (良好)"
    )
    ax.axhline(
        y=1.0, color="#F39C12", linestyle="--", alpha=0.6, label="Cpk=1.0 (可接受)"
    )

    for bar, val in zip(bars, cpks):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 0.02,
            f"{val:.2f}" if val > 0 else "N/A",
            ha="center",
            fontsize=11,
            fontweight="bold",
            color="#2C3E50",
        )

    ax.set_title(
        "过程能力指数 Cpk 汇总", fontsize=14, fontweight="bold", color="#2C3E50"
    )
    ax.set_ylabel("Cpk", fontsize=11)
    ax.set_ylim(0, max(cpks) * 1.3 + 0.3 if max(cpks) > 0 else 2)
    ax.legend(fontsize=9)
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


# ============================================================
# CSV 导入导出
# ============================================================


def export_to_csv(df: pd.DataFrame, filepath: Path | str):
    """导出数据为 CSV"""
    df.to_csv(filepath, index=False, encoding="utf-8-sig")
    print(f"  数据已导出: {filepath} ({len(df)} 行)")


def import_from_csv(filepath: Path | str) -> pd.DataFrame:
    """从 CSV 导入数据"""
    df = pd.read_csv(filepath)
    print(f"  已导入 {len(df)} 条记录")
    return df


# ============================================================
# 主流程
# ============================================================


def run_pipeline(num_records: int = 2000):
    """执行完整分析流程"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("  光器件产线品质数据可视化分析")
    print("  SPC 过程控制 + 良率趋势 + 缺陷分析")
    print("=" * 60)

    # 1. 初始化数据库
    print("\n[1/8] 初始化 SQLite 数据库...")
    db = ProductionDB()
    db.clear()

    # 2. 生成模拟数据
    print(f"\n[2/8] 生成 {num_records} 条模拟测试数据...")
    df = generate_test_data(num_records)
    ok_count = int((df["result"] == "OK").sum())
    ng_count = num_records - ok_count
    print(
        f"  合格: {ok_count} 件, 不合格: {ng_count} 件, "
        f"良率: {ok_count / num_records * 100:.1f}%"
    )

    # 3. 存入数据库
    print("\n[3/8] 写入 SQLite 数据库...")
    db.insert_df(df)
    print(f"  已写入 {len(df)} 条记录 -> {DB_PATH.name}")

    # 4. 基础数据分析
    print("\n[4/8] 基础数据分析...")
    batch_stats = analyze_by_batch(df)
    day_stats = analyze_by_day(df)
    defect_stats = analyze_defects(df)
    print_table(batch_stats, "批次良率统计")
    print_table(day_stats, "日良率趋势")
    if not defect_stats.empty:
        print_table(defect_stats, "不良原因分布")

    # 5. SPC 过程控制分析
    print("\n[5/8] SPC 过程控制分析 (子组大小 n=5)...")
    spc_metrics = [
        spc_analysis(df, "IL_1310nm", usl=SPEC["IL_1310nm"]),
        spc_analysis(df, "IL_1550nm", usl=SPEC["IL_1550nm"]),
        spc_analysis(df, "RL", lsl=SPEC["RL"]),
    ]
    print_spc_summary(spc_metrics)

    # 6. 生成基础图表
    print("\n[6/8] 生成基础可视化图表...")
    chart1 = plot_yield_trend(day_stats)
    chart2 = plot_batch_yield(batch_stats)
    print(f"  [OK] {chart1}")
    print(f"  [OK] {chart2}")
    if not defect_stats.empty:
        chart3 = plot_defect_pie(defect_stats)
        print(f"  [OK] {chart3}")

    # 7. 生成 SPC 控制图
    print("\n[7/8] 生成 SPC 控制图...")
    for m in spc_metrics:
        p = plot_spc_xbar_r(m)
        print(f"  [OK] {p}")
    cpk_p = plot_cpk_summary(spc_metrics)
    print(f"  [OK] {cpk_p}")

    # 8. 导出报告
    print("\n[8/8] 导出分析报告...")
    export_to_csv(batch_stats, REPORT_PATH)
    export_spc_report(spc_metrics, SPC_REPORT_PATH)
    print(f"  SPC报告已导出: {SPC_REPORT_PATH}")

    print("\n" + "=" * 60)
    print("  分析完成！输出文件：")
    print(f"    数据库:    {DB_PATH}")
    print(f"    基础图表:  {CHART_DIR}")
    print(f"    SPC 图表:  {SPC_CHART_DIR}")
    print(f"    报告:      {REPORT_PATH}")
    print(f"    SPC 报告:  {SPC_REPORT_PATH}")
    print("=" * 60)


if __name__ == "__main__":
    run_pipeline(2000)
