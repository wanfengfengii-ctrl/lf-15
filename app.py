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


tab1, tab2, tab3, tab4, tab5 = st.tabs(["📊 模拟结果", "🌊 潮位数据", "⚙️ 磨坊计划", "⚖️ 方案对比", "📅 多日优化排程"])

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
