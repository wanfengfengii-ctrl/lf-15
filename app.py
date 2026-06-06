import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
from datetime import datetime

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
    generate_default_tide_records,
    generate_default_mill_schedule,
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


tab1, tab2, tab3, tab4 = st.tabs(["📊 模拟结果", "🌊 潮位数据", "⚙️ 磨坊计划", "⚖️ 方案对比"])

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

        results, gate_schedule, warnings = run_simulation(
            params, tide_records, mill_schedule
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

    st.info("录入每日潮位时间序列数据。时间必须连续，单位为小时（0-24）。")

    if "tide_records" not in st.session_state:
        st.session_state["tide_records"] = generate_default_tide_records()

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

    st.info("设置计划的磨粉时段。水位不足时，磨坊将无法运行。")

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

    if st.button("✅ 更新磨坊计划", use_container_width=True):
        schedule = edited_mill_df.to_dict("records")
        valid = True
        msg = ""
        for i, s in enumerate(schedule):
            if s["start_hour"] >= s["end_hour"]:
                valid = False
                msg = f"第 {i+1} 个时段的开始时间必须小于结束时间"
                break
            if s["start_hour"] < 0 or s["end_hour"] > 24:
                valid = False
                msg = f"第 {i+1} 个时段的时间必须在 0-24 小时范围内"
                break

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
