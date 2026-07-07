"""
光器件产线品质看板 —— Streamlit Web Dashboard

使用 streamlit 构建交互式产线品质分析看板，
支持数据筛选、SPC 控制图、良率趋势、缺陷分析。
"""

import sys
from pathlib import Path

# 确保能导入同目录下的 main 模块
sys.path.insert(0, str(Path(__file__).parent))

import matplotlib
import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

import main as m

matplotlib.rcParams["font.sans-serif"] = [
    "Microsoft YaHei",
    "SimHei",
    "WenQuanYi Micro Hei",
    "Noto Sans CJK SC",
]
matplotlib.rcParams["axes.unicode_minus"] = False

# ============================================================
# 页面配置
# ============================================================
st.set_page_config(
    page_title="光器件产线品质看板",
    page_icon="📊",
    layout="wide",
)


# 数据缓存
@st.cache_data
def load_or_generate(num: int = 2000) -> pd.DataFrame:
    """优先从 SQLite 加载，否则重新生成"""
    try:
        db = m.ProductionDB()
        df = db.load_df()
        if not df.empty:
            return df
    except Exception:
        pass
    return m.generate_test_data(num)


# ============================================================
# 侧边栏：数据控制
# ============================================================
st.sidebar.title("📋 数据控制")

num_records = st.sidebar.number_input(
    "模拟数据量", min_value=500, max_value=10000, value=2000, step=500
)
if st.sidebar.button("🔄 重新生成模拟数据"):
    st.cache_data.clear()
    df_new = m.generate_test_data(num_records)
    db = m.ProductionDB()
    db.clear()
    db.insert_df(df_new)
    st.sidebar.success(f"已生成 {num_records} 条新数据")
    st.rerun()

# 加载数据
df = load_or_generate(num_records)
df["test_time"] = pd.to_datetime(df["test_time"])

# 侧边栏筛选
st.sidebar.title("🔍 筛选条件")

all_batches = sorted(df["batch"].unique())
selected_batches = st.sidebar.multiselect("批次", all_batches, default=all_batches[:10])

min_date = df["test_time"].min().date()
max_date = df["test_time"].max().date()
date_range = st.sidebar.date_input("日期范围", [min_date, max_date])

# 应用筛选
mask = df["batch"].isin(selected_batches)
if len(date_range) == 2:
    mask &= (df["test_time"].dt.date >= date_range[0]) & (
        df["test_time"].dt.date <= date_range[1]
    )
df_filtered = df[mask].copy()

# 指标选择
metrics = {
    "插入损耗 1310nm": "IL_1310nm",
    "插入损耗 1550nm": "IL_1550nm",
    "回波损耗 RL": "RL",
}
selected_metric_label = st.sidebar.selectbox("SPC 指标", list(metrics.keys()))
selected_metric = metrics[selected_metric_label]

# ============================================================
# 主页面
# ============================================================
st.title("📊 光器件产线品质看板")
st.caption(
    f"数据范围: {df_filtered['test_time'].min().strftime('%Y-%m-%d')} ~ "
    f"{df_filtered['test_time'].max().strftime('%Y-%m-%d')} | "
    f"记录数: {len(df_filtered)} | "
    f"批次: {len(selected_batches)}"
)

# ── KPI 行 ──
total = len(df_filtered)
ok_count = int((df_filtered["result"] == "OK").sum())
ng_count = total - ok_count
yield_pct = ok_count / total * 100 if total > 0 else 0

col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("📦 总件数", f"{total}")
col2.metric("✅ 合格数", f"{ok_count}")
col3.metric("❌ 不合格", f"{ng_count}", delta=None)
col4.metric(
    "📈 良率",
    f"{yield_pct:.1f}%",
    delta=f"{yield_pct - 80:.1f}%" if yield_pct else None,
)
# Cpk
spc = m.spc_analysis(
    df_filtered,
    selected_metric,
    usl=m.SPEC.get(selected_metric) if "IL" in selected_metric else None,
    lsl=m.SPEC.get(selected_metric) if "RL" in selected_metric else None,
)
col5.metric("🎯 Cpk", f"{spc['cpk']}" if spc["cpk"] else "N/A")

# ── 标签页 ──
tab1, tab2, tab3, tab4 = st.tabs(
    ["📈 SPC 控制图", "📊 良率趋势", "📋 数据明细", "🔍 缺陷分析"]
)

with tab1:
    st.subheader(f"X-bar-R 控制图 —— {selected_metric_label}")

    col_l, col_r = st.columns([3, 1])
    with col_l:
        # 绘制 SPC 控制图
        fig, (ax1, ax2) = plt.subplots(
            2,
            1,
            figsize=(10, 6),
            sharex=True,
            gridspec_kw={"height_ratios": [2.5, 1.5]},
        )
        sub = spc["subgroups"]
        bounds = spc["bounds"]
        anom = spc["anomalies"]

        sg = sub["subgroup"].values
        xb = sub["x_bar"].values
        rr = sub["r"].values

        # X-bar 图
        ax1.plot(sg, xb, "o-", color="#2980B9", lw=1.2, ms=4, label="X-bar")
        ax1.axhline(
            bounds["x_center"],
            color="#2C3E50",
            lw=1.5,
            label=f"CL={bounds['x_center']:.4f}",
        )
        ax1.axhline(
            bounds["x_ucl"],
            color="#E74C3C",
            ls="--",
            lw=1,
            label=f"UCL={bounds['x_ucl']:.3f}",
        )
        ax1.axhline(
            bounds["x_lcl"],
            color="#E74C3C",
            ls="--",
            lw=1,
            label=f"LCL={bounds['x_lcl']:.3f}",
        )

        flagged = anom[anom["flagged"]]
        if len(flagged) > 0:
            ax1.scatter(
                flagged["subgroup"],
                flagged["x_bar"],
                color="red",
                s=60,
                zorder=5,
                marker="o",
                edgecolors="darkred",
                lw=1,
                label=f"异常 ({len(flagged)}点)",
            )

        ax1.set_ylabel("子组均值", fontsize=10)
        ax1.set_title("X-bar 控制图", fontsize=13, fontweight="bold")
        ax1.legend(fontsize=7, loc="upper right", ncol=2)
        ax1.grid(alpha=0.3)

        # R 图
        ax2.plot(sg, rr, "o-", color="#27AE60", lw=1.2, ms=4, label="R")
        ax2.axhline(
            bounds["r_center"],
            color="#2C3E50",
            lw=1.5,
            label=f"CL={bounds['r_center']:.4f}",
        )
        ax2.axhline(
            bounds["r_ucl"],
            color="#E74C3C",
            ls="--",
            lw=1,
            label=f"UCL={bounds['r_ucl']:.3f}",
        )
        if bounds["r_lcl"] > 0:
            ax2.axhline(
                bounds["r_lcl"],
                color="#E74C3C",
                ls="--",
                lw=1,
                label=f"LCL={bounds['r_lcl']:.3f}",
            )
        ax2.set_xlabel("子组编号 (n=5)", fontsize=10)
        ax2.set_ylabel("极差 R", fontsize=10)
        ax2.legend(fontsize=7, loc="upper right", ncol=2)
        ax2.grid(alpha=0.3)

        fig.tight_layout()
        st.pyplot(fig)

    with col_r:
        st.markdown("### ⚙️ 过程参数")
        st.markdown(f"""
        | 参数 | 值 |
        |------|-----|
        | **X-bar 均值** | `{bounds["x_center"]:.4f}` |
        | **X-UCL** | `{bounds["x_ucl"]:.4f}` |
        | **X-LCL** | `{bounds["x_lcl"]:.4f}` |
        | **R 均值** | `{bounds["r_center"]:.4f}` |
        | **R-UCL** | `{bounds["r_ucl"]:.4f}` |
        """)
        st.markdown("### 🎯 过程能力")
        cpk_val = spc["cpk"] or 0
        cpk_color = (
            "#27AE60" if cpk_val >= 1.33 else "#F39C12" if cpk_val >= 1.0 else "#E74C3C"
        )
        cpk_grade = (
            "A (良好)"
            if cpk_val >= 1.33
            else "B (可接受)"
            if cpk_val >= 1.0
            else "C (需改善)"
        )
        st.markdown(
            f"**Cpk =** <span style='color:{cpk_color};font-size:24px'>{cpk_val:.2f}</span> &nbsp; {cpk_grade}",
            unsafe_allow_html=True,
        )

        # 异常明细
        flagged = anom[anom["flagged"]]
        if len(flagged) > 0:
            st.markdown(f"### ⚠️ 异常点 ({len(flagged)}处)")
            st.dataframe(
                flagged[["subgroup", "x_bar", "reason"]].rename(
                    columns={"subgroup": "子组", "x_bar": "X-bar", "reason": "原因"}
                ),
                hide_index=True,
                use_container_width=True,
            )

with tab2:
    st.subheader("良率趋势分析")

    c1, c2 = st.columns(2)
    with c1:
        # 日良率趋势
        day_stats = m.analyze_by_day(df_filtered)
        fig, ax = plt.subplots(figsize=(6, 4))
        dates = [str(d) for d in day_stats["日期"]]
        yp = day_stats["良率"].values
        ax.plot(dates, yp, marker="o", color="#2980B9", lw=2, ms=6)
        ax.axhline(y=95, color="#E74C3C", ls="--", alpha=0.7, label="95% 基准")
        for i, y in enumerate(yp):
            ax.annotate(
                f"{y:.1f}%",
                (i, y),
                xytext=(0, 8),
                textcoords="offset points",
                fontsize=8,
                ha="center",
            )
        ax.set_title("日良率趋势", fontweight="bold")
        ax.set_ylim(60, 102)
        ax.grid(axis="y", alpha=0.3)
        ax.legend(fontsize=8)
        fig.tight_layout()
        st.pyplot(fig)

    with c2:
        # 批次良率柱状图
        batch_stats = m.analyze_by_batch(df_filtered)
        fig, ax = plt.subplots(figsize=(6, 4))
        batches = batch_stats.index.tolist()
        yp2 = batch_stats["良率"].values
        colors = [
            "#27AE60" if y >= 95 else "#E67E22" if y >= 90 else "#E74C3C" for y in yp2
        ]
        ax.bar(batches, yp2, color=colors, edgecolor="white")
        ax.axhline(y=95, color="#E74C3C", ls="--", alpha=0.5, label="95% 基准")
        for bar, val in zip(ax.patches, yp2):
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height() + 0.5,
                f"{val:.1f}%",
                ha="center",
                fontsize=7,
            )
        ax.set_title("批次良率对比", fontweight="bold")
        ax.set_ylim(50, 102)
        ax.legend(fontsize=8)
        ax.grid(axis="y", alpha=0.3)
        fig.tight_layout()
        st.pyplot(fig)

    # Cpk 汇总
    st.subheader("过程能力指数 (Cpk) 汇总")
    all_metrics = [
        m.spc_analysis(df_filtered, "IL_1310nm", usl=m.SPEC["IL_1310nm"]),
        m.spc_analysis(df_filtered, "IL_1550nm", usl=m.SPEC["IL_1550nm"]),
        m.spc_analysis(df_filtered, "RL", lsl=m.SPEC["RL"]),
    ]
    fig, ax = plt.subplots(figsize=(5, 2.5))
    names = [mt["column"] for mt in all_metrics]
    cpks = [mt["cpk"] or 0 for mt in all_metrics]
    bar_colors = [
        "#27AE60" if c >= 1.33 else "#F39C12" if c >= 1.0 else "#E74C3C" for c in cpks
    ]
    bars = ax.barh(names, cpks, color=bar_colors, edgecolor="white", height=0.4)
    ax.axvline(x=1.33, color="#27AE60", ls="--", alpha=0.6)
    ax.axvline(x=1.0, color="#F39C12", ls="--", alpha=0.6)
    for bar, val in zip(bars, cpks):
        ax.text(
            bar.get_width() + 0.02,
            bar.get_y() + bar.get_height() / 2,
            f"{val:.2f}",
            va="center",
            fontsize=11,
            fontweight="bold",
        )
    ax.set_xlim(0, max(cpks) * 1.3 + 0.3 if max(cpks) > 0 else 2)
    ax.set_title("Cpk 汇总", fontweight="bold")
    ax.grid(axis="x", alpha=0.3)
    fig.tight_layout()
    st.pyplot(fig)

with tab3:
    st.subheader("测试数据明细")
    col_search, col_result = st.columns([1, 3])
    with col_search:
        result_filter = st.radio("结果筛选", ["全部", "OK", "NG"], horizontal=True)
    show_df = df_filtered.copy()
    if result_filter != "全部":
        show_df = show_df[show_df["result"] == result_filter]
    st.dataframe(
        show_df.sort_values("test_time").head(500),
        hide_index=True,
        use_container_width=True,
        column_config={
            "serial_no": "序列号",
            "batch": "批次",
            "test_time": "测试时间",
            "IL_1310nm": "IL_1310nm",
            "IL_1550nm": "IL_1550nm",
            "RL": "RL",
            "result": "结果",
            "fail_reason": "不良原因",
        },
    )
    st.caption(f"显示前 500 条（共 {len(show_df)} 条）")

with tab4:
    st.subheader("缺陷分析")
    c1, c2 = st.columns(2)
    with c1:
        defect_stats = m.analyze_defects(df_filtered)
        if not defect_stats.empty:
            fig, ax = plt.subplots(figsize=(5, 5))
            labels = defect_stats["不良原因"].tolist()
            values = defect_stats["数量"].tolist()
            pie_colors = ["#E74C3C", "#E67E22", "#F39C12"]
            wedges, texts, autotexts = ax.pie(
                values,
                labels=labels,
                autopct="%1.1f%%",
                colors=pie_colors[: len(labels)],
                startangle=90,
                textprops={"fontsize": 10},
            )
            for t in autotexts:
                t.set_color("white")
                t.set_fontweight("bold")
            ax.set_title("不良原因分布", fontweight="bold")
            fig.tight_layout()
            st.pyplot(fig)
        else:
            st.info("所有产品合格，无不良记录")

    with c2:
        # 各批次不良数
        st.markdown("#### 各批次不良统计")
        ng_by_batch = (
            df_filtered[df_filtered["result"] == "NG"]
            .groupby("batch")
            .size()
            .reset_index(name="不良数")
        )
        if len(ng_by_batch) > 0:
            fig, ax = plt.subplots(figsize=(5, 4))
            ax.bar(
                ng_by_batch["batch"],
                ng_by_batch["不良数"],
                color="#E74C3C",
                edgecolor="white",
            )
            for i, row in ng_by_batch.iterrows():
                ax.text(
                    i, row["不良数"] + 0.3, str(row["不良数"]), ha="center", fontsize=9
                )
            ax.set_title("各批次不良数量", fontweight="bold")
            ax.set_xlabel("批次")
            ax.set_ylabel("不良数")
            ax.grid(axis="y", alpha=0.3)
            fig.tight_layout()
            st.pyplot(fig)
        else:
            st.info("无不良记录")


# ============================================================
# 页脚
# ============================================================
st.divider()
st.caption("光器件产线品质数据可视化分析 | Python + SQLite + SPC | 2026")
