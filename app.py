import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
from datetime import datetime
import math

from database import (
    init_db,
    create_scenario,
    get_scenario,
    list_scenarios,
    update_scenario,
    delete_scenario,
    copy_scenario,
    save_simulation_results,
    get_simulation_results,
)
from simulation import (
    SimulationParams,
    run_simulation,
    validate_tide_records,
    validate_mill_schedule,
    validate_manual_gate_schedule,
    estimate_mill_water_needs,
    parse_tide_csv,
    generate_default_tide_records,
    generate_default_mill_schedule,
    generate_multi_day_tide_records,
    validate_multi_day_tide_records,
    get_total_hours,
    compute_simulation_metrics,
    generate_daily_mill_schedule_for_multi_day,
)
from optimizer import (
    run_full_optimization,
    compare_optimization_targets,
    OptimizationResult,
)
from database import (
    save_optimization_run,
    get_optimization_runs,
    get_optimization_run_detail,
    delete_optimization_run,
)
from risk_assessment import (
    StormSurgeConfig,
    RainfallConfig,
    EquipmentFailureConfig,
    DisturbanceScenario,
    RiskAssessmentResult,
    EmergencyRecommendation,
    MonteCarloResult,
    run_disturbed_simulation,
    assess_risks,
    generate_disturbance_scenarios,
    generate_emergency_recommendations,
    compare_risk_scenarios,
    run_monte_carlo_risk_assessment,
    get_risk_level_color,
    get_risk_level_label,
)
from database import (
    create_strategy,
    save_strategy_simulation_data,
    save_strategy_risk_actions,
    list_strategies,
    get_strategy,
    update_strategy,
    delete_strategy,
    get_strategy_simulation_timeseries,
    compare_strategies_metrics,
)
from decision_review import (
    compare_strategies,
    build_timeline_analysis,
    generate_strategy_from_optimization,
    generate_strategy_from_manual,
    generate_risk_actions_from_recommendations,
    format_metric_value,
    get_metric_label,
    RiskAction,
)


st.set_page_config(
    page_title="历史潮汐磨坊调度模拟系统",
    page_icon="🌊",
    layout="wide",
)

init_db()


def format_hour(hour: float) -> str:
    h = int(hour)
    m = int((hour - h) * 60)
    return f"{h:02d}:{m:02d}"


def tide_records_to_dataframe(tide_records):
    df = pd.DataFrame(tide_records)
    if "time_index" in df.columns:
        df["time_hour"] = df["time_index"]
    return df


def load_scenario_to_state(scenario_id):
    scenario = get_scenario(scenario_id)
    if scenario:
        st.session_state["scenario_id"] = scenario_id
        st.session_state["scenario_name"] = scenario["name"]
        st.session_state["scenario_description"] = scenario["description"]
        st.session_state["reservoir_capacity"] = scenario["reservoir_capacity"]
        st.session_state["reservoir_area"] = scenario.get("reservoir_area", 20.0)
        st.session_state["gate_max_flow"] = scenario["gate_max_flow"]
        st.session_state["mill_power_consumption"] = scenario["mill_power_consumption"]
        st.session_state["initial_water_level"] = scenario["initial_water_level"]

        tide_records = scenario["tide_records"]
        if tide_records and "time_index" in tide_records[0]:
            for r in tide_records:
                r["time_hour"] = float(r["time_index"])
        st.session_state["tide_records"] = tide_records

        st.session_state["mill_schedule"] = scenario["mill_schedule"]
        st.session_state["needs_simulation"] = True


st.title("🌊 历史潮汐磨坊调度模拟系统")
st.markdown("基于每日潮位变化、蓄水池容量和磨坊运行需求，智能生成闸门开启建议")

with st.sidebar:
    st.header("📋 方案管理")

    scenarios = list_scenarios()

    if "selected_scenario_id" not in st.session_state:
        st.session_state["selected_scenario_id"] = None

    scenario_options = {s["id"]: s["name"] for s in scenarios}

    selected_id = st.selectbox(
        "选择方案",
        options=[None] + list(scenario_options.keys()),
        format_func=lambda x: "新建方案" if x is None else scenario_options[x],
        index=0 if st.session_state["selected_scenario_id"] is None else 
              list(scenario_options.keys()).index(st.session_state["selected_scenario_id"]) + 1 
              if st.session_state["selected_scenario_id"] in scenario_options else 0,
        key="scenario_selector",
    )

    if selected_id != st.session_state.get("selected_scenario_id"):
        if selected_id is not None:
            load_scenario_to_state(selected_id)
        else:
            st.session_state["scenario_id"] = None
            st.session_state["scenario_name"] = ""
            st.session_state["scenario_description"] = ""
            st.session_state["reservoir_capacity"] = 100.0
            st.session_state["reservoir_area"] = 20.0
            st.session_state["gate_max_flow"] = 50.0
            st.session_state["mill_power_consumption"] = 5.0
            st.session_state["initial_water_level"] = 50.0
            st.session_state["tide_records"] = generate_default_tide_records()
            st.session_state["mill_schedule"] = generate_default_mill_schedule()
            st.session_state["needs_simulation"] = True
        st.session_state["selected_scenario_id"] = selected_id

    col1, col2 = st.columns(2)
    with col1:
        if st.button("💾 保存方案", use_container_width=True):
            if "scenario_name" not in st.session_state or not st.session_state["scenario_name"]:
                st.error("请输入方案名称")
            else:
                tide_records = st.session_state.get("tide_records", [])
                valid, msg = validate_tide_records(tide_records)
                if not valid:
                    st.error(msg)
                else:
                    if st.session_state.get("scenario_id"):
                        update_scenario(
                            st.session_state["scenario_id"],
                            st.session_state["scenario_name"],
                            st.session_state.get("scenario_description", ""),
                            st.session_state["reservoir_capacity"],
                            st.session_state["reservoir_area"],
                            st.session_state["gate_max_flow"],
                            st.session_state["mill_power_consumption"],
                            st.session_state["initial_water_level"],
                            tide_records,
                            st.session_state.get("mill_schedule", []),
                        )
                        st.success("方案已更新")
                    else:
                        new_id = create_scenario(
                            st.session_state["scenario_name"],
                            st.session_state.get("scenario_description", ""),
                            st.session_state["reservoir_capacity"],
                            st.session_state["reservoir_area"],
                            st.session_state["gate_max_flow"],
                            st.session_state["mill_power_consumption"],
                            st.session_state["initial_water_level"],
                            tide_records,
                            st.session_state.get("mill_schedule", []),
                        )
                        st.session_state["scenario_id"] = new_id
                        st.session_state["selected_scenario_id"] = new_id
                        st.success(f"方案已创建，ID: {new_id}")
                    st.rerun()

    with col2:
        if st.button("📋 复制方案", use_container_width=True, 
                     disabled=st.session_state.get("scenario_id") is None):
            if st.session_state.get("scenario_id"):
                new_name = f"{st.session_state['scenario_name']} (副本)"
                new_id = copy_scenario(st.session_state["scenario_id"], new_name)
                load_scenario_to_state(new_id)
                st.session_state["selected_scenario_id"] = new_id
                st.success(f"方案已复制，新ID: {new_id}")
                st.rerun()

    if st.button("🗑️ 删除方案", use_container_width=True, 
                 disabled=st.session_state.get("scenario_id") is None):
        if st.session_state.get("scenario_id"):
            delete_scenario(st.session_state["scenario_id"])
            st.session_state["scenario_id"] = None
            st.session_state["selected_scenario_id"] = None
            st.success("方案已删除")
            st.rerun()

    st.divider()
    st.header("⚙️ 系统参数")

    if "reservoir_capacity" not in st.session_state:
        st.session_state["reservoir_capacity"] = 100.0
    if "reservoir_area" not in st.session_state:
        st.session_state["reservoir_area"] = 20.0
    if "gate_max_flow" not in st.session_state:
        st.session_state["gate_max_flow"] = 50.0
    if "mill_power_consumption" not in st.session_state:
        st.session_state["mill_power_consumption"] = 5.0
    if "initial_water_level" not in st.session_state:
        st.session_state["initial_water_level"] = 50.0

    reservoir_capacity = st.slider(
        "蓄水池容量 (m³)",
        min_value=10.0,
        max_value=500.0,
        value=st.session_state["reservoir_capacity"],
        step=5.0,
        key="reservoir_capacity_slider",
    )
    if reservoir_capacity != st.session_state["reservoir_capacity"]:
        st.session_state["reservoir_capacity"] = reservoir_capacity
        st.session_state["needs_simulation"] = True

    reservoir_area = st.slider(
        "蓄水池面积 (m²)",
        min_value=1.0,
        max_value=100.0,
        value=st.session_state["reservoir_area"],
        step=1.0,
        key="reservoir_area_slider",
    )
    if reservoir_area != st.session_state["reservoir_area"]:
        st.session_state["reservoir_area"] = reservoir_area
        st.session_state["needs_simulation"] = True

    gate_max_flow = st.slider(
        "闸门最大流量 (m³/h)",
        min_value=1.0,
        max_value=200.0,
        value=st.session_state["gate_max_flow"],
        step=1.0,
        key="gate_max_flow_slider",
    )
    if gate_max_flow != st.session_state["gate_max_flow"]:
        st.session_state["gate_max_flow"] = gate_max_flow
        st.session_state["needs_simulation"] = True

    mill_power_consumption = st.slider(
        "磨坊耗水量 (m³/h)",
        min_value=0.5,
        max_value=50.0,
        value=st.session_state["mill_power_consumption"],
        step=0.5,
        key="mill_power_consumption_slider",
    )
    if mill_power_consumption != st.session_state["mill_power_consumption"]:
        st.session_state["mill_power_consumption"] = mill_power_consumption
        st.session_state["needs_simulation"] = True

    initial_water_level = st.slider(
        "初始蓄水量 (m³)",
        min_value=0.0,
        max_value=st.session_state["reservoir_capacity"],
        value=min(st.session_state["initial_water_level"], st.session_state["reservoir_capacity"]),
        step=1.0,
        key="initial_water_level_slider",
    )
    if initial_water_level != st.session_state["initial_water_level"]:
        st.session_state["initial_water_level"] = initial_water_level
        st.session_state["needs_simulation"] = True


tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs(["📊 模拟结果", "🌊 潮位数据", "⚙️ 磨坊计划", "⚖️ 方案对比", "📅 多日优化排程", "⚠️ 风险预警决策", "📜 协同决策与方案复盘"])

with tab1:
    st.header("方案信息")

    col1, col2 = st.columns([2, 1])
    with col1:
        scenario_name = st.text_input(
            "方案名称",
            value=st.session_state.get("scenario_name", ""),
            key="scenario_name_input",
        )
        if scenario_name != st.session_state.get("scenario_name"):
            st.session_state["scenario_name"] = scenario_name

    with col2:
        st.metric(
            "当前蓄水量",
            f"{st.session_state.get('initial_water_level', 0):.1f} m³",
        )

    scenario_description = st.text_area(
        "方案描述",
        value=st.session_state.get("scenario_description", ""),
        height=60,
        key="scenario_desc_input",
    )
    if scenario_description != st.session_state.get("scenario_description"):
        st.session_state["scenario_description"] = scenario_description

    st.divider()

    try:
        params = SimulationParams(
            reservoir_capacity=st.session_state["reservoir_capacity"],
            reservoir_area=st.session_state["reservoir_area"],
            gate_max_flow=st.session_state["gate_max_flow"],
            mill_power_consumption=st.session_state["mill_power_consumption"],
            initial_water_level=st.session_state["initial_water_level"],
        )

        tide_records = st.session_state.get("tide_records", generate_default_tide_records())
        mill_schedule = st.session_state.get("mill_schedule", generate_default_mill_schedule())

        if "gate_mode" not in st.session_state:
            st.session_state["gate_mode"] = "auto"
        if "manual_gate_schedule" not in st.session_state:
            st.session_state["manual_gate_schedule"] = []

        col1, col2 = st.columns([1, 3])
        with col1:
            gate_mode = st.radio(
                "闸门控制模式",
                options=["auto", "manual"],
                format_func=lambda x: "🤖 自动调度" if x == "auto" else "✋ 手动控制",
                horizontal=True,
                key="gate_mode_radio",
            )
        with col2:
            st.write("")
            st.caption(
                "自动模式：系统根据潮位和蓄水量智能开关闸门 | "
                "手动模式：由您手动设置每个时段的闸门开启比例"
            )

        manual_gate = None
        if gate_mode == "manual":
            st.info("💡 手动设置闸门开启时段和比例。未设置的时段闸门默认关闭。")

            gate_df = pd.DataFrame(
                st.session_state["manual_gate_schedule"],
                columns=["start_hour", "end_hour", "open_ratio"],
            )

            edited_gate_df = st.data_editor(
                gate_df,
                num_rows="dynamic",
                use_container_width=True,
                column_config={
                    "start_hour": st.column_config.NumberColumn(
                        "开始时间 (小时)",
                        min_value=0,
                        max_value=24,
                        step=0.5,
                        format="%.1f",
                    ),
                    "end_hour": st.column_config.NumberColumn(
                        "结束时间 (小时)",
                        min_value=0,
                        max_value=24,
                        step=0.5,
                        format="%.1f",
                    ),
                    "open_ratio": st.column_config.NumberColumn(
                        "开启比例 (%)",
                        min_value=0,
                        max_value=100,
                        step=5,
                        format="%.0f",
                    ),
                },
            )

            preview_gate = edited_gate_df.to_dict("records")
            if preview_gate:
                valid_gate, gate_msg, gate_warns = validate_manual_gate_schedule(preview_gate)
                if not valid_gate:
                    st.error(f"❌ {gate_msg}")
                else:
                    if gate_warns:
                        for w in gate_warns:
                            st.warning(f"⚠️ {w}")
                    st.success("✅ 手动闸门计划有效")

            col_g1, col_g2 = st.columns(2)
            with col_g1:
                if st.button("✅ 更新手动闸门设置", use_container_width=True):
                    schedule = edited_gate_df.to_dict("records")
                    valid, msg, _ = validate_manual_gate_schedule(schedule)
                    if not valid:
                        st.error(msg)
                    else:
                        st.session_state["manual_gate_schedule"] = schedule
                        st.session_state["needs_simulation"] = True
                        st.success("手动闸门设置已更新")
                        st.rerun()
            with col_g2:
                if st.button("🔄 清空闸门设置", use_container_width=True):
                    st.session_state["manual_gate_schedule"] = []
                    st.session_state["needs_simulation"] = True
                    st.rerun()

            manual_gate = st.session_state["manual_gate_schedule"]

        if gate_mode != st.session_state.get("gate_mode"):
            st.session_state["gate_mode"] = gate_mode
            st.session_state["needs_simulation"] = True

        results, gate_schedule, warnings = run_simulation(
            params, tide_records, mill_schedule,
            manual_gate_schedule=manual_gate,
        )

        if st.session_state.get("scenario_id") and st.session_state.get("needs_simulation", True):
            save_simulation_results(st.session_state["scenario_id"], results, gate_schedule)
            st.session_state["needs_simulation"] = False

        if warnings:
            with st.expander(f"⚠️ 模拟警告 ({len(warnings)} 条)", expanded=False):
                for w in warnings:
                    st.warning(w)

        df_results = pd.DataFrame(results)

        st.subheader("📈 潮位与水位变化曲线")

        fig = make_subplots(
            rows=3,
            cols=1,
            shared_xaxes=True,
            vertical_spacing=0.08,
            subplot_titles=("潮位与蓄水池水位 (m)", "蓄水量 (m³)", "闸门开启比例 (%)"),
            row_heights=[0.4, 0.3, 0.3],
        )

        fig.add_trace(
            go.Scatter(
                x=df_results["time_hour"],
                y=df_results["tide_level"],
                name="潮位",
                line=dict(color="#1f77b4", width=2),
                fill="tozeroy",
                fillcolor="rgba(31, 119, 180, 0.15)",
            ),
            row=1,
            col=1,
        )

        fig.add_trace(
            go.Scatter(
                x=df_results["time_hour"],
                y=df_results["water_level"],
                name="蓄水池水位",
                line=dict(color="#ff7f0e", width=2),
                fill="tozeroy",
                fillcolor="rgba(255, 127, 14, 0.15)",
            ),
            row=1,
            col=1,
        )

        for i, sched in enumerate(mill_schedule):
            fig.add_vrect(
                x0=sched["start_hour"],
                x1=sched["end_hour"],
                fillcolor="green",
                opacity=0.12,
                layer="below",
                line_width=0,
                annotation_text=f"磨粉时段 {i+1}",
                annotation_position="top left",
                annotation_font_size=10,
                row=1,
                col=1,
            )

        fig.add_trace(
            go.Scatter(
                x=df_results["time_hour"],
                y=df_results["water_volume"],
                name="蓄水量",
                line=dict(color="#2ca02c", width=2),
                fill="tozeroy",
                fillcolor="rgba(44, 160, 44, 0.15)",
            ),
            row=2,
            col=1,
        )

        fig.add_hline(
            y=st.session_state["reservoir_capacity"],
            line_dash="dash",
            line_color="red",
            annotation_text="容量上限",
            annotation_position="right",
            row=2,
            col=1,
        )

        fig.add_trace(
            go.Scatter(
                x=df_results["time_hour"],
                y=df_results["gate_open_ratio"],
                name="闸门开启比例",
                line=dict(color="#9467bd", width=2),
                fill="tozeroy",
                fillcolor="rgba(148, 103, 189, 0.2)",
            ),
            row=3,
            col=1,
        )

        fig.update_layout(
            height=650,
            hovermode="x unified",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        )

        fig.update_xaxes(title_text="时间 (小时)", row=3, col=1)
        fig.update_yaxes(title_text="水位 (m)", row=1, col=1)
        fig.update_yaxes(title_text="蓄水量 (m³)", row=2, col=1)
        fig.update_yaxes(title_text="开启比例 (%)", row=3, col=1, range=[0, 105])

        st.plotly_chart(fig, use_container_width=True)

        st.subheader("🚪 闸门调度建议")

        col1, col2 = st.columns(2)
        with col1:
            st.metric(
                "建议开启时段数",
                len([g for g in gate_schedule if g["action"] == "开启"]),
            )
        with col2:
            total_open_hours = sum(
                g["end_hour"] - g["start_hour"]
                for g in gate_schedule
                if g["action"] == "开启"
            )
            st.metric("累计开启时长", f"{total_open_hours:.1f} 小时")

        if gate_schedule:
            schedule_data = []
            for g in gate_schedule:
                schedule_data.append(
                    {
                        "时段": f"{format_hour(g['start_hour'])} - {format_hour(g['end_hour'])}",
                        "时长 (小时)": round(g["end_hour"] - g["start_hour"], 1),
                        "操作": g["action"],
                        "开启比例 (%)": round(g["open_ratio"], 1),
                    }
                )

            st.dataframe(
                pd.DataFrame(schedule_data),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("暂无闸门调度建议")

        st.subheader("📊 关键指标")

        col1, col2, col3, col4 = st.columns(4)

        with col1:
            max_tide = df_results["tide_level"].max()
            st.metric("最高潮位", f"{max_tide:.2f} m")

        with col2:
            min_tide = df_results["tide_level"].min()
            st.metric("最低潮位", f"{min_tide:.2f} m")

        with col3:
            max_water = df_results["water_volume"].max()
            st.metric("最高蓄水量", f"{max_water:.1f} m³")

        with col4:
            min_water = df_results["water_volume"].min()
            st.metric("最低蓄水量", f"{min_water:.1f} m³")

        col1, col2 = st.columns(2)
        with col1:
            mill_hours = sum(1 for r in results if r["mill_running"]) * params.time_step_hours
            st.metric("磨坊实际运行时长", f"{mill_hours:.1f} 小时")

        with col2:
            capacity_utilization = (
                df_results["water_volume"].mean() / st.session_state["reservoir_capacity"] * 100
            )
            st.metric("平均库容利用率", f"{capacity_utilization:.1f} %")

    except Exception as e:
        st.error(f"模拟出错: {str(e)}")

with tab2:
    st.header("🌊 潮位数据管理")

    st.info("录入每日潮位时间序列数据。时间必须连续（从0到24小时），单位为小时。支持CSV文件上传。")

    if "tide_records" not in st.session_state:
        st.session_state["tide_records"] = generate_default_tide_records()

    uploaded_file = st.file_uploader(
        "📁 上传潮位 CSV 文件",
        type=["csv"],
        help="CSV文件应包含时间（小时）和潮位（米）两列，自动识别列名",
    )

    if uploaded_file is not None:
        try:
            csv_content = uploaded_file.getvalue().decode("utf-8")
            records, msg = parse_tide_csv(csv_content)
            if records:
                valid, valid_msg = validate_tide_records(records)
                if valid:
                    st.success(f"✅ {msg}")
                    if st.button("📥 导入此数据", use_container_width=True):
                        st.session_state["tide_records"] = records
                        st.session_state["needs_simulation"] = True
                        st.success("潮位数据已导入")
                        st.rerun()
                else:
                    st.error(f"❌ 数据验证失败: {valid_msg}")
                    st.write(f"解析到 {len(records)} 条记录")
            else:
                st.error(f"❌ {msg}")
        except Exception as e:
            st.error(f"文件读取失败: {e}")

    st.divider()

    tide_df = pd.DataFrame(st.session_state["tide_records"])
    if "time_index" in tide_df.columns:
        tide_df["time_hour"] = tide_df["time_index"]
        tide_df = tide_df[["time_hour", "tide_level"]]

    edited_df = st.data_editor(
        tide_df,
        num_rows="dynamic",
        use_container_width=True,
        column_config={
            "time_hour": st.column_config.NumberColumn(
                "时间 (小时)",
                min_value=0,
                max_value=24,
                step=0.5,
                format="%.1f",
            ),
            "tide_level": st.column_config.NumberColumn(
                "潮位 (m)",
                min_value=0,
                step=0.1,
                format="%.2f",
            ),
        },
    )

    preview_records = edited_df.to_dict("records")
    if preview_records:
        valid, msg = validate_tide_records(preview_records)
        if not valid:
            st.error(f"❌ {msg}")
        else:
            st.success(f"✅ {msg}")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("✅ 更新潮位数据", use_container_width=True):
            records = edited_df.to_dict("records")
            valid, msg = validate_tide_records(records)
            if not valid:
                st.error(msg)
            else:
                st.session_state["tide_records"] = records
                st.session_state["needs_simulation"] = True
                st.success("潮位数据已更新")
                st.rerun()

    with col2:
        if st.button("🔄 使用示例数据", use_container_width=True):
            st.session_state["tide_records"] = generate_default_tide_records()
            st.session_state["needs_simulation"] = True
            st.success("已加载示例潮位数据")
            st.rerun()

    st.subheader("潮位曲线预览")
    if len(edited_df) >= 2:
        preview_fig = go.Figure()
        preview_fig.add_trace(
            go.Scatter(
                x=edited_df["time_hour"],
                y=edited_df["tide_level"],
                mode="lines+markers",
                name="潮位",
                line=dict(color="#1f77b4", width=2),
                marker=dict(size=8),
            )
        )
        preview_fig.update_layout(
            xaxis_title="时间 (小时)",
            yaxis_title="潮位 (m)",
            height=300,
        )
        st.plotly_chart(preview_fig, use_container_width=True)

with tab3:
    st.header("⚙️ 磨坊运行计划")

    st.info("设置计划的磨粉时段。水位不足时，磨坊将无法运行。系统会检测时段重叠和水量风险。")

    if "mill_schedule" not in st.session_state:
        st.session_state["mill_schedule"] = generate_default_mill_schedule()

    mill_df = pd.DataFrame(st.session_state["mill_schedule"])

    edited_mill_df = st.data_editor(
        mill_df,
        num_rows="dynamic",
        use_container_width=True,
        column_config={
            "start_hour": st.column_config.NumberColumn(
                "开始时间 (小时)",
                min_value=0,
                max_value=24,
                step=0.5,
                format="%.1f",
            ),
            "end_hour": st.column_config.NumberColumn(
                "结束时间 (小时)",
                min_value=0,
                max_value=24,
                step=0.5,
                format="%.1f",
            ),
        },
    )

    preview_schedule = edited_mill_df.to_dict("records")
    if preview_schedule:
        valid, msg, warn_list = validate_mill_schedule(preview_schedule)
        if not valid:
            st.error(f"❌ {msg}")
        elif warn_list:
            for w in warn_list:
                st.warning(f"⚠️ {w}")

        total_water, water_warnings = estimate_mill_water_needs(
            preview_schedule,
            st.session_state.get("mill_power_consumption", 5.0),
            st.session_state.get("reservoir_capacity", 100.0),
        )
        if water_warnings:
            for w in water_warnings:
                st.warning(f"💧 {w}")
        st.info(f"📊 预计总耗水量: {total_water:.1f} m³")

    if st.button("✅ 更新磨坊计划", use_container_width=True):
        schedule = edited_mill_df.to_dict("records")
        valid, msg, _ = validate_mill_schedule(schedule)
        if not valid:
            st.error(msg)
        else:
            st.session_state["mill_schedule"] = schedule
            st.session_state["needs_simulation"] = True
            st.success("磨坊计划已更新")
            st.rerun()

    st.divider()
    st.subheader("磨坊计划预览")

    if not edited_mill_df.empty:
        total_hours = sum(
            row["end_hour"] - row["start_hour"]
            for _, row in edited_mill_df.iterrows()
        )
        st.metric("计划总运行时长", f"{total_hours:.1f} 小时")

        timeline_fig = go.Figure()
        for i, row in edited_mill_df.iterrows():
            timeline_fig.add_trace(
                go.Bar(
                    x=[row["end_hour"] - row["start_hour"]],
                    y=["磨坊运行"],
                    base=[row["start_hour"]],
                    orientation="h",
                    name=f"时段 {i+1}",
                    marker_color="green",
                    opacity=0.7,
                    hovertext=f"{format_hour(row['start_hour'])} - {format_hour(row['end_hour'])}",
                )
            )
        timeline_fig.update_layout(
            xaxis_title="时间 (小时)",
            xaxis_range=[0, 24],
            height=150,
            showlegend=False,
            barmode="stack",
        )
        st.plotly_chart(timeline_fig, use_container_width=True)

with tab4:
    st.header("⚖️ 方案对比")

    st.info("选择两个方案进行对比分析，查看不同参数对调度结果的影响。")

    all_scenarios = list_scenarios()
    scenario_dict = {s["id"]: s["name"] for s in all_scenarios}

    col1, col2 = st.columns(2)
    with col1:
        compare_id_1 = st.selectbox(
            "方案 A",
            options=list(scenario_dict.keys()),
            format_func=lambda x: scenario_dict[x],
            key="compare_scenario_1",
        )
    with col2:
        compare_id_2 = st.selectbox(
            "方案 B",
            options=list(scenario_dict.keys()),
            format_func=lambda x: scenario_dict[x],
            key="compare_scenario_2",
        )

    if compare_id_1 and compare_id_2 and st.button("🔍 开始对比", use_container_width=True):
        if compare_id_1 == compare_id_2:
            st.warning("请选择两个不同的方案进行对比")
        else:
            s1 = get_scenario(compare_id_1)
            s2 = get_scenario(compare_id_2)

            if s1 and s2:
                results_1, gate_1, _ = run_simulation(
                    SimulationParams(
                        reservoir_capacity=s1["reservoir_capacity"],
                        reservoir_area=s1.get("reservoir_area", 20.0),
                        gate_max_flow=s1["gate_max_flow"],
                        mill_power_consumption=s1["mill_power_consumption"],
                        initial_water_level=s1["initial_water_level"],
                    ),
                    s1["tide_records"],
                    s1["mill_schedule"],
                )
                results_2, gate_2, _ = run_simulation(
                    SimulationParams(
                        reservoir_capacity=s2["reservoir_capacity"],
                        reservoir_area=s2.get("reservoir_area", 20.0),
                        gate_max_flow=s2["gate_max_flow"],
                        mill_power_consumption=s2["mill_power_consumption"],
                        initial_water_level=s2["initial_water_level"],
                    ),
                    s2["tide_records"],
                    s2["mill_schedule"],
                )

                df1 = pd.DataFrame(results_1)
                df2 = pd.DataFrame(results_2)

                st.subheader("📈 蓄水量对比曲线")

                compare_fig = make_subplots(
                    rows=3,
                    cols=1,
                    shared_xaxes=True,
                    vertical_spacing=0.08,
                    subplot_titles=("潮位与水位对比 (m)", "蓄水量对比 (m³)", "闸门开启比例对比 (%)"),
                    row_heights=[0.35, 0.35, 0.3],
                )

                compare_fig.add_trace(
                    go.Scatter(
                        x=df1["time_hour"],
                        y=df1["tide_level"],
                        name=f"A: {s1['name']} 潮位",
                        line=dict(color="#1f77b4", width=2, dash="dash"),
                    ),
                    row=1,
                    col=1,
                )
                compare_fig.add_trace(
                    go.Scatter(
                        x=df1["time_hour"],
                        y=df1["water_level"],
                        name=f"A: {s1['name']} 水位",
                        line=dict(color="#1f77b4", width=2),
                    ),
                    row=1,
                    col=1,
                )
                compare_fig.add_trace(
                    go.Scatter(
                        x=df2["time_hour"],
                        y=df2["tide_level"],
                        name=f"B: {s2['name']} 潮位",
                        line=dict(color="#ff7f0e", width=2, dash="dash"),
                    ),
                    row=1,
                    col=1,
                )
                compare_fig.add_trace(
                    go.Scatter(
                        x=df2["time_hour"],
                        y=df2["water_level"],
                        name=f"B: {s2['name']} 水位",
                        line=dict(color="#ff7f0e", width=2),
                    ),
                    row=1,
                    col=1,
                )

                compare_fig.add_trace(
                    go.Scatter(
                        x=df1["time_hour"],
                        y=df1["water_volume"],
                        name=f"A: {s1['name']} 蓄水量",
                        line=dict(color="#1f77b4", width=2),
                    ),
                    row=2,
                    col=1,
                )
                compare_fig.add_trace(
                    go.Scatter(
                        x=df2["time_hour"],
                        y=df2["water_volume"],
                        name=f"B: {s2['name']} 蓄水量",
                        line=dict(color="#ff7f0e", width=2),
                    ),
                    row=2,
                    col=1,
                )

                compare_fig.add_trace(
                    go.Scatter(
                        x=df1["time_hour"],
                        y=df1["gate_open_ratio"],
                        name=f"A: {s1['name']} 闸门",
                        line=dict(color="#2ca02c", width=2),
                    ),
                    row=3,
                    col=1,
                )
                compare_fig.add_trace(
                    go.Scatter(
                        x=df2["time_hour"],
                        y=df2["gate_open_ratio"],
                        name=f"B: {s2['name']} 闸门",
                        line=dict(color="#d62728", width=2),
                    ),
                    row=3,
                    col=1,
                )

                compare_fig.update_layout(
                    height=700,
                    hovermode="x unified",
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                )
                compare_fig.update_xaxes(title_text="时间 (小时)", row=3, col=1)
                compare_fig.update_yaxes(title_text="水位 (m)", row=1, col=1)
                compare_fig.update_yaxes(title_text="蓄水量 (m³)", row=2, col=1)
                compare_fig.update_yaxes(title_text="开启比例 (%)", row=3, col=1, range=[0, 105])

                st.plotly_chart(compare_fig, use_container_width=True)

                st.subheader("📊 参数与指标对比")

                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("方案 A", s1["name"])
                with col2:
                    st.metric("方案 B", s2["name"])
                with col3:
                    diff = s1["reservoir_capacity"] - s2["reservoir_capacity"]
                    st.metric("容量差", f"{diff:+.1f} m³")

                compare_data = [
                    {
                        "指标": "蓄水池容量 (m³)",
                        f"方案 A: {s1['name']}": s1["reservoir_capacity"],
                        f"方案 B: {s2['name']}": s2["reservoir_capacity"],
                        "差异": round(s1["reservoir_capacity"] - s2["reservoir_capacity"], 2),
                    },
                    {
                        "指标": "蓄水池面积 (m²)",
                        f"方案 A: {s1['name']}": s1.get("reservoir_area", 20.0),
                        f"方案 B: {s2['name']}": s2.get("reservoir_area", 20.0),
                        "差异": round(s1.get("reservoir_area", 20.0) - s2.get("reservoir_area", 20.0), 2),
                    },
                    {
                        "指标": "闸门最大流量 (m³/h)",
                        f"方案 A: {s1['name']}": s1["gate_max_flow"],
                        f"方案 B: {s2['name']}": s2["gate_max_flow"],
                        "差异": round(s1["gate_max_flow"] - s2["gate_max_flow"], 2),
                    },
                    {
                        "指标": "磨坊耗水量 (m³/h)",
                        f"方案 A: {s1['name']}": s1["mill_power_consumption"],
                        f"方案 B: {s2['name']}": s2["mill_power_consumption"],
                        "差异": round(s1["mill_power_consumption"] - s2["mill_power_consumption"], 2),
                    },
                    {
                        "指标": "初始蓄水量 (m³)",
                        f"方案 A: {s1['name']}": s1["initial_water_level"],
                        f"方案 B: {s2['name']}": s2["initial_water_level"],
                        "差异": round(s1["initial_water_level"] - s2["initial_water_level"], 2),
                    },
                    {
                        "指标": "最高蓄水量 (m³)",
                        f"方案 A: {s1['name']}": round(df1["water_volume"].max(), 2),
                        f"方案 B: {s2['name']}": round(df2["water_volume"].max(), 2),
                        "差异": round(df1["water_volume"].max() - df2["water_volume"].max(), 2),
                    },
                    {
                        "指标": "最低蓄水量 (m³)",
                        f"方案 A: {s1['name']}": round(df1["water_volume"].min(), 2),
                        f"方案 B: {s2['name']}": round(df2["water_volume"].min(), 2),
                        "差异": round(df1["water_volume"].min() - df2["water_volume"].min(), 2),
                    },
                    {
                        "指标": "平均蓄水量 (m³)",
                        f"方案 A: {s1['name']}": round(df1["water_volume"].mean(), 2),
                        f"方案 B: {s2['name']}": round(df2["water_volume"].mean(), 2),
                        "差异": round(df1["water_volume"].mean() - df2["water_volume"].mean(), 2),
                    },
                    {
                        "指标": "闸门开启时段数",
                        f"方案 A: {s1['name']}": len([g for g in gate_1 if g["action"] == "开启"]),
                        f"方案 B: {s2['name']}": len([g for g in gate_2 if g["action"] == "开启"]),
                        "差异": len([g for g in gate_1 if g["action"] == "开启"]) - len([g for g in gate_2 if g["action"] == "开启"]),
                    },
                    {
                        "指标": "累计开启时长 (小时)",
                        f"方案 A: {s1['name']}": round(sum(g["end_hour"] - g["start_hour"] for g in gate_1 if g["action"] == "开启"), 2),
                        f"方案 B: {s2['name']}": round(sum(g["end_hour"] - g["start_hour"] for g in gate_2 if g["action"] == "开启"), 2),
                        "差异": round(
                            sum(g["end_hour"] - g["start_hour"] for g in gate_1 if g["action"] == "开启") -
                            sum(g["end_hour"] - g["start_hour"] for g in gate_2 if g["action"] == "开启"),
                            2,
                        ),
                    },
                ]

                st.dataframe(pd.DataFrame(compare_data), use_container_width=True, hide_index=True)

                st.subheader("📋 闸门调度建议对比")

                col1, col2 = st.columns(2)
                with col1:
                    st.write(f"**方案 A: {s1['name']}**")
                    if gate_1:
                        gate1_data = [
                            {
                                "时段": f"{format_hour(g['start_hour'])} - {format_hour(g['end_hour'])}",
                                "操作": g["action"],
                                "比例 (%)": round(g["open_ratio"], 1),
                            }
                            for g in gate_1
                        ]
                        st.dataframe(pd.DataFrame(gate1_data), use_container_width=True, hide_index=True)
                    else:
                        st.info("无闸门调度建议")

                with col2:
                    st.write(f"**方案 B: {s2['name']}**")
                    if gate_2:
                        gate2_data = [
                            {
                                "时段": f"{format_hour(g['start_hour'])} - {format_hour(g['end_hour'])}",
                                "操作": g["action"],
                                "比例 (%)": round(g["open_ratio"], 1),
                            }
                            for g in gate_2
                        ]
                        st.dataframe(pd.DataFrame(gate2_data), use_container_width=True, hide_index=True)
                    else:
                        st.info("无闸门调度建议")
            else:
                st.error("无法加载方案数据")

with tab5:
    st.header("📅 多日潮汐预测与自动优化排程")
    st.markdown("导入连续多天潮位数据，自动计算最优闸门开闭与磨坊运行时段，支持多种优化目标")

    if "multi_day_tide_records" not in st.session_state:
        st.session_state["multi_day_tide_records"] = generate_multi_day_tide_records(num_days=7)
    if "optimization_target" not in st.session_state:
        st.session_state["optimization_target"] = "balanced"
    if "optimization_days" not in st.session_state:
        st.session_state["optimization_days"] = 7
    if "daily_target_hours" not in st.session_state:
        st.session_state["daily_target_hours"] = 8.0
    if "optimization_results" not in st.session_state:
        st.session_state["optimization_results"] = None
    if "compare_results" not in st.session_state:
        st.session_state["compare_results"] = None
    if "is_sample_data" not in st.session_state:
        st.session_state["is_sample_data"] = True

    st.subheader("📊 多日潮位数据")

    col1, col2 = st.columns([2, 1])
    with col1:
        is_sample = st.session_state.get("is_sample_data", True)
        slider_label = "预测天数" if is_sample else "数据天数（由上传数据决定）"
        num_days_input = st.slider(
            slider_label,
            min_value=1,
            max_value=30,
            value=st.session_state["optimization_days"],
            step=1,
            disabled=not is_sample,
            key="opt_days_slider",
            help="示例数据模式下可调整天数，上传数据模式下由数据实际覆盖天数" if not is_sample else "调整后自动重新生成对应天数的示例数据",
        )
    with col2:
        st.write("")
        st.write("")
        sample_label = "📊 示例数据" if is_sample else "📁 已上传数据"
        st.caption(f"数据来源：{sample_label}")
        if not is_sample:
            actual_days_display = get_total_hours(st.session_state["multi_day_tide_records"]) / 24
            st.caption(f"实际覆盖：{actual_days_display:.2f} 天")

    if is_sample and num_days_input != st.session_state["optimization_days"]:
        st.session_state["optimization_days"] = num_days_input
        st.session_state["multi_day_tide_records"] = generate_multi_day_tide_records(num_days=num_days_input)
        st.session_state["optimization_results"] = None
        st.session_state["compare_results"] = None
        st.rerun()

    if st.button("🔄 重新生成示例数据", use_container_width=True, key="gen_multi_day"):
        st.session_state["multi_day_tide_records"] = generate_multi_day_tide_records(num_days=num_days_input)
        st.session_state["optimization_days"] = num_days_input
        st.session_state["is_sample_data"] = True
        st.session_state["optimization_results"] = None
        st.session_state["compare_results"] = None
        st.success(f"已重新生成 {num_days_input} 天示例潮位数据")
        st.rerun()

    uploaded_multi_file = st.file_uploader(
        "📁 上传多日潮位 CSV 文件",
        type=["csv"],
        help="CSV文件应包含时间（小时，从0开始）和潮位（米）两列，支持多天连续数据",
        key="multi_day_upload",
    )

    if uploaded_multi_file is not None:
        try:
            csv_content = uploaded_multi_file.getvalue().decode("utf-8")
            records, msg = parse_tide_csv(csv_content)
            if records:
                valid, valid_msg = validate_multi_day_tide_records(records, min_hours=24.0)
                if valid:
                    st.success(f"✅ {msg} - {valid_msg}")
                    if st.button("📥 导入此数据", use_container_width=True, key="import_multi_day"):
                        st.session_state["multi_day_tide_records"] = records
                        total_hours = get_total_hours(records)
                        actual_days = total_hours / 24
                        st.session_state["optimization_days"] = round(actual_days)
                        st.session_state["is_sample_data"] = False
                        st.session_state["optimization_results"] = None
                        st.session_state["compare_results"] = None
                        st.success(f"多日潮位数据已导入，覆盖 {actual_days:.2f} 天")
                        st.rerun()
                else:
                    st.error(f"❌ 数据验证失败: {valid_msg}")
                    st.write(f"解析到 {len(records)} 条记录")
            else:
                st.error(f"❌ {msg}")
        except Exception as e:
            st.error(f"文件读取失败: {e}")

    tide_multi_df = pd.DataFrame(st.session_state["multi_day_tide_records"])

    with st.expander("📋 查看潮位数据明细", expanded=False):
        st.dataframe(tide_multi_df, use_container_width=True, height=200)

    total_hours = get_total_hours(st.session_state["multi_day_tide_records"])
    actual_days = total_hours / 24

    if st.session_state.get("is_sample_data", True):
        st.info(f"📊 当前为示例数据，覆盖 {total_hours:.1f} 小时 ({actual_days:.1f} 天)，共 {len(tide_multi_df)} 条记录")
    else:
        days_int = int(actual_days)
        hours_remain = round((actual_days - days_int) * 24, 1)
        st.info(f"📊 当前为上传数据，覆盖 {total_hours:.1f} 小时 ({days_int}天{hours_remain}小时)，共 {len(tide_multi_df)} 条记录")

    preview_fig = go.Figure()
    preview_fig.add_trace(
        go.Scatter(
            x=tide_multi_df["time_hour"],
            y=tide_multi_df["tide_level"],
            mode="lines",
            name="潮位",
            line=dict(color="#1f77b4", width=2),
            fill="tozeroy",
            fillcolor="rgba(31, 119, 180, 0.15)",
        )
    )
    preview_fig.update_layout(
        xaxis_title="时间 (小时)",
        yaxis_title="潮位 (m)",
        height=300,
        hovermode="x unified",
    )
    st.plotly_chart(preview_fig, use_container_width=True)

    st.divider()

    st.subheader("🎯 优化目标设置")

    target_options = {
        "water_saving": "💧 节水模式 - 优先保持高水位，减少闸门开启",
        "high_yield": "⚡ 高产模式 - 优先延长磨坊运行时间",
        "low_overflow": "🌊 低溢流模式 - 优先减少蓄水池溢流",
        "balanced": "⚖️ 均衡模式 - 综合平衡各指标",
    }

    col_t1, col_t2 = st.columns([2, 1])
    with col_t1:
        selected_target = st.selectbox(
            "选择优化目标",
            options=list(target_options.keys()),
            format_func=lambda x: target_options[x],
            index=list(target_options.keys()).index(st.session_state["optimization_target"])
            if st.session_state["optimization_target"] in target_options else 3,
            key="opt_target_select",
        )
    with col_t2:
        daily_hours = st.slider(
            "日均目标工时 (h)",
            min_value=2.0,
            max_value=16.0,
            value=st.session_state["daily_target_hours"],
            step=0.5,
            key="daily_hours_slider",
        )

    target_descriptions = {
        "water_saving": "节水模式适合水资源紧张的场景，策略是尽量减少闸门开启次数和时间，保持蓄水池高水位，优先保障关键时段的磨粉需求。",
        "high_yield": "高产模式适合需要最大化产量的场景，策略是尽可能延长磨坊运行时间，充分利用潮汐周期补水，以产量最大化为首要目标。",
        "low_overflow": "低溢流模式适合需要减少水资源浪费的场景，策略是精确控制闸门开闭时机，避免蓄水池满溢，提高水资源利用效率。",
        "balanced": "均衡模式综合考虑产量、水位和溢流等多个因素，在各指标之间寻求最佳平衡点，适合大多数常规场景。",
    }

    st.info(f"💡 {target_descriptions.get(selected_target, '')}")

    if st.button("🚀 开始优化计算", use_container_width=True, type="primary", key="run_optimization"):
        with st.spinner("正在进行优化计算，请稍候..."):
            try:
                params = SimulationParams(
                    reservoir_capacity=st.session_state["reservoir_capacity"],
                    reservoir_area=st.session_state["reservoir_area"],
                    gate_max_flow=st.session_state["gate_max_flow"],
                    mill_power_consumption=st.session_state["mill_power_consumption"],
                    initial_water_level=st.session_state["initial_water_level"],
                )

                tide_data = st.session_state["multi_day_tide_records"]
                actual_total_hours = get_total_hours(tide_data)
                effective_days = max(1, int(math.ceil(actual_total_hours / 24)))

                result = run_full_optimization(
                    params,
                    tide_data,
                    target=selected_target,
                    num_days=effective_days,
                    daily_mill_hours=daily_hours,
                )

                st.session_state["optimization_results"] = result
                st.session_state["optimization_target"] = selected_target
                st.session_state["daily_target_hours"] = daily_hours
                st.success("✅ 优化计算完成!")
            except Exception as e:
                st.error(f"优化计算失败: {e}")
                import traceback
                traceback.print_exc()

    st.divider()

    if st.session_state["optimization_results"] is not None:
        opt_result = st.session_state["optimization_results"]
        metrics = opt_result.metrics

        st.subheader("📈 优化结果")

        target_names = {
            "water_saving": "💧 节水模式",
            "high_yield": "⚡ 高产模式",
            "low_overflow": "🌊 低溢流模式",
            "balanced": "⚖️ 均衡模式",
        }

        st.metric("优化目标", target_names.get(opt_result.target, opt_result.target))

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric(
                "磨坊总运行时长",
                f"{metrics.get('total_mill_hours', 0):.1f} h",
                f"日均 {metrics.get('total_mill_hours', 0)/max(1, metrics.get('num_days', 1)):.1f} h",
            )
        with col2:
            st.metric(
                "闸门累计开启",
                f"{metrics.get('total_gate_open_hours', 0):.1f} h",
            )
        with col3:
            st.metric(
                "溢流水量",
                f"{metrics.get('overflow_volume', 0):.1f} m³",
            )
        with col4:
            st.metric(
                "平均库容利用率",
                f"{metrics.get('capacity_utilization_pct', 0):.1f} %",
            )

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("最高蓄水量", f"{metrics.get('max_water_volume', 0):.1f} m³")
        with col2:
            st.metric("最低蓄水量", f"{metrics.get('min_water_volume', 0):.1f} m³")
        with col3:
            st.metric("总补水量", f"{metrics.get('total_inflow', 0):.1f} m³")
        with col4:
            st.metric("优化评分", f"{opt_result.score:.1f}")

        df_opt = pd.DataFrame(opt_result.simulation_results)

        st.subheader("📊 多日水位变化曲线")

        fig = make_subplots(
            rows=3,
            cols=1,
            shared_xaxes=True,
            vertical_spacing=0.08,
            subplot_titles=("潮位与蓄水池水位 (m)", "蓄水量 (m³)", "闸门开启比例 (%)"),
            row_heights=[0.4, 0.3, 0.3],
        )

        fig.add_trace(
            go.Scatter(
                x=df_opt["time_hour"] / 24,
                y=df_opt["tide_level"],
                name="潮位",
                line=dict(color="#1f77b4", width=2),
                fill="tozeroy",
                fillcolor="rgba(31, 119, 180, 0.1)",
            ),
            row=1,
            col=1,
        )

        fig.add_trace(
            go.Scatter(
                x=df_opt["time_hour"] / 24,
                y=df_opt["water_level"],
                name="蓄水池水位",
                line=dict(color="#ff7f0e", width=2),
                fill="tozeroy",
                fillcolor="rgba(255, 127, 14, 0.1)",
            ),
            row=1,
            col=1,
        )

        for i, sched in enumerate(opt_result.mill_schedule):
            if i == 0:
                show_legend = True
            else:
                show_legend = False
            fig.add_vrect(
                x0=sched["start_hour"] / 24,
                x1=sched["end_hour"] / 24,
                fillcolor="green",
                opacity=0.12,
                layer="below",
                line_width=0,
                row=1,
                col=1,
            )

        fig.add_trace(
            go.Scatter(
                x=df_opt["time_hour"] / 24,
                y=df_opt["water_volume"],
                name="蓄水量",
                line=dict(color="#2ca02c", width=2),
                fill="tozeroy",
                fillcolor="rgba(44, 160, 44, 0.1)",
            ),
            row=2,
            col=1,
        )

        fig.add_hline(
            y=st.session_state["reservoir_capacity"],
            line_dash="dash",
            line_color="red",
            annotation_text="容量上限",
            annotation_position="right",
            row=2,
            col=1,
        )

        fig.add_trace(
            go.Scatter(
                x=df_opt["time_hour"] / 24,
                y=df_opt["gate_open_ratio"],
                name="闸门开启比例",
                line=dict(color="#9467bd", width=2),
                fill="tozeroy",
                fillcolor="rgba(148, 103, 189, 0.15)",
            ),
            row=3,
            col=1,
        )

        fig.update_layout(
            height=650,
            hovermode="x unified",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        )

        fig.update_xaxes(title_text="时间 (天)", row=3, col=1)
        fig.update_yaxes(title_text="水位 (m)", row=1, col=1)
        fig.update_yaxes(title_text="蓄水量 (m³)", row=2, col=1)
        fig.update_yaxes(title_text="开启比例 (%)", row=3, col=1, range=[0, 105])

        st.plotly_chart(fig, use_container_width=True)

        st.subheader("🚪 优化闸门调度建议")

        if opt_result.gate_schedule:
            gate_data = []
            for g in opt_result.gate_schedule:
                start_day = g["start_hour"] / 24
                end_day = g["end_hour"] / 24
                gate_data.append({
                    "开始": f"第{start_day:.2f}天 ({format_hour(g['start_hour'] % 24)})",
                    "结束": f"第{end_day:.2f}天 ({format_hour(g['end_hour'] % 24)})",
                    "时长 (h)": round(g["end_hour"] - g["start_hour"], 1),
                    "操作": g["action"],
                    "开启比例 (%)": round(g["open_ratio"], 1),
                })
            st.dataframe(pd.DataFrame(gate_data), use_container_width=True, hide_index=True)
        else:
            st.info("暂无闸门调度建议")

        st.subheader("⚙️ 优化磨坊运行计划")

        if opt_result.mill_schedule:
            mill_data = []
            for i, s in enumerate(opt_result.mill_schedule):
                day = int(s["start_hour"] / 24) + 1
                mill_data.append({
                    "时段序号": i + 1,
                    "日期": f"第 {day} 天",
                    "开始时间": format_hour(s["start_hour"] % 24),
                    "结束时间": format_hour(s["end_hour"] % 24),
                    "时长 (h)": round(s["end_hour"] - s["start_hour"], 1),
                })
            st.dataframe(pd.DataFrame(mill_data), use_container_width=True, hide_index=True)

            total_mill_time = sum(s["end_hour"] - s["start_hour"] for s in opt_result.mill_schedule)
            st.caption(f"总计 {len(opt_result.mill_schedule)} 个磨粉时段，累计运行 {total_mill_time:.1f} 小时")

        st.divider()

        col_save1, col_save2, col_save3 = st.columns(3)
        with col_save1:
            if st.button("💾 保存优化结果", use_container_width=True, key="save_opt_result"):
                if st.session_state.get("scenario_id"):
                    run_id = save_optimization_run(
                        st.session_state["scenario_id"],
                        opt_result.target,
                        st.session_state["optimization_days"],
                        st.session_state["daily_target_hours"],
                        opt_result.score,
                        opt_result.metrics,
                        opt_result.mill_schedule,
                        opt_result.gate_schedule,
                    )
                    st.success(f"优化结果已保存，ID: {run_id}")
                else:
                    st.warning("请先保存方案，再保存优化结果")

        with col_save2:
            if st.button("🔍 四种目标对比", use_container_width=True, key="compare_all_targets"):
                with st.spinner("正在计算四种优化目标的对比结果..."):
                    try:
                        params = SimulationParams(
                            reservoir_capacity=st.session_state["reservoir_capacity"],
                            reservoir_area=st.session_state["reservoir_area"],
                            gate_max_flow=st.session_state["gate_max_flow"],
                            mill_power_consumption=st.session_state["mill_power_consumption"],
                            initial_water_level=st.session_state["initial_water_level"],
                        )

                        tide_data = st.session_state["multi_day_tide_records"]
                        actual_total_hours = get_total_hours(tide_data)
                        effective_days = max(1, int(math.ceil(actual_total_hours / 24)))

                        compare_results = compare_optimization_targets(
                            params,
                            tide_data,
                            num_days=effective_days,
                            daily_mill_hours=daily_hours,
                        )
                        st.session_state["compare_results"] = compare_results
                        st.success("✅ 四种目标对比计算完成!")
                    except Exception as e:
                        st.error(f"对比计算失败: {e}")

        with col_save3:
            if st.button("🔄 清除结果", use_container_width=True, key="clear_opt_result"):
                st.session_state["optimization_results"] = None
                st.session_state["compare_results"] = None
                st.rerun()

    if st.session_state.get("compare_results") is not None and len(st.session_state["compare_results"]) > 0:
        st.divider()
        st.subheader("📊 四种优化策略对比分析")

        compare_results = st.session_state["compare_results"]

        target_display = {
            "water_saving": "💧 节水",
            "high_yield": "⚡ 高产",
            "low_overflow": "🌊 低溢流",
            "balanced": "⚖️ 均衡",
        }

        compare_metrics = []
        for res in compare_results:
            m = res.metrics
            compare_metrics.append({
                "优化目标": target_display.get(res.target, res.target),
                "磨坊总时长 (h)": m.get("total_mill_hours", 0),
                "闸门开启 (h)": m.get("total_gate_open_hours", 0),
                "溢流水量 (m³)": m.get("overflow_volume", 0),
                "平均库容 (%)": m.get("capacity_utilization_pct", 0),
                "总补水 (m³)": m.get("total_inflow", 0),
                "优化评分": res.score,
            })

        st.dataframe(pd.DataFrame(compare_metrics), use_container_width=True, hide_index=True)

        st.subheader("📈 关键指标对比")

        col1, col2, col3 = st.columns(3)

        with col1:
            bar_fig1 = go.Figure()
            bar_fig1.add_trace(go.Bar(
                x=[target_display.get(r.target, r.target) for r in compare_results],
                y=[r.metrics.get("total_mill_hours", 0) for r in compare_results],
                name="磨坊运行时长 (h)",
                marker_color="#2ca02c",
            ))
            bar_fig1.update_layout(
                title="磨坊运行时长对比",
                height=300,
            )
            st.plotly_chart(bar_fig1, use_container_width=True)

        with col2:
            bar_fig2 = go.Figure()
            bar_fig2.add_trace(go.Bar(
                x=[target_display.get(r.target, r.target) for r in compare_results],
                y=[r.metrics.get("overflow_volume", 0) for r in compare_results],
                name="溢流水量 (m³)",
                marker_color="#d62728",
            ))
            bar_fig2.update_layout(
                title="溢流水量对比",
                height=300,
            )
            st.plotly_chart(bar_fig2, use_container_width=True)

        with col3:
            bar_fig3 = go.Figure()
            bar_fig3.add_trace(go.Bar(
                x=[target_display.get(r.target, r.target) for r in compare_results],
                y=[r.metrics.get("capacity_utilization_pct", 0) for r in compare_results],
                name="平均库容利用率 (%)",
                marker_color="#ff7f0e",
            ))
            bar_fig3.update_layout(
                title="平均库容利用率对比",
                height=300,
            )
            st.plotly_chart(bar_fig3, use_container_width=True)

        st.subheader("📉 水位变化对比")

        compare_fig = make_subplots(
            rows=2,
            cols=1,
            shared_xaxes=True,
            vertical_spacing=0.08,
            subplot_titles=("蓄水量对比 (m³)", "闸门开启比例对比 (%)"),
            row_heights=[0.6, 0.4],
        )

        colors = ["#1f77b4", "#ff7f0e", "#2ca02c", "#9467bd"]

        for i, res in enumerate(compare_results):
            df_res = pd.DataFrame(res.simulation_results)
            compare_fig.add_trace(
                go.Scatter(
                    x=df_res["time_hour"] / 24,
                    y=df_res["water_volume"],
                    name=f"{target_display.get(res.target, res.target)} 蓄水量",
                    line=dict(color=colors[i % len(colors)], width=2),
                ),
                row=1,
                col=1,
            )

        compare_fig.add_hline(
            y=st.session_state["reservoir_capacity"],
            line_dash="dash",
            line_color="red",
            annotation_text="容量上限",
            annotation_position="right",
            row=1,
            col=1,
        )

        for i, res in enumerate(compare_results):
            df_res = pd.DataFrame(res.simulation_results)
            compare_fig.add_trace(
                go.Scatter(
                    x=df_res["time_hour"] / 24,
                    y=df_res["gate_open_ratio"],
                    name=f"{target_display.get(res.target, res.target)} 闸门",
                    line=dict(color=colors[i % len(colors)], width=2),
                ),
                row=2,
                col=1,
            )

        compare_fig.update_layout(
            height=550,
            hovermode="x unified",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        )
        compare_fig.update_xaxes(title_text="时间 (天)", row=2, col=1)
        compare_fig.update_yaxes(title_text="蓄水量 (m³)", row=1, col=1)
        compare_fig.update_yaxes(title_text="开启比例 (%)", row=2, col=1, range=[0, 105])

        st.plotly_chart(compare_fig, use_container_width=True)

        st.subheader("📋 各策略闸门调度对比")

        for res in compare_results:
            with st.expander(f"{target_display.get(res.target, res.target)} 模式 - 闸门调度详情", expanded=False):
                if res.gate_schedule:
                    gate_detail = []
                    for g in res.gate_schedule:
                        gate_detail.append({
                            "开始时间": format_hour(g["start_hour"]),
                            "结束时间": format_hour(g["end_hour"]),
                            "时长 (h)": round(g["end_hour"] - g["start_hour"], 1),
                            "操作": g["action"],
                            "比例 (%)": round(g["open_ratio"], 1),
                        })
                    st.dataframe(pd.DataFrame(gate_detail), use_container_width=True, hide_index=True)

        if st.session_state.get("scenario_id"):
            st.divider()
            st.subheader("📚 历史优化记录")

            opt_runs = get_optimization_runs(st.session_state["scenario_id"])
            if opt_runs:
                st.info(f"共有 {len(opt_runs)} 条历史优化记录")

                runs_data = []
                for run in opt_runs:
                    runs_data.append({
                        "ID": run["id"],
                        "优化目标": target_display.get(run["optimization_target"], run["optimization_target"]),
                        "天数": run["num_days"],
                        "日均工时 (h)": run["daily_mill_hours"],
                        "评分": run["score"],
                        "创建时间": run["created_at"],
                    })
                st.dataframe(pd.DataFrame(runs_data), use_container_width=True, hide_index=True)
            else:
                st.info("暂无历史优化记录")

with tab6:
    st.header("⚠️ 气象扰动与风险预警决策")
    st.markdown("叠加风暴潮、降雨入流、设备故障等扰动因素，自动评估不同方案的缺水、溢流和停机风险，生成带风险等级的应急调度建议")

    if "risk_disturbance_scenario" not in st.session_state:
        st.session_state["risk_disturbance_scenario"] = "moderate_storm"
    if "risk_assessment_results" not in st.session_state:
        st.session_state["risk_assessment_results"] = None
    if "risk_compare_results" not in st.session_state:
        st.session_state["risk_compare_results"] = None
    if "risk_emergency_recommendations" not in st.session_state:
        st.session_state["risk_emergency_recommendations"] = None
    if "custom_storm_surge" not in st.session_state:
        st.session_state["custom_storm_surge"] = StormSurgeConfig()
    if "custom_rainfall" not in st.session_state:
        st.session_state["custom_rainfall"] = RainfallConfig()
    if "custom_equipment" not in st.session_state:
        st.session_state["custom_equipment"] = EquipmentFailureConfig()
    if "monte_carlo_result" not in st.session_state:
        st.session_state["monte_carlo_result"] = None
    if "use_monte_carlo" not in st.session_state:
        st.session_state["use_monte_carlo"] = False
    if "monte_carlo_num" not in st.session_state:
        st.session_state["monte_carlo_num"] = 100

    preset_scenarios = generate_disturbance_scenarios()
    scenario_dict = {s.name: s for s in preset_scenarios}

    slider_keys = [
        "custom_surge_height", "custom_surge_start", "custom_surge_duration", "custom_surge_shape",
        "custom_rainfall_rate", "custom_rainfall_start", "custom_rainfall_duration",
        "custom_runoff_coeff", "custom_catchment_area",
        "custom_gate_fail", "custom_mill_fail", "custom_gate_flow_red",
        "custom_failure_start", "custom_failure_duration",
    ]

    def _init_sliders_from_scenario(scenario_name):
        sc = scenario_dict[scenario_name]
        st.session_state["custom_surge_height"] = sc.storm_surge.surge_height
        st.session_state["custom_surge_start"] = sc.storm_surge.surge_start_hour
        st.session_state["custom_surge_duration"] = sc.storm_surge.surge_duration_hours
        st.session_state["custom_surge_shape"] = sc.storm_surge.surge_shape
        st.session_state["custom_rainfall_rate"] = sc.rainfall.rainfall_rate
        st.session_state["custom_rainfall_start"] = sc.rainfall.rainfall_start_hour
        st.session_state["custom_rainfall_duration"] = sc.rainfall.rainfall_duration_hours
        st.session_state["custom_runoff_coeff"] = sc.rainfall.runoff_coefficient
        st.session_state["custom_catchment_area"] = sc.rainfall.catchment_area
        st.session_state["custom_gate_fail"] = sc.equipment.gate_failure_probability
        st.session_state["custom_mill_fail"] = sc.equipment.mill_failure_probability
        st.session_state["custom_gate_flow_red"] = int(sc.equipment.gate_flow_reduction_pct)
        st.session_state["custom_failure_start"] = sc.equipment.failure_start_hour
        st.session_state["custom_failure_duration"] = sc.equipment.failure_duration_hours

    def _on_scenario_change():
        new_scenario = st.session_state["risk_scenario_select"]
        st.session_state["risk_disturbance_scenario"] = new_scenario
        _init_sliders_from_scenario(new_scenario)

    sliders_initialized = any(k in st.session_state for k in slider_keys)
    if not sliders_initialized:
        _init_sliders_from_scenario(st.session_state["risk_disturbance_scenario"])

    st.subheader("🎯 扰动场景选择")

    col_s1, col_s2 = st.columns([2, 1])
    with col_s1:
        selected_scenario_name = st.selectbox(
            "选择预设扰动场景（选择后参数自动同步到下方滑块",
            options=[s.name for s in preset_scenarios],
            format_func=lambda x: f"{scenario_dict[x].description} ({get_risk_level_label(scenario_dict[x].risk_level)})",
            index=[s.name for s in preset_scenarios].index(st.session_state["risk_disturbance_scenario"])
            if st.session_state["risk_disturbance_scenario"] in scenario_dict else 2,
            key="risk_scenario_select",
            on_change=_on_scenario_change,
        )
    with col_s2:
        st.write("")
        st.write("")
        risk_color = get_risk_level_color(scenario_dict[selected_scenario_name].risk_level)
        risk_label = get_risk_level_label(scenario_dict[selected_scenario_name].risk_level)
        st.markdown(f"<span style='color:{risk_color};font-weight:bold;'>场景风险等级：{risk_label}</span>", unsafe_allow_html=True)

    with st.expander("⚙️ 自定义扰动参数", expanded=False):
        st.caption("选择预设场景后参数会自动同步到此处，也可手动调整创建自定义场景")

        col_c1, col_c2, col_c3 = st.columns(3)

        with col_c1:
            st.markdown("**🌊 风暴潮参数**")
            surge_height = st.slider(
                "潮位抬升高度 (m)",
                min_value=0.0,
                max_value=3.0,
                step=0.1,
                key="custom_surge_height",
            )
            surge_start = st.slider(
                "开始时间 (小时)",
                min_value=0.0,
                max_value=168.0,
                step=1.0,
                key="custom_surge_start",
            )
            surge_duration = st.slider(
                "持续时间 (小时)",
                min_value=1.0,
                max_value=72.0,
                step=1.0,
                key="custom_surge_duration",
            )
            surge_shape = st.selectbox(
                "潮位变化形态",
                options=["sinusoidal", "triangular", "rectangular"],
                format_func=lambda x: "正弦曲线" if x == "sinusoidal" else ("三角波" if x == "triangular" else "矩形波"),
                key="custom_surge_shape",
            )

        with col_c2:
            st.markdown("**🌧️ 降雨入流参数**")
            rainfall_rate = st.slider(
                "降雨强度 (mm/h)",
                min_value=0.0,
                max_value=200.0,
                step=5.0,
                key="custom_rainfall_rate",
            )
            rainfall_start = st.slider(
                "开始时间 (小时)",
                min_value=0.0,
                max_value=168.0,
                step=1.0,
                key="custom_rainfall_start",
            )
            rainfall_duration = st.slider(
                "持续时间 (小时)",
                min_value=1.0,
                max_value=72.0,
                step=1.0,
                key="custom_rainfall_duration",
            )
            runoff_coeff = st.slider(
                "径流系数",
                min_value=0.1,
                max_value=1.0,
                step=0.05,
                key="custom_runoff_coeff",
            )
            catchment_area = st.slider(
                "集水面积 (m²)",
                min_value=10.0,
                max_value=500.0,
                step=10.0,
                key="custom_catchment_area",
            )

        with col_c3:
            st.markdown("**🔧 设备故障参数**")
            st.caption("💡 启用概率模拟后会基于蒙特卡洛方法评估真实故障概率分布")
            gate_fail_prob = st.slider(
                "闸门故障概率",
                min_value=0.0,
                max_value=1.0,
                step=0.05,
                key="custom_gate_fail",
            )
            mill_fail_prob = st.slider(
                "磨坊故障概率",
                min_value=0.0,
                max_value=1.0,
                step=0.05,
                key="custom_mill_fail",
            )
            gate_flow_reduction = st.slider(
                "闸门流量降低 (%)",
                min_value=0,
                max_value=100,
                step=5,
                key="custom_gate_flow_red",
            )
            failure_start = st.slider(
                "故障开始时间 (小时)",
                min_value=0.0,
                max_value=168.0,
                step=1.0,
                key="custom_failure_start",
            )
            failure_duration = st.slider(
                "故障持续时间 (小时)",
                min_value=1.0,
                max_value=72.0,
                step=1.0,
                key="custom_failure_duration",
            )

    st.divider()

    st.subheader("📊 风险评估计算")

    col_mode1, col_mode2, col_mode3 = st.columns(3)
    with col_mode1:
        use_mc = st.toggle(
            "启用概率模拟（蒙特卡洛）",
            value=st.session_state["use_monte_carlo"],
            key="use_mc_toggle",
            help="启用后会运行多次随机模拟，基于真实概率分布评估风险",
        )
        st.session_state["use_monte_carlo"] = use_mc
    with col_mode2:
        if use_mc:
            mc_num = st.select_slider(
                "模拟次数",
                options=[20, 50, 100, 200, 500],
                value=st.session_state["monte_carlo_num"],
                key="mc_num_slider",
            )
            st.session_state["monte_carlo_num"] = mc_num
    with col_mode3:
        if use_mc:
            st.info(f"🎲 将运行 {mc_num} 次蒙特卡洛模拟")

    st.markdown("")

    col_r1, col_r2, col_r3 = st.columns(3)
    with col_r1:
        button_label = "🎲 概率风险评估（蒙特卡洛）" if use_mc else "🔍 单场景风险评估"
        if st.button(button_label, use_container_width=True, type="primary", key="run_single_risk"):
            with st.spinner("正在进行风险评估计算..."):
                try:
                    params = SimulationParams(
                        reservoir_capacity=st.session_state["reservoir_capacity"],
                        reservoir_area=st.session_state["reservoir_area"],
                        gate_max_flow=st.session_state["gate_max_flow"],
                        mill_power_consumption=st.session_state["mill_power_consumption"],
                        initial_water_level=st.session_state["initial_water_level"],
                    )

                    tide_data = st.session_state.get("multi_day_tide_records", generate_multi_day_tide_records(num_days=7))
                    total_hours = get_total_hours(tide_data)
                    effective_days = max(1, int(math.ceil(total_hours / 24)))

                    custom_scenario = DisturbanceScenario(
                        name="custom_scenario",
                        description="用户自定义扰动场景",
                        storm_surge=StormSurgeConfig(
                            surge_height=st.session_state["custom_surge_height"],
                            surge_start_hour=st.session_state["custom_surge_start"],
                            surge_duration_hours=st.session_state["custom_surge_duration"],
                            surge_shape=st.session_state["custom_surge_shape"],
                        ),
                        rainfall=RainfallConfig(
                            rainfall_rate=st.session_state["custom_rainfall_rate"],
                            rainfall_start_hour=st.session_state["custom_rainfall_start"],
                            rainfall_duration_hours=st.session_state["custom_rainfall_duration"],
                            runoff_coefficient=st.session_state["custom_runoff_coeff"],
                            catchment_area=st.session_state["custom_catchment_area"],
                        ),
                        equipment=EquipmentFailureConfig(
                            gate_failure_probability=st.session_state["custom_gate_fail"],
                            mill_failure_probability=st.session_state["custom_mill_fail"],
                            gate_flow_reduction_pct=float(st.session_state["custom_gate_flow_red"]),
                            failure_start_hour=st.session_state["custom_failure_start"],
                            failure_duration_hours=st.session_state["custom_failure_duration"],
                        ),
                        risk_level="medium",
                    )

                    baseline_scenario = DisturbanceScenario(
                        name="baseline",
                        description="无扰动基线场景",
                    )

                    if use_mc:
                        mc_result = run_monte_carlo_risk_assessment(
                            params, tide_data,
                            generate_daily_mill_schedule_for_multi_day(effective_days),
                            custom_scenario,
                            num_simulations=st.session_state["monte_carlo_num"],
                        )

                        baseline_sim, _, _ = run_disturbed_simulation(
                            params, tide_data,
                            generate_daily_mill_schedule_for_multi_day(effective_days),
                            baseline_scenario,
                            total_hours=total_hours,
                        )
                        baseline_risk = assess_risks(params, baseline_sim, baseline_scenario)

                        median_disturbed = RiskAssessmentResult(
                            scenario_name="custom_scenario",
                            water_shortage_risk=mc_result.median_risks["water_shortage"],
                            overflow_risk=mc_result.median_risks["overflow"],
                            shutdown_risk=mc_result.median_risks["shutdown"],
                            overall_risk_level=mc_result.overall_risk_level,
                            risk_details={
                                "low_water_duration_pct": 0,
                                "overflow_duration_pct": 0,
                                "mill_availability_pct": 0,
                            },
                            simulation_results=mc_result.all_results[0].simulation_results,
                            metrics={},
                            warnings=mc_result.warnings,
                            is_probabilistic=True,
                            num_simulations=mc_result.num_simulations,
                            risk_confidence_interval={
                                "shortage_low": mc_result.percentile_5_risks["water_shortage"],
                                "shortage_high": mc_result.percentile_95_risks["water_shortage"],
                                "overflow_low": mc_result.percentile_5_risks["overflow"],
                                "overflow_high": mc_result.percentile_95_risks["overflow"],
                                "shutdown_low": mc_result.percentile_5_risks["shutdown"],
                                "shutdown_high": mc_result.percentile_95_risks["shutdown"],
                            },
                        )

                        recommendations = generate_emergency_recommendations(
                            params, baseline_risk, median_disturbed, custom_scenario
                        )

                        st.session_state["monte_carlo_result"] = mc_result
                        st.session_state["risk_assessment_results"] = {
                            "baseline": baseline_risk,
                            "disturbed": median_disturbed,
                        }
                        st.session_state["risk_emergency_recommendations"] = recommendations
                        st.session_state["risk_disturbance_scenario"] = selected_scenario_name

                        st.success(f"✅ 蒙特卡洛风险评估完成! 共运行 {mc_result.num_simulations} 次模拟")
                    else:
                        baseline_sim, _, _ = run_disturbed_simulation(
                            params, tide_data,
                            generate_daily_mill_schedule_for_multi_day(effective_days),
                            baseline_scenario,
                            total_hours=total_hours,
                        )
                        baseline_risk = assess_risks(params, baseline_sim, baseline_scenario)

                        disturbed_sim, _, _ = run_disturbed_simulation(
                            params, tide_data,
                            generate_daily_mill_schedule_for_multi_day(effective_days),
                            custom_scenario,
                            total_hours=total_hours,
                        )
                        disturbed_risk = assess_risks(params, disturbed_sim, custom_scenario)

                        recommendations = generate_emergency_recommendations(
                            params, baseline_risk, disturbed_risk, custom_scenario
                        )

                        st.session_state["risk_assessment_results"] = {
                            "baseline": baseline_risk,
                            "disturbed": disturbed_risk,
                        }
                        st.session_state["risk_emergency_recommendations"] = recommendations
                        st.session_state["risk_disturbance_scenario"] = selected_scenario_name
                        st.session_state["monte_carlo_result"] = None

                        st.success("✅ 风险评估计算完成!")
                except Exception as e:
                    st.error(f"风险评估失败: {e}")
                    import traceback
                    traceback.print_exc()

    with col_r2:
        if st.button("📊 所有场景对比", use_container_width=True, key="run_all_risk"):
            with st.spinner("正在计算所有扰动场景的风险对比..."):
                try:
                    params = SimulationParams(
                        reservoir_capacity=st.session_state["reservoir_capacity"],
                        reservoir_area=st.session_state["reservoir_area"],
                        gate_max_flow=st.session_state["gate_max_flow"],
                        mill_power_consumption=st.session_state["mill_power_consumption"],
                        initial_water_level=st.session_state["initial_water_level"],
                    )

                    tide_data = st.session_state.get("multi_day_tide_records", generate_multi_day_tide_records(num_days=7))
                    total_hours = get_total_hours(tide_data)
                    effective_days = max(1, int(math.ceil(total_hours / 24)))

                    all_scenarios = generate_disturbance_scenarios()
                    compare_results = compare_risk_scenarios(
                        params, tide_data,
                        generate_daily_mill_schedule_for_multi_day(effective_days),
                        all_scenarios,
                    )

                    st.session_state["risk_compare_results"] = compare_results
                    st.success("✅ 所有场景对比计算完成!")
                except Exception as e:
                    st.error(f"场景对比计算失败: {e}")

    with col_r3:
        if st.button("🔄 清除结果", use_container_width=True, key="clear_risk_results"):
            st.session_state["risk_assessment_results"] = None
            st.session_state["risk_compare_results"] = None
            st.session_state["risk_emergency_recommendations"] = None
            st.rerun()

    st.divider()

    if st.session_state.get("risk_assessment_results") is not None:
        baseline_risk = st.session_state["risk_assessment_results"]["baseline"]
        disturbed_risk = st.session_state["risk_assessment_results"]["disturbed"]
        is_prob = bool(
            hasattr(disturbed_risk, "is_probabilistic") and disturbed_risk.is_probabilistic
        )

        if is_prob:
            st.subheader("📈 概率风险评估结果（蒙特卡洛）")
            st.caption(f"基于 {disturbed_risk.num_simulations} 次随机模拟，展示中位数风险值及 5%-95% 置信区间")
        else:
            st.subheader("📈 单场景风险评估结果（确定性）")

        col_m1, col_m2, col_m3, col_m4 = st.columns(4)
        with col_m1:
            risk_color = get_risk_level_color(disturbed_risk.overall_risk_level)
            risk_label = get_risk_level_label(disturbed_risk.overall_risk_level)
            st.metric(
                "综合风险等级",
                risk_label,
                delta=f"vs 基线: {get_risk_level_label(baseline_risk.overall_risk_level)}",
                delta_color="inverse",
            )
            st.markdown(f"<div style='width:100%;height:10px;background:#e0e0e0;border-radius:5px;'><div style='width:100%;height:100%;background:{risk_color};border-radius:5px;'></div></div>", unsafe_allow_html=True)
        with col_m2:
            delta_short = disturbed_risk.water_shortage_risk - baseline_risk.water_shortage_risk
            st.metric(
                "缺水风险",
                f"{disturbed_risk.water_shortage_risk:.1f}%",
                delta=f"{delta_short:+.1f}%",
                delta_color="inverse",
            )
        with col_m3:
            delta_over = disturbed_risk.overflow_risk - baseline_risk.overflow_risk
            st.metric(
                "溢流风险",
                f"{disturbed_risk.overflow_risk:.1f}%",
                delta=f"{delta_over:+.1f}%",
                delta_color="inverse",
            )
        with col_m4:
            delta_shut = disturbed_risk.shutdown_risk - baseline_risk.shutdown_risk
            st.metric(
                "停机风险",
                f"{disturbed_risk.shutdown_risk:.1f}%",
                delta=f"{delta_shut:+.1f}%",
                delta_color="inverse",
            )

        if disturbed_risk.warnings:
            with st.expander(f"⚠️ 风险警告 ({len(disturbed_risk.warnings)} 条)", expanded=True):
                for w in disturbed_risk.warnings:
                    st.warning(w)

        if is_prob and hasattr(disturbed_risk, 'risk_confidence_interval') and disturbed_risk.risk_confidence_interval:
            st.subheader("📊 置信区间（5%-95%）")
            ci = disturbed_risk.risk_confidence_interval
            col_ci1, col_ci2, col_ci3 = st.columns(3)
            with col_ci1:
                st.metric(
                    "缺水风险范围",
                    f"{ci['shortage_low']:.1f}% - {ci['shortage_high']:.1f}%",
                    delta=f"中位数 {disturbed_risk.water_shortage_risk:.1f}%",
                )
            with col_ci2:
                st.metric(
                    "溢流风险范围",
                    f"{ci['overflow_low']:.1f}% - {ci['overflow_high']:.1f}%",
                    delta=f"中位数 {disturbed_risk.overflow_risk:.1f}%",
                )
            with col_ci3:
                st.metric(
                    "停机风险范围",
                    f"{ci['shutdown_low']:.1f}% - {ci['shutdown_high']:.1f}%",
                    delta=f"中位数 {disturbed_risk.shutdown_risk:.1f}%",
                )

            mc_result = st.session_state.get("monte_carlo_result")
            if mc_result:
                with st.expander("📈 风险分布直方图", expanded=False):
                    dist = mc_result.risk_distributions
                    fig_dist = make_subplots(
                        rows=1, cols=3,
                        subplot_titles=("缺水风险分布", "溢流风险分布", "停机风险分布"),
                    )
                    fig_dist.add_trace(
                        go.Histogram(x=dist["water_shortage"], nbinsx=20, name="缺水风险", marker_color="#ff7f0e"),
                        row=1, col=1,
                    )
                    fig_dist.add_trace(
                        go.Histogram(x=dist["overflow"], nbinsx=20, name="溢流风险", marker_color="#d62728"),
                        row=1, col=2,
                    )
                    fig_dist.add_trace(
                        go.Histogram(x=dist["shutdown"], nbinsx=20, name="停机风险", marker_color="#9467bd"),
                        row=1, col=3,
                    )
                    fig_dist.update_layout(
                        height=350,
                        showlegend=False,
                        title_text=f"风险概率分布 (n={mc_result.num_simulations})",
                    )
                    fig_dist.update_xaxes(title_text="风险值 (%)")
                    fig_dist.update_yaxes(title_text="频次")
                    st.plotly_chart(fig_dist, use_container_width=True)

                    dist_stats = pd.DataFrame([
                        {"指标": "均值 (%)", "缺水风险": round(mc_result.mean_risks["water_shortage"], 1),
                         "溢流风险": round(mc_result.mean_risks["overflow"], 1),
                         "停机风险": round(mc_result.mean_risks["shutdown"], 1)},
                        {"指标": "中位数 (%)", "缺水风险": round(mc_result.median_risks["water_shortage"], 1),
                         "溢流风险": round(mc_result.median_risks["overflow"], 1),
                         "停机风险": round(mc_result.median_risks["shutdown"], 1)},
                        {"指标": "5%分位数 (%)", "缺水风险": round(mc_result.percentile_5_risks["water_shortage"], 1),
                         "溢流风险": round(mc_result.percentile_5_risks["overflow"], 1),
                         "停机风险": round(mc_result.percentile_5_risks["shutdown"], 1)},
                        {"指标": "95%分位数 (%)", "缺水风险": round(mc_result.percentile_95_risks["water_shortage"], 1),
                         "溢流风险": round(mc_result.percentile_95_risks["overflow"], 1),
                         "停机风险": round(mc_result.percentile_95_risks["shutdown"], 1)},
                    ])
                    st.dataframe(dist_stats, use_container_width=True, hide_index=True)

        st.subheader("📊 详细风险指标对比")

        risk_compare_data = [
            {
                "风险指标": "缺水风险",
                "基线场景 (%)": round(baseline_risk.water_shortage_risk, 2),
                "扰动场景 (%)": round(disturbed_risk.water_shortage_risk, 2),
                "变化 (%)": round(disturbed_risk.water_shortage_risk - baseline_risk.water_shortage_risk, 2),
            },
            {
                "风险指标": "溢流风险",
                "基线场景 (%)": round(baseline_risk.overflow_risk, 2),
                "扰动场景 (%)": round(disturbed_risk.overflow_risk, 2),
                "变化 (%)": round(disturbed_risk.overflow_risk - baseline_risk.overflow_risk, 2),
            },
            {
                "风险指标": "停机风险",
                "基线场景 (%)": round(baseline_risk.shutdown_risk, 2),
                "扰动场景 (%)": round(disturbed_risk.shutdown_risk, 2),
                "变化 (%)": round(disturbed_risk.shutdown_risk - baseline_risk.shutdown_risk, 2),
            },
            {
                "风险指标": "低水位持续时间占比",
                "基线场景 (%)": baseline_risk.risk_details.get("low_water_duration_pct", 0),
                "扰动场景 (%)": disturbed_risk.risk_details.get("low_water_duration_pct", 0),
                "变化 (%)": round(
                    disturbed_risk.risk_details.get("low_water_duration_pct", 0) -
                    baseline_risk.risk_details.get("low_water_duration_pct", 0), 2
                ),
            },
            {
                "风险指标": "溢流持续时间占比",
                "基线场景 (%)": baseline_risk.risk_details.get("overflow_duration_pct", 0),
                "扰动场景 (%)": disturbed_risk.risk_details.get("overflow_duration_pct", 0),
                "变化 (%)": round(
                    disturbed_risk.risk_details.get("overflow_duration_pct", 0) -
                    baseline_risk.risk_details.get("overflow_duration_pct", 0), 2
                ),
            },
            {
                "风险指标": "磨坊可用率",
                "基线场景 (%)": baseline_risk.risk_details.get("mill_availability_pct", 0),
                "扰动场景 (%)": disturbed_risk.risk_details.get("mill_availability_pct", 0),
                "变化 (%)": round(
                    disturbed_risk.risk_details.get("mill_availability_pct", 0) -
                    baseline_risk.risk_details.get("mill_availability_pct", 0), 2
                ),
            },
        ]

        st.dataframe(pd.DataFrame(risk_compare_data), use_container_width=True, hide_index=True)

        st.subheader("📈 水位变化对比曲线")

        df_baseline = pd.DataFrame(baseline_risk.simulation_results)
        df_disturbed = pd.DataFrame(disturbed_risk.simulation_results)

        fig_risk = make_subplots(
            rows=3,
            cols=1,
            shared_xaxes=True,
            vertical_spacing=0.08,
            subplot_titles=("蓄水量对比 (m³)", "闸门开启比例对比 (%)", "扰动强度"),
            row_heights=[0.4, 0.3, 0.3],
        )

        fig_risk.add_trace(
            go.Scatter(
                x=df_baseline["time_hour"] / 24,
                y=df_baseline["water_volume"],
                name="基线 - 蓄水量",
                line=dict(color="#1f77b4", width=2),
            ),
            row=1,
            col=1,
        )
        fig_risk.add_trace(
            go.Scatter(
                x=df_disturbed["time_hour"] / 24,
                y=df_disturbed["water_volume"],
                name="扰动 - 蓄水量",
                line=dict(color="#d62728", width=2),
            ),
            row=1,
            col=1,
        )
        fig_risk.add_hline(
            y=st.session_state["reservoir_capacity"],
            line_dash="dash",
            line_color="red",
            annotation_text="容量上限",
            annotation_position="right",
            row=1,
            col=1,
        )

        fig_risk.add_trace(
            go.Scatter(
                x=df_baseline["time_hour"] / 24,
                y=df_baseline["gate_open_ratio"],
                name="基线 - 闸门",
                line=dict(color="#1f77b4", width=2),
            ),
            row=2,
            col=1,
        )
        fig_risk.add_trace(
            go.Scatter(
                x=df_disturbed["time_hour"] / 24,
                y=df_disturbed["gate_open_ratio"],
                name="扰动 - 闸门",
                line=dict(color="#d62728", width=2),
            ),
            row=2,
            col=1,
        )

        if "storm_surge" in df_disturbed.columns:
            fig_risk.add_trace(
                go.Scatter(
                    x=df_disturbed["time_hour"] / 24,
                    y=df_disturbed["storm_surge"],
                    name="风暴潮 (m)",
                    line=dict(color="#ff7f0e", width=2),
                    fill="tozeroy",
                    fillcolor="rgba(255, 127, 14, 0.2)",
                ),
                row=3,
                col=1,
            )
        if "rainfall_inflow" in df_disturbed.columns:
            fig_risk.add_trace(
                go.Scatter(
                    x=df_disturbed["time_hour"] / 24,
                    y=df_disturbed["rainfall_inflow"],
                    name="降雨入流 (m³/h)",
                    line=dict(color="#2ca02c", width=2),
                    fill="tozeroy",
                    fillcolor="rgba(44, 160, 44, 0.2)",
                ),
                row=3,
                col=1,
            )

        fig_risk.update_layout(
            height=700,
            hovermode="x unified",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        )
        fig_risk.update_xaxes(title_text="时间 (天)", row=3, col=1)
        fig_risk.update_yaxes(title_text="蓄水量 (m³)", row=1, col=1)
        fig_risk.update_yaxes(title_text="开启比例 (%)", row=2, col=1, range=[0, 105])
        fig_risk.update_yaxes(title_text="强度", row=3, col=1)

        st.plotly_chart(fig_risk, use_container_width=True)

        st.divider()
        st.subheader("🚨 应急调度建议")

        recommendations = st.session_state.get("risk_emergency_recommendations", [])
        if recommendations:
            priority_colors = {
                "critical": "#9400d3",
                "high": "#d62728",
                "medium": "#ff7f0e",
                "low": "#2ca02c",
            }
            priority_labels = {
                "critical": "紧急",
                "high": "高优先级",
                "medium": "中优先级",
                "low": "低优先级",
            }

            for i, rec in enumerate(recommendations):
                color = priority_colors.get(rec.priority, "#7f7f7f")
                label = priority_labels.get(rec.priority, "未知")

                with st.expander(f"{'🔴' if rec.priority == 'high' else '🟠' if rec.priority == 'medium' else '🟢'} {rec.action} ({label})", expanded=(i < 2)):
                    st.markdown(f"<p style='color:{color};font-weight:bold;'>优先级：{label}</p>", unsafe_allow_html=True)
                    st.write(f"**描述**：{rec.description}")
                    st.write(f"**影响**：{rec.risk_impact}")
                    st.write(f"**建议时间窗口**：第 {rec.time_window[0]/24:.2f} 天 - 第 {rec.time_window[1]/24:.2f} 天")

                    if rec.details:
                        st.write("**详细参数**：")
                        for k, v in rec.details.items():
                            st.caption(f"  • {k}: {v}")
        else:
            st.info("暂无应急调度建议")

    if st.session_state.get("risk_compare_results") is not None and len(st.session_state["risk_compare_results"]) > 0:
        st.divider()
        st.subheader("📊 所有扰动场景风险对比")

        compare_results = st.session_state["risk_compare_results"]

        scenario_display = {
            "baseline": "📊 基线",
            "minor_storm": "🌊 小型风暴",
            "moderate_storm": "⛈️ 中型风暴",
            "severe_storm": "🌀 严重风暴",
            "equipment_failure": "🔧 设备故障",
            "heavy_rainfall": "🌧️ 强降雨",
        }

        compare_data = []
        for res in compare_results:
            compare_data.append({
                "场景": scenario_display.get(res.scenario_name, res.scenario_name),
                "综合风险等级": get_risk_level_label(res.overall_risk_level),
                "缺水风险 (%)": round(res.water_shortage_risk, 1),
                "溢流风险 (%)": round(res.overflow_risk, 1),
                "停机风险 (%)": round(res.shutdown_risk, 1),
                "磨坊运行 (h)": round(res.risk_details.get("total_mill_hours", 0), 1),
                "溢流水量 (m³)": round(res.risk_details.get("overflow_volume", 0), 1),
                "最低蓄水量 (m³)": round(res.risk_details.get("min_water_volume", 0), 1),
            })

        st.dataframe(pd.DataFrame(compare_data), use_container_width=True, hide_index=True)

        st.subheader("📈 三项风险对比柱状图")

        bar_compare_fig = go.Figure()

        scenario_names = [scenario_display.get(r.scenario_name, r.scenario_name) for r in compare_results]

        bar_compare_fig.add_trace(go.Bar(
            x=scenario_names,
            y=[r.water_shortage_risk for r in compare_results],
            name="缺水风险 (%)",
            marker_color="#ff7f0e",
        ))
        bar_compare_fig.add_trace(go.Bar(
            x=scenario_names,
            y=[r.overflow_risk for r in compare_results],
            name="溢流风险 (%)",
            marker_color="#d62728",
        ))
        bar_compare_fig.add_trace(go.Bar(
            x=scenario_names,
            y=[r.shutdown_risk for r in compare_results],
            name="停机风险 (%)",
            marker_color="#9467bd",
        ))

        bar_compare_fig.update_layout(
            barmode="group",
            height=400,
            title="各场景三项风险指标对比",
            yaxis_title="风险值 (%)",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        )

        st.plotly_chart(bar_compare_fig, use_container_width=True)

        st.subheader("📉 蓄水量变化对比")

        water_compare_fig = go.Figure()

        colors = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b"]
        for i, res in enumerate(compare_results):
            df_res = pd.DataFrame(res.simulation_results)
            water_compare_fig.add_trace(
                go.Scatter(
                    x=df_res["time_hour"] / 24,
                    y=df_res["water_volume"],
                    name=scenario_display.get(res.scenario_name, res.scenario_name),
                    line=dict(color=colors[i % len(colors)], width=2),
                )
            )

        water_compare_fig.add_hline(
            y=st.session_state["reservoir_capacity"],
            line_dash="dash",
            line_color="red",
            annotation_text="容量上限",
            annotation_position="right",
        )

        water_compare_fig.update_layout(
            height=400,
            title="各场景蓄水量变化对比",
            xaxis_title="时间 (天)",
            yaxis_title="蓄水量 (m³)",
            hovermode="x unified",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        )

        st.plotly_chart(water_compare_fig, use_container_width=True)

with tab7:
    st.header("📜 协同决策与历史方案复盘")
    st.markdown("保存多套调度策略，记录决策理由与风险处置动作，通过时间轴复盘不同策略的产量、溢流、停机和风险变化全过程")

    if "decision_strategy_name" not in st.session_state:
        st.session_state["decision_strategy_name"] = ""
    if "decision_strategy_desc" not in st.session_state:
        st.session_state["decision_strategy_desc"] = ""
    if "decision_reason" not in st.session_state:
        st.session_state["decision_reason"] = ""
    if "selected_strategies_compare" not in st.session_state:
        st.session_state["selected_strategies_compare"] = []
    if "strategy_timeline_data" not in st.session_state:
        st.session_state["strategy_timeline_data"] = None
    if "strategy_compare_result" not in st.session_state:
        st.session_state["strategy_compare_result"] = None
    if "review_window_hours" not in st.session_state:
        st.session_state["review_window_hours"] = 6.0
    if "active_strategy_detail" not in st.session_state:
        st.session_state["active_strategy_detail"] = None
    if "risk_actions_temp" not in st.session_state:
        st.session_state["risk_actions_temp"] = []

    scenario_id = st.session_state.get("scenario_id")

    if not scenario_id:
        st.info("💡 请先在左侧保存一个方案，然后在此处进行决策策略的保存与复盘分析")
    else:
        strategies = list_strategies(scenario_id)

        with st.expander("💾 保存当前策略", expanded=True):
            st.subheader("保存当前调度策略")
            st.caption("将当前模拟或优化结果保存为一个决策策略，记录决策理由和风险处置动作")

            col_s1, col_s2 = st.columns([2, 1])
            with col_s1:
                strategy_name = st.text_input(
                    "策略名称",
                    value=st.session_state["decision_strategy_name"],
                    key="strategy_name_input",
                    placeholder="例如：汛期高产方案、低水位节水策略",
                )
            with col_s2:
                strategy_type = st.selectbox(
                    "策略类型",
                    options=["optimized", "manual", "baseline"],
                    format_func=lambda x: "🤖 自动优化" if x == "optimized" else
                                          ("✋ 手动调度" if x == "manual" else "📊 基准方案"),
                    key="strategy_type_select",
                )

            strategy_desc = st.text_input(
                "策略描述",
                value=st.session_state["decision_strategy_desc"],
                key="strategy_desc_input",
                placeholder="简要描述该策略的适用场景和特点",
            )

            decision_reason = st.text_area(
                "📝 决策理由",
                value=st.session_state["decision_reason"],
                height=80,
                key="decision_reason_input",
                placeholder="记录选择此策略的原因、依据、预期效果等",
            )

            col_sa1, col_sa2 = st.columns(2)
            with col_sa1:
                save_source = st.radio(
                    "数据来源",
                    options=["current_sim", "current_opt"],
                    format_func=lambda x: "📊 当前模拟结果" if x == "current_sim" else "🎯 当前优化结果",
                    horizontal=True,
                    key="save_source_radio",
                )
            with col_sa2:
                st.write("")
                st.write("")
                st.caption("选择将哪个结果保存为决策策略")

            st.divider()
            st.markdown("**🚨 风险处置记录**")
            st.caption("记录该策略对应的风险处置动作和应急方案")

            action_type_options = [
                "闸门调节", "磨坊调度", "预泄腾库", "蓄水保水",
                "设备检修", "人员调度", "物资准备", "应急预案", "其他"
            ]
            priority_options = ["critical", "high", "medium", "low"]
            priority_labels = {"critical": "紧急", "high": "高", "medium": "中", "low": "低"}

            col_ar1, col_ar2, col_ar3, col_ar4, col_ar5 = st.columns([2, 3, 1, 1, 1])
            with col_ar1:
                new_action_type = st.selectbox(
                    "动作类型",
                    options=action_type_options,
                    key="new_action_type",
                )
            with col_ar2:
                new_action_desc = st.text_input(
                    "动作描述",
                    key="new_action_desc",
                    placeholder="描述具体的风险处置动作",
                )
            with col_ar3:
                new_action_start = st.number_input(
                    "开始(h)",
                    min_value=0.0,
                    max_value=200.0,
                    value=0.0,
                    step=1.0,
                    key="new_action_start",
                )
            with col_ar4:
                new_action_end = st.number_input(
                    "结束(h)",
                    min_value=0.0,
                    max_value=200.0,
                    value=24.0,
                    step=1.0,
                    key="new_action_end",
                )
            with col_ar5:
                new_action_priority = st.selectbox(
                    "优先级",
                    options=priority_options,
                    format_func=lambda x: priority_labels[x],
                    key="new_action_priority",
                )

            if st.button("➕ 添加风险处置动作", use_container_width=True, key="add_risk_action"):
                new_action = {
                    "action_type": new_action_type,
                    "action_description": new_action_desc,
                    "start_hour": new_action_start,
                    "end_hour": new_action_end,
                    "priority": new_action_priority,
                }
                st.session_state["risk_actions_temp"].append(new_action)
                st.success("已添加风险处置动作")
                st.rerun()

            if st.session_state["risk_actions_temp"]:
                st.markdown("**已记录的风险处置动作：**")
                for i, action in enumerate(st.session_state["risk_actions_temp"]):
                    col_a1, col_a2, col_a3 = st.columns([5, 1, 1])
                    with col_a1:
                        st.caption(
                            f"[{priority_labels.get(action['priority'], '中')}] "
                            f"{action['action_type']}: {action['action_description']} "
                            f"(第{action['start_hour']:.0f}h - 第{action['end_hour']:.0f}h)"
                        )
                    with col_a3:
                        if st.button("🗑️", key=f"del_action_{i}"):
                            st.session_state["risk_actions_temp"].pop(i)
                            st.rerun()

            col_save_btn1, col_save_btn2 = st.columns(2)
            with col_save_btn1:
                if st.button("💾 保存策略", use_container_width=True, type="primary", key="save_strategy_btn"):
                    if not strategy_name:
                        st.error("请输入策略名称")
                    else:
                        try:
                            params = SimulationParams(
                                reservoir_capacity=st.session_state["reservoir_capacity"],
                                reservoir_area=st.session_state["reservoir_area"],
                                gate_max_flow=st.session_state["gate_max_flow"],
                                mill_power_consumption=st.session_state["mill_power_consumption"],
                                initial_water_level=st.session_state["initial_water_level"],
                            )

                            sim_results = None
                            metrics = None
                            mill_sched = None
                            gate_sched = None
                            opt_target = None

                            if save_source == "current_opt" and st.session_state.get("optimization_results") is not None:
                                opt_result = st.session_state["optimization_results"]
                                sim_results = opt_result.simulation_results
                                metrics = opt_result.metrics
                                mill_sched = opt_result.mill_schedule
                                gate_sched = opt_result.gate_schedule
                                opt_target = opt_result.target
                            else:
                                tide_records = st.session_state.get("tide_records", generate_default_tide_records())
                                mill_schedule = st.session_state.get("mill_schedule", generate_default_mill_schedule())
                                manual_gate = None
                                if st.session_state.get("gate_mode") == "manual":
                                    manual_gate = st.session_state.get("manual_gate_schedule")

                                sim_results, gate_sched, warns = run_simulation(
                                    params, tide_records, mill_schedule,
                                    manual_gate_schedule=manual_gate,
                                )
                                metrics = compute_simulation_metrics(sim_results, params)
                                mill_sched = mill_schedule

                            new_strategy_id = create_strategy(
                                scenario_id=scenario_id,
                                name=strategy_name,
                                description=strategy_desc,
                                strategy_type=strategy_type,
                                optimization_target=opt_target,
                                decision_reason=decision_reason,
                            )

                            save_strategy_simulation_data(
                                new_strategy_id,
                                sim_results,
                                metrics,
                                mill_sched,
                                gate_sched,
                                reservoir_capacity=params.reservoir_capacity,
                            )

                            if st.session_state["risk_actions_temp"]:
                                save_strategy_risk_actions(
                                    new_strategy_id,
                                    st.session_state["risk_actions_temp"],
                                )

                            st.session_state["decision_strategy_name"] = ""
                            st.session_state["decision_strategy_desc"] = ""
                            st.session_state["decision_reason"] = ""
                            st.session_state["risk_actions_temp"] = []
                            st.success(f"✅ 策略已保存！策略ID: {new_strategy_id}")
                            st.rerun()
                        except Exception as e:
                            st.error(f"保存失败: {e}")
                            import traceback
                            traceback.print_exc()

            with col_save_btn2:
                if st.button("🗑️ 清空表单", use_container_width=True, key="clear_strategy_form"):
                    st.session_state["decision_strategy_name"] = ""
                    st.session_state["decision_strategy_desc"] = ""
                    st.session_state["decision_reason"] = ""
                    st.session_state["risk_actions_temp"] = []
                    st.rerun()

        st.divider()

        with st.expander("📋 已保存策略列表", expanded=True):
            if not strategies:
                st.info("暂无已保存的策略，请先保存一个策略")
            else:
                st.info(f"共有 {len(strategies)} 个已保存的决策策略")

                strategy_type_display = {
                    "optimized": "🤖 自动优化",
                    "manual": "✋ 手动调度",
                    "baseline": "📊 基准方案",
                }

                strat_data = []
                for s in strategies:
                    strat_data.append({
                        "ID": s["id"],
                        "策略名称": s["name"],
                        "类型": strategy_type_display.get(s["strategy_type"], s["strategy_type"]),
                        "描述": s.get("description", ""),
                        "更新时间": s["updated_at"],
                    })

                st.dataframe(pd.DataFrame(strat_data), use_container_width=True, hide_index=True)

                col_m1, col_m2 = st.columns(2)
                with col_m1:
                    selected_ids = st.multiselect(
                        "选择要对比分析的策略",
                        options=[s["id"] for s in strategies],
                        format_func=lambda x: next(
                            (s["name"] for s in strategies if s["id"] == x), str(x)
                        ),
                        default=st.session_state.get("selected_strategies_compare", []),
                        key="compare_strategies_select",
                    )
                with col_m2:
                    window_hours = st.slider(
                        "滚动分析窗口 (小时)",
                        min_value=1.0,
                        max_value=24.0,
                        value=st.session_state["review_window_hours"],
                        step=1.0,
                        key="window_hours_slider",
                        help="用于计算滚动产量和风险指标的时间窗口大小",
                    )
                    st.session_state["review_window_hours"] = window_hours

                if st.button("🔍 开始对比分析", use_container_width=True, type="primary",
                             key="run_strategy_compare", disabled=len(selected_ids) < 2):
                    if len(selected_ids) < 2:
                        st.warning("请至少选择2个策略进行对比")
                    else:
                        with st.spinner("正在进行策略对比分析..."):
                            try:
                                strategies_data = []
                                strategy_names = []

                                for sid in selected_ids:
                                    strat = get_strategy(sid)
                                    if strat:
                                        strategies_data.append(strat)
                                        strategy_names.append(strat["name"])

                                params = SimulationParams(
                                    reservoir_capacity=st.session_state["reservoir_capacity"],
                                    reservoir_area=st.session_state["reservoir_area"],
                                    gate_max_flow=st.session_state["gate_max_flow"],
                                    mill_power_consumption=st.session_state["mill_power_consumption"],
                                    initial_water_level=st.session_state["initial_water_level"],
                                )

                                compare_result = compare_strategies(
                                    strategies_data, strategy_names
                                )
                                timeline = build_timeline_analysis(
                                    strategies_data, strategy_names,
                                    params, window_hours,
                                )

                                st.session_state["selected_strategies_compare"] = selected_ids
                                st.session_state["strategy_compare_result"] = compare_result
                                st.session_state["strategy_timeline_data"] = timeline
                                st.success("✅ 对比分析完成!")
                            except Exception as e:
                                st.error(f"对比分析失败: {e}")
                                import traceback
                                traceback.print_exc()

        if st.session_state.get("strategy_compare_result") is not None:
            st.divider()
            st.subheader("📊 策略指标对比")

            comp_result = st.session_state["strategy_compare_result"]

            compare_table_data = []
            metric_order = [
                "total_mill_hours", "total_gate_open_hours", "overflow_volume",
                "avg_water_volume", "max_water_volume", "min_water_volume",
                "capacity_utilization_pct", "total_inflow",
            ]

            for key in metric_order:
                if key in comp_result.metrics_comparison:
                    row = {"指标": get_metric_label(key)}
                    for i, name in enumerate(comp_result.strategy_names):
                        value = comp_result.metrics_comparison[key][i]
                        row[name] = format_metric_value(key, value)
                    row["最优策略"] = comp_result.best_by_metric.get(key, "-")
                    compare_table_data.append(row)

            st.dataframe(pd.DataFrame(compare_table_data), use_container_width=True, hide_index=True)

            st.markdown(f"**🏆 综合排名：** {' → '.join(comp_result.overall_ranking)}")

            st.subheader("📈 关键指标对比图")

            col_gm1, col_gm2, col_gm3 = st.columns(3)
            with col_gm1:
                bar_mill = go.Figure()
                for i, name in enumerate(comp_result.strategy_names):
                    mill_hours = comp_result.metrics_comparison.get("total_mill_hours", [0])[i]
                    bar_mill.add_trace(go.Bar(
                        x=[name], y=[mill_hours], name=name,
                        marker_color=f"hsla({i * 60}, 70%, 50%, 0.8)",
                    ))
                bar_mill.update_layout(
                    title="磨坊运行时长对比",
                    height=300,
                    showlegend=False,
                    yaxis_title="时长 (h)",
                )
                st.plotly_chart(bar_mill, use_container_width=True)

            with col_gm2:
                bar_overflow = go.Figure()
                for i, name in enumerate(comp_result.strategy_names):
                    overflow = comp_result.metrics_comparison.get("overflow_volume", [0])[i]
                    bar_overflow.add_trace(go.Bar(
                        x=[name], y=[overflow], name=name,
                        marker_color=f"hsla({i * 60 + 10}, 70%, 50%, 0.8)",
                    ))
                bar_overflow.update_layout(
                    title="溢流水量对比",
                    height=300,
                    showlegend=False,
                    yaxis_title="水量 (m³)",
                )
                st.plotly_chart(bar_overflow, use_container_width=True)

            with col_gm3:
                bar_cap = go.Figure()
                for i, name in enumerate(comp_result.strategy_names):
                    cap_util = comp_result.metrics_comparison.get("capacity_utilization_pct", [0])[i]
                    bar_cap.add_trace(go.Bar(
                        x=[name], y=[cap_util], name=name,
                        marker_color=f"hsla({i * 60 + 30}, 70%, 50%, 0.8)",
                    ))
                bar_cap.update_layout(
                    title="库容利用率对比",
                    height=300,
                    showlegend=False,
                    yaxis_title="利用率 (%)",
                )
                st.plotly_chart(bar_cap, use_container_width=True)

        if st.session_state.get("strategy_timeline_data") is not None:
            st.divider()
            st.subheader("⏱️ 时间轴全过程复盘")

            timeline = st.session_state["strategy_timeline_data"]
            strategy_names = timeline.time_hours and [name for name in timeline.water_volumes.keys()]

            if not strategy_names:
                strategy_names = []

            colors_list = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b"]

            time_days = [t / 24 for t in timeline.time_hours]

            st.markdown("**📈 蓄水量变化对比**")
            fig_water = go.Figure()

            for i, name in enumerate(strategy_names):
                fig_water.add_trace(go.Scatter(
                    x=time_days,
                    y=timeline.water_volumes[name],
                    name=name,
                    line=dict(color=colors_list[i % len(colors_list)], width=2),
                ))

            fig_water.add_hline(
                y=st.session_state["reservoir_capacity"],
                line_dash="dash",
                line_color="red",
                annotation_text="容量上限",
                annotation_position="right",
            )

            fig_water.update_layout(
                height=350,
                hovermode="x unified",
                xaxis_title="时间 (天)",
                yaxis_title="蓄水量 (m³)",
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            )
            st.plotly_chart(fig_water, use_container_width=True)

            st.markdown("**🚪 闸门开启比例对比**")
            fig_gate = go.Figure()

            for i, name in enumerate(strategy_names):
                fig_gate.add_trace(go.Scatter(
                    x=time_days,
                    y=timeline.gate_ratios[name],
                    name=name,
                    line=dict(color=colors_list[i % len(colors_list)], width=2),
                ))

            fig_gate.update_layout(
                height=300,
                hovermode="x unified",
                xaxis_title="时间 (天)",
                yaxis_title="开启比例 (%)",
                yaxis_range=[0, 105],
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            )
            st.plotly_chart(fig_gate, use_container_width=True)

            st.markdown("**⚡ 滚动产量变化**")
            st.caption(f"滚动窗口：{st.session_state['review_window_hours']} 小时")

            fig_yield = go.Figure()
            for i, name in enumerate(strategy_names):
                yield_data = timeline.rolling_yield.get(name, [])
                yield_times = [t / 24 for t in timeline.time_hours[:len(yield_data)]]
                fig_yield.add_trace(go.Scatter(
                    x=yield_times,
                    y=yield_data,
                    name=name,
                    line=dict(color=colors_list[i % len(colors_list)], width=2),
                    fill="tozeroy",
                    fillcolor=f"rgba({int(colors_list[i % len(colors_list)][1:3], 16)}, "
                              f"{int(colors_list[i % len(colors_list)][3:5], 16)}, "
                              f"{int(colors_list[i % len(colors_list)][5:7], 16)}, 0.15)",
                ))

            fig_yield.update_layout(
                height=300,
                hovermode="x unified",
                xaxis_title="时间 (天)",
                yaxis_title="滚动产量 (磨坊小时数)",
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            )
            st.plotly_chart(fig_yield, use_container_width=True)

            st.markdown("**⚠️ 滚动风险变化**")

            risk_tabs = st.tabs(["溢流风险", "缺水风险", "停机风险"])

            with risk_tabs[0]:
                fig_overflow_risk = go.Figure()
                for i, name in enumerate(strategy_names):
                    risk_data = timeline.rolling_risk.get(name, {}).get("overflow", [])
                    risk_times = [t / 24 for t in timeline.time_hours[:len(risk_data)]]
                    fig_overflow_risk.add_trace(go.Scatter(
                        x=risk_times,
                        y=risk_data,
                        name=name,
                        line=dict(color=colors_list[i % len(colors_list)], width=2),
                    ))

                fig_overflow_risk.add_hrect(
                    y0=70, y1=100,
                    fillcolor="rgba(214, 39, 40, 0.15)",
                    line_width=0,
                    annotation_text="高风险区",
                    annotation_position="right",
                )

                fig_overflow_risk.update_layout(
                    height=280,
                    hovermode="x unified",
                    xaxis_title="时间 (天)",
                    yaxis_title="溢流风险 (%)",
                    yaxis_range=[0, 105],
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                )
                st.plotly_chart(fig_overflow_risk, use_container_width=True)

            with risk_tabs[1]:
                fig_shortage_risk = go.Figure()
                for i, name in enumerate(strategy_names):
                    risk_data = timeline.rolling_risk.get(name, {}).get("shortage", [])
                    risk_times = [t / 24 for t in timeline.time_hours[:len(risk_data)]]
                    fig_shortage_risk.add_trace(go.Scatter(
                        x=risk_times,
                        y=risk_data,
                        name=name,
                        line=dict(color=colors_list[i % len(colors_list)], width=2),
                    ))

                fig_shortage_risk.add_hrect(
                    y0=70, y1=100,
                    fillcolor="rgba(255, 127, 14, 0.15)",
                    line_width=0,
                    annotation_text="高风险区",
                    annotation_position="right",
                )

                fig_shortage_risk.update_layout(
                    height=280,
                    hovermode="x unified",
                    xaxis_title="时间 (天)",
                    yaxis_title="缺水风险 (%)",
                    yaxis_range=[0, 105],
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                )
                st.plotly_chart(fig_shortage_risk, use_container_width=True)

            with risk_tabs[2]:
                fig_shutdown_risk = go.Figure()
                for i, name in enumerate(strategy_names):
                    risk_data = timeline.rolling_risk.get(name, {}).get("shutdown", [])
                    risk_times = [t / 24 for t in timeline.time_hours[:len(risk_data)]]
                    fig_shutdown_risk.add_trace(go.Scatter(
                        x=risk_times,
                        y=risk_data,
                        name=name,
                        line=dict(color=colors_list[i % len(colors_list)], width=2),
                    ))

                fig_shutdown_risk.add_hrect(
                    y0=70, y1=100,
                    fillcolor="rgba(148, 103, 189, 0.15)",
                    line_width=0,
                    annotation_text="高风险区",
                    annotation_position="right",
                )

                fig_shutdown_risk.update_layout(
                    height=280,
                    hovermode="x unified",
                    xaxis_title="时间 (天)",
                    yaxis_title="停机风险 (%)",
                    yaxis_range=[0, 105],
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                )
                st.plotly_chart(fig_shutdown_risk, use_container_width=True)

        st.divider()

        with st.expander("🔍 策略详情查看", expanded=False):
            st.subheader("查看单个策略的详细信息")

            detail_options = [s["id"] for s in strategies]
            detail_labels = {s["id"]: s["name"] for s in strategies}

            selected_detail_id = st.selectbox(
                "选择策略",
                options=detail_options,
                format_func=lambda x: detail_labels.get(x, str(x)),
                key="strategy_detail_select",
            )

            if selected_detail_id:
                detail = get_strategy(selected_detail_id)
                if detail:
                    st.markdown(f"### {detail['name']}")
                    st.caption(f"ID: {detail['id']} | 类型: {detail.get('strategy_type', '')}")

                    if detail.get("description"):
                        st.write(f"**描述：** {detail['description']}")

                    if detail.get("decision_reason"):
                        st.markdown("**📝 决策理由**")
                        st.info(detail["decision_reason"])

                    if detail.get("metrics"):
                        st.markdown("**📊 关键指标**")
                        metrics_data = []
                        for key, value in detail["metrics"].items():
                            metrics_data.append({
                                "指标": get_metric_label(key),
                                "数值": format_metric_value(key, value),
                            })
                        st.dataframe(pd.DataFrame(metrics_data), use_container_width=True, hide_index=True)

                    if detail.get("risk_actions"):
                        st.markdown("**🚨 风险处置动作**")
                        priority_colors = {
                            "critical": "#9400d3",
                            "high": "#d62728",
                            "medium": "#ff7f0e",
                            "low": "#2ca02c",
                        }
                        priority_labels_map = {
                            "critical": "紧急", "high": "高优先级",
                            "medium": "中优先级", "low": "低优先级",
                        }
                        for action in detail["risk_actions"]:
                            prio = action.get("priority", "medium")
                            color = priority_colors.get(prio, "#7f7f7f")
                            label = priority_labels_map.get(prio, "未知")
                            with st.expander(
                                f"{'🔴' if prio == 'critical' else '🟠' if prio == 'high' else '🟡' if prio == 'medium' else '🟢'} "
                                f"{action.get('action_type', '')}: {action.get('action_description', '')[:50]}...",
                                expanded=False,
                            ):
                                st.markdown(f"<span style='color:{color};font-weight:bold;'>优先级：{label}</span>",
                                            unsafe_allow_html=True)
                                st.write(f"**类型：** {action.get('action_type', '')}")
                                st.write(f"**描述：** {action.get('action_description', '')}")
                                if action.get("start_hour") is not None and action.get("end_hour") is not None:
                                    st.write(f"**时间窗口：** 第 {action['start_hour']:.1f}h - 第 {action['end_hour']:.1f}h")

                    if detail.get("simulation_results"):
                        st.markdown("**📈 模拟曲线**")
                        df_detail = pd.DataFrame(detail["simulation_results"])

                        fig_detail = make_subplots(
                            rows=3, cols=1,
                            shared_xaxes=True,
                            vertical_spacing=0.08,
                            subplot_titles=("蓄水量 (m³)", "闸门开启比例 (%)", "磨坊运行状态"),
                            row_heights=[0.4, 0.3, 0.3],
                        )

                        has_data = len(df_detail) > 0
                        max_hour = df_detail["time_hour"].max() if has_data else 0
                        use_days = max_hour > 48
                        x_values = df_detail["time_hour"] / 24 if use_days else df_detail["time_hour"]
                        x_label = "时间 (天)" if use_days else "时间 (小时)"

                        fig_detail.add_trace(
                            go.Scatter(x=x_values, y=df_detail["water_volume"],
                                       name="蓄水量", line=dict(color="#2ca02c", width=2)),
                            row=1, col=1,
                        )
                        fig_detail.add_hline(
                            y=st.session_state["reservoir_capacity"],
                            line_dash="dash", line_color="red",
                            row=1, col=1,
                        )

                        fig_detail.add_trace(
                            go.Scatter(x=x_values, y=df_detail["gate_open_ratio"],
                                       name="闸门比例", line=dict(color="#9467bd", width=2)),
                            row=2, col=1,
                        )

                        mill_states = [100 if m else 0 for m in df_detail.get("mill_running", [])]
                        fig_detail.add_trace(
                            go.Scatter(x=x_values, y=mill_states,
                                       name="磨坊运行", fill="tozeroy",
                                       line=dict(color="#ff7f0e", width=0),
                                       fillcolor="rgba(255, 127, 14, 0.3)"),
                            row=3, col=1,
                        )
                        fig_detail.update_yaxes(range=[0, 105], row=3, col=1)

                        fig_detail.update_layout(
                            height=500,
                            hovermode="x unified",
                            showlegend=False,
                        )
                        fig_detail.update_xaxes(title_text=x_label, row=3, col=1)

                        st.plotly_chart(fig_detail, use_container_width=True)

                    col_d1, col_d2 = st.columns(2)
                    with col_d1:
                        if st.button("🗑️ 删除此策略", use_container_width=True, key="delete_strategy_btn"):
                            delete_strategy(selected_detail_id)
                            st.success("策略已删除")
                            st.rerun()
                    with col_d2:
                        st.caption("删除后不可恢复")

        st.divider()
        st.caption("💡 提示：您可以在「多日优化排程」和「风险预警决策」标签页完成分析后，回到此处保存策略并进行对比复盘")
