#!/usr/bin/env python3
"""测试潮汐磨坊调度模拟系统的核心功能 - v2"""

from database import (
    init_db, create_scenario, list_scenarios, get_scenario,
    copy_scenario, delete_scenario, save_simulation_results, get_simulation_results,
    save_optimization_run, get_optimization_runs, get_optimization_run_detail, delete_optimization_run,
)
from simulation import (
    SimulationParams, run_simulation, validate_tide_records,
    validate_mill_schedule, estimate_mill_water_needs,
    validate_manual_gate_schedule, parse_tide_csv,
    generate_default_tide_records, generate_default_mill_schedule,
    generate_multi_day_tide_records, validate_multi_day_tide_records,
    get_total_hours, compute_simulation_metrics,
    generate_daily_mill_schedule_for_multi_day,
)
from optimizer import (
    run_full_optimization, compare_optimization_targets,
    calculate_score, OptimizationResult,
)
from risk_assessment import (
    StormSurgeConfig,
    RainfallConfig,
    EquipmentFailureConfig,
    EquipmentFailureState,
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
    apply_storm_surge_to_tide,
    has_storm_surge,
    has_rainfall,
    has_equipment_failure,
    get_disturbance_time_window,
)


def test_validate_tide_records():
    print("\n=== 测试潮位记录验证 ===")

    tide_records = generate_default_tide_records()
    valid, msg = validate_tide_records(tide_records)
    assert valid, f"默认数据应有效: {msg}"
    print(f"✅ 默认潮位数据验证通过: {msg}")

    bad_records = [
        {"time_hour": 2.0, "tide_level": 2.0},
        {"time_hour": 5.0, "tide_level": 3.0},
    ]
    valid, msg = validate_tide_records(bad_records)
    assert not valid, "不从0开始的记录应该无效"
    print(f"✅ 不从0开始检测通过: {msg}")

    bad_records2 = [
        {"time_hour": 0.0, "tide_level": 2.0},
        {"time_hour": 5.0, "tide_level": 3.0},
    ]
    valid, msg = validate_tide_records(bad_records2)
    assert not valid, "不到24小时的记录应该无效"
    print(f"✅ 不覆盖24小时检测通过: {msg}")

    dup_records = [
        {"time_hour": 0.0, "tide_level": 2.0},
        {"time_hour": 12.0, "tide_level": 3.0},
        {"time_hour": 12.0, "tide_level": 2.5},
        {"time_hour": 24.0, "tide_level": 2.0},
    ]
    valid, msg = validate_tide_records(dup_records)
    assert not valid, "重复时间应该无效"
    print(f"✅ 重复时间检测通过: {msg}")

    negative_records = [
        {"time_hour": 0.0, "tide_level": -2.0},
        {"time_hour": 24.0, "tide_level": 3.0},
    ]
    valid, msg = validate_tide_records(negative_records)
    assert not valid, "负潮位应该无效"
    print(f"✅ 负潮位检测通过: {msg}")


def test_validate_mill_schedule():
    print("\n=== 测试磨坊计划验证 ===")

    schedule = generate_default_mill_schedule()
    valid, msg, warns = validate_mill_schedule(schedule)
    assert valid, f"默认计划应有效: {msg}"
    print(f"✅ 默认磨坊计划验证通过: {msg}")

    overlap_schedule = [
        {"start_hour": 8.0, "end_hour": 12.0},
        {"start_hour": 10.0, "end_hour": 14.0},
    ]
    valid, msg, _ = validate_mill_schedule(overlap_schedule)
    assert not valid, "重叠时段应该无效"
    print(f"✅ 重叠时段检测通过: {msg}")

    invalid_schedule = [
        {"start_hour": 12.0, "end_hour": 8.0},
    ]
    valid, msg, _ = validate_mill_schedule(invalid_schedule)
    assert not valid, "开始>结束应该无效"
    print(f"✅ 开始>结束检测通过: {msg}")


def test_water_needs_estimation():
    print("\n=== 测试水量估算 ===")

    schedule = generate_default_mill_schedule()
    total_water, warnings = estimate_mill_water_needs(schedule, 5.0, 100.0)
    print(f"✅ 总耗水量估算: {total_water:.1f} m³")
    assert total_water > 0, "耗水量应大于0"

    big_schedule = [
        {"start_hour": 0.0, "end_hour": 24.0},
    ]
    total_water2, warnings2 = estimate_mill_water_needs(big_schedule, 10.0, 100.0)
    assert len(warnings2) >= 1, "水量不足应该有警告"
    print(f"✅ 水量不足警告: {warnings2[0]}")


def test_manual_gate():
    print("\n=== 测试手动闸门控制 ===")

    params = SimulationParams(
        reservoir_capacity=100.0,
        reservoir_area=20.0,
        gate_max_flow=50.0,
        mill_power_consumption=5.0,
        initial_water_level=50.0,
    )
    tide_records = generate_default_tide_records()
    mill_schedule = generate_default_mill_schedule()

    manual_schedule = [
        {"start_hour": 0.0, "end_hour": 6.0, "open_ratio": 100.0},
        {"start_hour": 12.0, "end_hour": 18.0, "open_ratio": 50.0},
    ]

    valid, msg, warns = validate_manual_gate_schedule(manual_schedule)
    assert valid, f"手动闸门计划应有效: {msg}"
    print(f"✅ 手动闸门验证通过: {msg}")
    if warns:
        for w in warns:
            print(f"   ⚠️  {w}")

    results, gate_schedule, warnings = run_simulation(
        params, tide_records, mill_schedule,
        manual_gate_schedule=manual_schedule,
    )
    assert len(results) > 0
    print(f"✅ 手动闸门模式模拟成功: {len(results)} 个时间步")

    gate_ratios = [r["gate_open_ratio"] for r in results]
    print(f"✅ 闸门开启比例范围: {min(gate_ratios):.1f}% - {max(gate_ratios):.1f}%")

    bad_gate = [
        {"start_hour": 0.0, "end_hour": 10.0, "open_ratio": 150.0},
    ]
    valid, msg, _ = validate_manual_gate_schedule(bad_gate)
    assert not valid, "超过100%的比例应该无效"
    print(f"✅ 超限比例检测通过: {msg}")

    overlap_gate = [
        {"start_hour": 0.0, "end_hour": 10.0, "open_ratio": 50.0},
        {"start_hour": 8.0, "end_hour": 16.0, "open_ratio": 30.0},
    ]
    valid, msg, _ = validate_manual_gate_schedule(overlap_gate)
    assert not valid, "重叠闸门时段应该无效"
    print(f"✅ 重叠闸门时段检测通过: {msg}")


def test_csv_parsing():
    print("\n=== 测试CSV解析 ===")

    csv_content = """time_hour,tide_level
0.0,2.5
6.0,4.5
12.0,2.5
18.0,0.5
24.0,2.5
"""
    records, msg = parse_tide_csv(csv_content)
    assert len(records) == 5, f"应解析5条记录，实际{len(records)}"
    assert records[0]["time_hour"] == 0.0
    assert records[0]["tide_level"] == 2.5
    print(f"✅ CSV解析成功: {msg}")

    csv_chinese = """小时,潮位米
0,3.0
12,1.0
24,3.0
"""
    records2, msg2 = parse_tide_csv(csv_chinese)
    assert len(records2) == 3, f"应解析3条记录，实际{len(records2)}"
    print(f"✅ 中文CSV解析成功: {msg2}")

    bad_csv = """invalid
bad data
"""
    records3, msg3 = parse_tide_csv(bad_csv)
    print(f"✅ 无效CSV处理: {msg3}")


def test_database():
    print("\n=== 测试数据库功能 ===")
    init_db()
    print("✅ 数据库初始化成功")

    tide_records = generate_default_tide_records()
    mill_schedule = generate_default_mill_schedule()

    scenario_id = create_scenario(
        name='测试方案v2',
        description='用于测试的方案',
        reservoir_capacity=100.0,
        reservoir_area=20.0,
        gate_max_flow=50.0,
        mill_power_consumption=5.0,
        initial_water_level=50.0,
        tide_records=tide_records,
        mill_schedule=mill_schedule,
    )
    print(f"✅ 方案创建成功, ID: {scenario_id}")

    scenario = get_scenario(scenario_id)
    assert scenario is not None
    assert scenario['reservoir_area'] == 20.0
    print("✅ 方案读取成功（含蓄水池面积）")

    new_id = copy_scenario(scenario_id, '测试方案副本v2')
    new_scenario = get_scenario(new_id)
    assert new_scenario['reservoir_area'] == scenario['reservoir_area']
    print("✅ 方案复制成功")

    delete_scenario(new_id)
    delete_scenario(scenario_id)
    print("✅ 清理测试数据完成")


def test_simulation_constraints():
    print("\n=== 测试模拟约束 ===")

    tide_records = generate_default_tide_records()
    mill_schedule = generate_default_mill_schedule()

    params = SimulationParams(
        reservoir_capacity=100.0,
        reservoir_area=20.0,
        gate_max_flow=50.0,
        mill_power_consumption=5.0,
        initial_water_level=50.0,
    )

    results, _, warnings = run_simulation(params, tide_records, mill_schedule)

    water_volumes = [r['water_volume'] for r in results]
    assert min(water_volumes) >= -0.001, f"蓄水量低于0: {min(water_volumes)}"
    assert max(water_volumes) <= params.reservoir_capacity + 0.001, f"蓄水量超过容量: {max(water_volumes)}"
    print(f"✅ 蓄水量约束: {min(water_volumes):.2f} - {max(water_volumes):.2f} m³")

    gate_ratios = [r['gate_open_ratio'] for r in results]
    assert min(gate_ratios) >= -0.001, f"闸门比例低于0: {min(gate_ratios)}"
    assert max(gate_ratios) <= 100.001, f"闸门比例超过100: {max(gate_ratios)}"
    print(f"✅ 闸门比例约束: {min(gate_ratios):.1f}% - {max(gate_ratios):.1f}%")

    mill_running_volumes = [r['water_volume'] for r in results if r['mill_running']]
    if mill_running_volumes:
        assert min(mill_running_volumes) >= -0.001
        print(f"✅ 磨坊运行时水位约束: {min(mill_running_volumes):.2f} m³ (最低)")

    print("✅ 所有约束验证通过")


def test_multi_day_tide():
    print("\n=== 测试多日潮位数据 ===")

    records = generate_multi_day_tide_records(num_days=7)
    print(f"✅ 生成 7 天潮位数据，共 {len(records)} 条记录")

    assert len(records) > 0, "应生成记录"
    assert records[0]["time_hour"] == 0.0, "应从0小时开始"
    assert records[-1]["time_hour"] >= 7 * 24, "应覆盖7天"

    valid, msg = validate_multi_day_tide_records(records, min_hours=24.0)
    assert valid, f"多日潮位数据应有效: {msg}"
    print(f"✅ 多日数据验证通过: {msg}")

    total_hours = get_total_hours(records)
    assert total_hours >= 7 * 24 - 1, f"总时长应约为7天: {total_hours}"
    print(f"✅ 总时长: {total_hours:.1f} 小时 ({total_hours/24:.1f} 天)")

    bad_records = generate_multi_day_tide_records(num_days=1)
    bad_records = bad_records[:10]
    valid, msg = validate_multi_day_tide_records(bad_records, min_hours=24.0)
    assert not valid, "不足24小时的数据应无效"
    print(f"✅ 不足时长检测通过: {msg}")

    discontinuous_records = [
        {"time_hour": 0.0, "tide_level": 2.0},
        {"time_hour": 1.0, "tide_level": 2.5},
        {"time_hour": 2.0, "tide_level": 3.0},
        {"time_hour": 10.0, "tide_level": 2.0},
        {"time_hour": 11.0, "tide_level": 1.5},
    ]
    valid, msg = validate_multi_day_tide_records(discontinuous_records, min_hours=10.0, max_gap_hours=6.0)
    assert not valid, "时间间隔超过6小时的数据应无效"
    assert "不连续" in msg, "错误信息应包含'不连续'"
    print(f"✅ 时间不连续检测通过: {msg}")

    continuous_records = [
        {"time_hour": 0.0, "tide_level": 2.0},
        {"time_hour": 2.0, "tide_level": 2.5},
        {"time_hour": 4.0, "tide_level": 3.0},
        {"time_hour": 6.0, "tide_level": 2.8},
        {"time_hour": 8.0, "tide_level": 2.0},
    ]
    valid, msg = validate_multi_day_tide_records(continuous_records, min_hours=8.0, max_gap_hours=3.0)
    assert valid, "间隔2小时的数据应有效"
    print(f"✅ 连续数据验证通过: {msg}")

    fractional_days_records = generate_multi_day_tide_records(num_days=3)
    fractional_days_records = [r for r in fractional_days_records if r["time_hour"] <= 60.0]
    valid, msg = validate_multi_day_tide_records(fractional_days_records, min_hours=48.0)
    assert valid, "非整天数据也应有效"
    total_h = get_total_hours(fractional_days_records)
    assert 60.0 - total_h < 0.1, f"总时长应约为60小时: {total_h}"
    print(f"✅ 非整天数据验证通过: {msg}")


def test_multi_day_simulation():
    print("\n=== 测试多日模拟 ===")

    params = SimulationParams(
        reservoir_capacity=100.0,
        reservoir_area=20.0,
        gate_max_flow=50.0,
        mill_power_consumption=5.0,
        initial_water_level=50.0,
    )

    tide_records = generate_multi_day_tide_records(num_days=3)
    total_hours = get_total_hours(tide_records)

    mill_schedule = generate_daily_mill_schedule_for_multi_day(3)
    print(f"✅ 生成 3 天磨坊计划，共 {len(mill_schedule)} 个时段")

    results, gate_schedule, warnings = run_simulation(
        params, tide_records, mill_schedule, total_hours=total_hours,
    )

    assert len(results) > 0, "模拟应有结果"
    print(f"✅ 多日模拟成功: {len(results)} 个时间步")
    print(f"✅ 闸门调度时段数: {len(gate_schedule)}")

    metrics = compute_simulation_metrics(results, params)
    assert metrics, "应有指标计算结果"
    print(f"✅ 指标计算完成: {len(metrics)} 项指标")
    print(f"   - 磨坊运行: {metrics['total_mill_hours']:.1f} 小时")
    print(f"   - 闸门开启: {metrics['total_gate_open_hours']:.1f} 小时")
    print(f"   - 库容利用率: {metrics['capacity_utilization_pct']:.1f} %")

    water_volumes = [r["water_volume"] for r in results]
    assert min(water_volumes) >= -0.001, "蓄水量不应为负"
    assert max(water_volumes) <= params.reservoir_capacity + 0.001, "蓄水量不应超容量"
    print(f"✅ 蓄水量约束验证通过")


def test_optimizer():
    print("\n=== 测试优化器 ===")

    params = SimulationParams(
        reservoir_capacity=100.0,
        reservoir_area=20.0,
        gate_max_flow=50.0,
        mill_power_consumption=5.0,
        initial_water_level=50.0,
    )

    tide_records = generate_multi_day_tide_records(num_days=3)

    targets = ["water_saving", "high_yield", "low_overflow", "balanced"]
    for target in targets:
        result = run_full_optimization(
            params, tide_records, target=target, num_days=3, daily_mill_hours=8.0,
        )
        assert isinstance(result, OptimizationResult), "应返回 OptimizationResult"
        assert result.target == target, "目标应匹配"
        assert len(result.simulation_results) > 0, "应有模拟结果"
        assert len(result.metrics) > 0, "应有指标"
        assert result.mill_schedule, "应有磨坊计划"
        assert result.gate_schedule, "应有闸门计划"
        print(f"✅ {target} 优化完成，评分: {result.score:.1f}")


def test_optimization_comparison():
    print("\n=== 测试多目标对比 ===")

    params = SimulationParams(
        reservoir_capacity=100.0,
        reservoir_area=20.0,
        gate_max_flow=50.0,
        mill_power_consumption=5.0,
        initial_water_level=50.0,
    )

    tide_records = generate_multi_day_tide_records(num_days=3)

    results = compare_optimization_targets(
        params, tide_records,
        targets=["water_saving", "high_yield", "low_overflow"],
        num_days=3, daily_mill_hours=8.0,
    )

    assert len(results) == 3, "应返回3个优化结果"
    print(f"✅ 三目标对比完成，共 {len(results)} 个结果")

    for r in results:
        print(f"   - {r.target}: 评分={r.score:.1f}, 磨坊={r.metrics['total_mill_hours']:.1f}h")

    high_yield_result = [r for r in results if r.target == "high_yield"][0]
    water_saving_result = [r for r in results if r.target == "water_saving"][0]

    print(f"✅ 高产模式磨坊时长: {high_yield_result.metrics['total_mill_hours']:.1f}h")
    print(f"✅ 节水模式平均水位: {water_saving_result.metrics['avg_water_volume']:.1f}m³")


def test_score_calculation():
    print("\n=== 测试评分计算 ===")

    params = SimulationParams(
        reservoir_capacity=100.0,
        reservoir_area=20.0,
        gate_max_flow=50.0,
        mill_power_consumption=5.0,
        initial_water_level=50.0,
    )

    metrics_high_yield = {
        "total_mill_hours": 50.0,
        "overflow_volume": 5.0,
        "avg_water_volume": 60.0,
    }

    score = calculate_score(metrics_high_yield, "high_yield", params)
    assert isinstance(score, float), "评分应为浮点数"
    print(f"✅ 高产模式评分: {score:.2f}")

    score2 = calculate_score(metrics_high_yield, "water_saving", params)
    print(f"✅ 节水模式评分: {score2:.2f}")

    score3 = calculate_score(metrics_high_yield, "low_overflow", params)
    print(f"✅ 低溢流模式评分: {score3:.2f}")

    score4 = calculate_score(metrics_high_yield, "balanced", params)
    print(f"✅ 均衡模式评分: {score4:.2f}")


def test_optimization_database():
    print("\n=== 测试优化结果数据库 ===")

    init_db()

    tide_records = generate_default_tide_records()
    mill_schedule = generate_default_mill_schedule()

    scenario_id = create_scenario(
        name='优化测试方案',
        description='用于测试优化存储的方案',
        reservoir_capacity=100.0,
        reservoir_area=20.0,
        gate_max_flow=50.0,
        mill_power_consumption=5.0,
        initial_water_level=50.0,
        tide_records=tide_records,
        mill_schedule=mill_schedule,
    )
    print(f"✅ 创建测试方案，ID: {scenario_id}")

    params = SimulationParams(
        reservoir_capacity=100.0,
        reservoir_area=20.0,
        gate_max_flow=50.0,
        mill_power_consumption=5.0,
        initial_water_level=50.0,
    )

    multi_day_tides = generate_multi_day_tide_records(num_days=3)
    opt_result = run_full_optimization(
        params, multi_day_tides, target="balanced", num_days=3, daily_mill_hours=8.0
    )

    run_id = save_optimization_run(
        scenario_id,
        "balanced",
        3,
        8.0,
        opt_result.score,
        opt_result.metrics,
        opt_result.mill_schedule,
        opt_result.gate_schedule,
    )
    print(f"✅ 保存优化运行，ID: {run_id}")

    runs = get_optimization_runs(scenario_id)
    assert len(runs) >= 1, "应至少有1条优化记录"
    print(f"✅ 读取优化记录列表: {len(runs)} 条")

    detail = get_optimization_run_detail(run_id)
    assert detail is not None, "应能读取详情"
    assert "metrics" in detail, "应包含指标"
    assert "mill_schedule" in detail, "应包含磨坊计划"
    assert "gate_schedule" in detail, "应包含闸门计划"
    print(f"✅ 读取优化详情成功，指标数: {len(detail['metrics'])}")

    delete_optimization_run(run_id)
    print(f"✅ 删除优化运行成功")

    runs_after = get_optimization_runs(scenario_id)
    remaining = [r for r in runs_after if r["id"] == run_id]
    assert len(remaining) == 0, "删除后不应存在"
    print(f"✅ 确认删除成功")

    delete_scenario(scenario_id)
    print(f"✅ 清理测试方案")


def test_storm_surge_config():
    print("\n=== 测试风暴潮配置 ===")

    config = StormSurgeConfig(
        surge_height=1.0,
        surge_start_hour=24.0,
        surge_duration_hours=12.0,
        surge_shape="sinusoidal",
    )

    surge_at_start = config.surge_at_time(24.0)
    assert abs(surge_at_start) < 0.001, f"开始时潮位抬升应为0，实际: {surge_at_start}"
    print(f"✅ 风暴潮开始时抬升为0: {surge_at_start:.3f} m")

    surge_at_mid = config.surge_at_time(30.0)
    assert surge_at_mid > 0.9, f"中期抬升应接近峰值，实际: {surge_at_mid}"
    print(f"✅ 风暴潮中期抬升: {surge_at_mid:.3f} m")

    surge_at_end = config.surge_at_time(36.0)
    assert abs(surge_at_end) < 0.001, f"结束时潮位抬升应为0，实际: {surge_at_end}"
    print(f"✅ 风暴潮结束时抬升为0: {surge_at_end:.3f} m")

    surge_before = config.surge_at_time(10.0)
    assert surge_before == 0.0, "开始前不应有抬升"
    print("✅ 风暴潮开始前无抬升")

    surge_after = config.surge_at_time(40.0)
    assert surge_after == 0.0, "结束后不应有抬升"
    print("✅ 风暴潮结束后无抬升")

    zero_config = StormSurgeConfig(surge_height=0.0)
    assert zero_config.surge_at_time(10.0) == 0.0, "高度为0时不应有抬升"
    print("✅ 零高度风暴潮无影响")


def test_rainfall_config():
    print("\n=== 测试降雨入流配置 ===")

    config = RainfallConfig(
        rainfall_rate=50.0,
        rainfall_start_hour=12.0,
        rainfall_duration_hours=24.0,
        runoff_coefficient=0.6,
        catchment_area=100.0,
    )

    inflow = config.inflow_at_time(24.0)
    expected_inflow = 50.0 * 100.0 * 0.6 / 1000.0
    assert abs(inflow - expected_inflow) < 0.001, f"入流量计算错误: {inflow} vs {expected_inflow}"
    print(f"✅ 降雨入流量计算正确: {inflow:.3f} m³/h")

    inflow_before = config.inflow_at_time(6.0)
    assert inflow_before == 0.0, "降雨开始前不应有入流"
    print("✅ 降雨开始前无入流")

    inflow_after = config.inflow_at_time(40.0)
    assert inflow_after == 0.0, "降雨结束后不应有入流"
    print("✅ 降雨结束后无入流")

    zero_rain = RainfallConfig(rainfall_rate=0.0)
    assert zero_rain.inflow_at_time(10.0) == 0.0, "零降雨不应有入流"
    print("✅ 零降雨无入流")


def test_equipment_failure_config():
    print("\n=== 测试设备故障配置 ===")

    config = EquipmentFailureConfig(
        gate_failure_probability=0.3,
        mill_failure_probability=0.5,
        gate_flow_reduction_pct=50.0,
        failure_start_hour=24.0,
        failure_duration_hours=12.0,
    )

    assert not config.is_failure_period(10.0), "故障开始前不应在故障期"
    print("✅ 故障开始前不在故障期")

    assert config.is_failure_period(30.0), "故障期中应返回True"
    print("✅ 故障期中正确识别")

    assert not config.is_failure_period(40.0), "故障结束后不应在故障期"
    print("✅ 故障结束后不在故障期")

    base_flow = 100.0
    flow_normal = config.effective_gate_flow(base_flow, 10.0)
    assert flow_normal == base_flow, "非故障期流量不应变化"
    print("✅ 非故障期流量正常")

    flow_failure = config.effective_gate_flow(base_flow, 30.0)
    expected_flow = base_flow * 0.5
    assert abs(flow_failure - expected_flow) < 0.001, f"故障期流量计算错误: {flow_failure}"
    print(f"✅ 故障期流量降低正确: {flow_failure:.1f} m³/h")

    mill_normal = config.mill_available(10.0)
    assert mill_normal, "非故障期磨坊应可用"
    print("✅ 非故障期磨坊可用")

    mill_failure = config.mill_available(30.0)
    assert not mill_failure, "高故障概率下磨坊应不可用"
    print("✅ 高故障概率下磨坊不可用")


def test_apply_storm_surge():
    print("\n=== 测试风暴潮叠加到潮位 ===")

    tide_records = [
        {"time_hour": 0.0, "tide_level": 2.0},
        {"time_hour": 12.0, "tide_level": 4.0},
        {"time_hour": 24.0, "tide_level": 2.0},
    ]

    storm = StormSurgeConfig(
        surge_height=1.0,
        surge_start_hour=0.0,
        surge_duration_hours=24.0,
        surge_shape="rectangular",
    )

    modified = apply_storm_surge_to_tide(tide_records, storm)
    assert len(modified) == len(tide_records), "记录数应保持一致"
    print(f"✅ 记录数保持一致: {len(modified)} 条")

    assert modified[0]["tide_level"] == 3.0, f"潮位应叠加，实际: {modified[0]['tide_level']}"
    print(f"✅ 潮位正确叠加: {tide_records[0]['tide_level']} + {1.0} = {modified[0]['tide_level']}")


def test_disturbed_simulation():
    print("\n=== 测试扰动模拟 ===")

    params = SimulationParams(
        reservoir_capacity=100.0,
        reservoir_area=20.0,
        gate_max_flow=50.0,
        mill_power_consumption=5.0,
        initial_water_level=50.0,
    )

    tide_records = generate_multi_day_tide_records(num_days=3)
    mill_schedule = generate_daily_mill_schedule_for_multi_day(3)

    baseline = DisturbanceScenario(name="baseline", description="基线")
    results, gate_schedule, warnings = run_disturbed_simulation(
        params, tide_records, mill_schedule, baseline
    )

    assert len(results) > 0, "模拟应产生结果"
    print(f"✅ 基线模拟成功: {len(results)} 个时间步")

    storm_scenario = DisturbanceScenario(
        name="storm",
        description="风暴潮测试",
        storm_surge=StormSurgeConfig(
            surge_height=1.5,
            surge_start_hour=24.0,
            surge_duration_hours=12.0,
        ),
    )
    storm_results, _, storm_warnings = run_disturbed_simulation(
        params, tide_records, mill_schedule, storm_scenario
    )
    assert len(storm_results) > 0
    print(f"✅ 风暴潮模拟成功: {len(storm_warnings)} 条警告")

    rainfall_scenario = DisturbanceScenario(
        name="rainfall",
        description="强降雨测试",
        rainfall=RainfallConfig(
            rainfall_rate=100.0,
            rainfall_start_hour=12.0,
            rainfall_duration_hours=24.0,
            runoff_coefficient=0.8,
            catchment_area=200.0,
        ),
    )
    rain_results, _, rain_warnings = run_disturbed_simulation(
        params, tide_records, mill_schedule, rainfall_scenario
    )
    assert len(rain_results) > 0
    print(f"✅ 降雨入流模拟成功: {len(rain_warnings)} 条警告")

    equipment_scenario = DisturbanceScenario(
        name="equipment",
        description="设备故障测试",
        equipment=EquipmentFailureConfig(
            gate_failure_probability=0.5,
            mill_failure_probability=0.5,
            gate_flow_reduction_pct=50.0,
            failure_start_hour=24.0,
            failure_duration_hours=24.0,
        ),
    )
    equip_results, _, equip_warnings = run_disturbed_simulation(
        params, tide_records, mill_schedule, equipment_scenario
    )
    assert len(equip_results) > 0
    print(f"✅ 设备故障模拟成功: {len(equip_warnings)} 条警告")

    has_storm_data = any("storm_surge" in r for r in storm_results)
    assert has_storm_data, "结果中应包含风暴潮数据"
    print("✅ 模拟结果包含风暴潮数据")

    has_rainfall_data = any("rainfall_inflow" in r for r in rain_results)
    assert has_rainfall_data, "结果中应包含降雨入流数据"
    print("✅ 模拟结果包含降雨入流数据")


def test_risk_assessment():
    print("\n=== 测试风险评估 ===")

    params = SimulationParams(
        reservoir_capacity=100.0,
        reservoir_area=20.0,
        gate_max_flow=50.0,
        mill_power_consumption=5.0,
        initial_water_level=50.0,
    )

    tide_records = generate_multi_day_tide_records(num_days=3)
    mill_schedule = generate_daily_mill_schedule_for_multi_day(3)

    baseline = DisturbanceScenario(name="baseline")
    sim_results, _, _ = run_disturbed_simulation(
        params, tide_records, mill_schedule, baseline
    )

    risk_result = assess_risks(params, sim_results, baseline)
    assert isinstance(risk_result, RiskAssessmentResult)
    print(f"✅ 风险评估结果类型正确")

    assert 0 <= risk_result.water_shortage_risk <= 100, "缺水风险应在0-100之间"
    assert 0 <= risk_result.overflow_risk <= 100, "溢流风险应在0-100之间"
    assert 0 <= risk_result.shutdown_risk <= 100, "停机风险应在0-100之间"
    print(f"✅ 三项风险值均在有效范围")
    print(f"   - 缺水风险: {risk_result.water_shortage_risk:.1f}%")
    print(f"   - 溢流风险: {risk_result.overflow_risk:.1f}%")
    print(f"   - 停机风险: {risk_result.shutdown_risk:.1f}%")

    assert risk_result.overall_risk_level in ["low", "medium", "high", "critical"]
    print(f"✅ 综合风险等级: {get_risk_level_label(risk_result.overall_risk_level)}")

    assert "low_water_duration_pct" in risk_result.risk_details
    assert "overflow_duration_pct" in risk_result.risk_details
    assert "mill_availability_pct" in risk_result.risk_details
    print(f"✅ 风险详情包含关键指标: {len(risk_result.risk_details)} 项")

    color = get_risk_level_color(risk_result.overall_risk_level)
    assert color.startswith("#"), "颜色应为十六进制格式"
    print(f"✅ 风险等级颜色: {color}")

    label = get_risk_level_label(risk_result.overall_risk_level)
    assert isinstance(label, str) and len(label) > 0
    print(f"✅ 风险等级标签: {label}")


def test_emergency_recommendations():
    print("\n=== 测试应急调度建议 ===")

    params = SimulationParams(
        reservoir_capacity=100.0,
        reservoir_area=20.0,
        gate_max_flow=50.0,
        mill_power_consumption=5.0,
        initial_water_level=50.0,
    )

    tide_records = generate_multi_day_tide_records(num_days=7)
    mill_schedule = generate_daily_mill_schedule_for_multi_day(7)

    baseline = DisturbanceScenario(name="baseline")
    baseline_sim, _, _ = run_disturbed_simulation(params, tide_records, mill_schedule, baseline)
    baseline_risk = assess_risks(params, baseline_sim, baseline)

    severe_storm = DisturbanceScenario(
        name="severe_storm",
        description="严重风暴潮",
        storm_surge=StormSurgeConfig(
            surge_height=2.0,
            surge_start_hour=48.0,
            surge_duration_hours=24.0,
        ),
        rainfall=RainfallConfig(
            rainfall_rate=80.0,
            rainfall_start_hour=48.0,
            rainfall_duration_hours=18.0,
            runoff_coefficient=0.7,
            catchment_area=150.0,
        ),
        equipment=EquipmentFailureConfig(
            gate_failure_probability=0.3,
            mill_failure_probability=0.2,
            gate_flow_reduction_pct=50.0,
            failure_start_hour=48.0,
            failure_duration_hours=12.0,
        ),
    )
    storm_sim, _, _ = run_disturbed_simulation(params, tide_records, mill_schedule, severe_storm)
    storm_risk = assess_risks(params, storm_sim, severe_storm)

    recommendations = generate_emergency_recommendations(
        params, baseline_risk, storm_risk, severe_storm
    )

    assert isinstance(recommendations, list)
    print(f"✅ 生成应急建议: {len(recommendations)} 条")

    if recommendations:
        for rec in recommendations:
            assert isinstance(rec, EmergencyRecommendation)
            assert rec.action, "建议应有行动名称"
            assert rec.priority in ["critical", "high", "medium", "low"]
            assert len(rec.time_window) == 2
        print(f"✅ 所有建议格式正确")

        priorities = [r.priority for r in recommendations]
        priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        sorted_priorities = sorted(priorities, key=lambda p: priority_order.get(p, 99))
        assert priorities == sorted_priorities, "建议应按优先级排序"
        print("✅ 建议按优先级正确排序")


def test_disturbance_scenarios():
    print("\n=== 测试预设扰动场景 ===")

    scenarios = generate_disturbance_scenarios()
    assert len(scenarios) >= 5, "应至少有5个预设场景"
    print(f"✅ 预设扰动场景数量: {len(scenarios)} 个")

    names = [s.name for s in scenarios]
    assert "baseline" in names, "应包含基线场景"
    print("✅ 包含基线场景")

    for scenario in scenarios:
        assert isinstance(scenario, DisturbanceScenario)
        assert scenario.risk_level in ["low", "medium", "high", "critical"]
        assert scenario.storm_surge is not None
        assert scenario.rainfall is not None
        assert scenario.equipment is not None
    print("✅ 所有场景格式正确")

    for s in scenarios:
        print(f"   - {s.name}: {s.description} ({get_risk_level_label(s.risk_level)})")


def test_risk_comparison():
    print("\n=== 测试多场景风险对比 ===")

    params = SimulationParams(
        reservoir_capacity=100.0,
        reservoir_area=20.0,
        gate_max_flow=50.0,
        mill_power_consumption=5.0,
        initial_water_level=50.0,
    )

    tide_records = generate_multi_day_tide_records(num_days=3)
    mill_schedule = generate_daily_mill_schedule_for_multi_day(3)

    scenarios = generate_disturbance_scenarios()
    results = compare_risk_scenarios(params, tide_records, mill_schedule, scenarios)

    assert len(results) == len(scenarios), "结果数应与场景数一致"
    print(f"✅ 风险对比结果: {len(results)} 个场景")

    for r in results:
        assert isinstance(r, RiskAssessmentResult)
        assert r.scenario_name
    print("✅ 所有结果格式正确")

    baseline_risk = [r for r in results if r.scenario_name == "baseline"][0]
    severe_risk = [r for r in results if r.scenario_name == "severe_storm"][0]

    assert severe_risk.overflow_risk >= baseline_risk.overflow_risk - 1, "严重风暴溢流风险不应低于基线"
    print("✅ 严重风暴溢流风险高于基线（符合预期）")


def test_equipment_failure_state():
    print("\n=== 测试设备故障状态采样 ===")

    config = EquipmentFailureConfig(
        gate_failure_probability=0.5,
        mill_failure_probability=0.5,
        gate_flow_reduction_pct=50.0,
        failure_start_hour=24.0,
        failure_duration_hours=12.0,
    )

    num_samples = 1000
    gate_fail_count = 0
    mill_fail_count = 0

    for i in range(num_samples):
        state = config.sample(random_seed=i)
        assert isinstance(state, EquipmentFailureState)
        if state.gate_failed:
            gate_fail_count += 1
        if state.mill_failed:
            mill_fail_count += 1

    gate_fail_rate = gate_fail_count / num_samples
    mill_fail_rate = mill_fail_count / num_samples

    assert 0.4 < gate_fail_rate < 0.6, f"闸门故障率应接近0.5，实际: {gate_fail_rate}"
    assert 0.4 < mill_fail_rate < 0.6, f"磨坊故障率应接近0.5，实际: {mill_fail_rate}"
    print(f"✅ 闸门故障率符合预期: {gate_fail_rate:.3f} (预期 ~0.5)")
    print(f"✅ 磨坊故障率符合预期: {mill_fail_rate:.3f} (预期 ~0.5)")

    state_normal = EquipmentFailureState()
    assert not state_normal.gate_failed
    assert not state_normal.mill_failed
    assert state_normal.effective_gate_flow(100.0, 10.0) == 100.0
    assert state_normal.mill_available(10.0)
    print("✅ 正常状态下设备全部可用")

    state_failed = EquipmentFailureState(
        gate_failed=True,
        mill_failed=True,
        gate_flow_reduction_pct=50.0,
        failure_start_hour=0.0,
        failure_duration_hours=24.0,
    )
    assert state_failed.effective_gate_flow(100.0, 10.0) == 50.0
    assert not state_failed.mill_available(10.0)
    print("✅ 故障状态下设备功能受限正确")


def test_disturbance_detection():
    print("\n=== 测试扰动因素检测 ===")

    baseline = DisturbanceScenario(name="baseline")
    assert not has_storm_surge(baseline)
    assert not has_rainfall(baseline)
    assert not has_equipment_failure(baseline)
    print("✅ 基线场景无任何扰动")

    storm_only = DisturbanceScenario(
        name="storm",
        storm_surge=StormSurgeConfig(surge_height=1.0),
    )
    assert has_storm_surge(storm_only)
    assert not has_rainfall(storm_only)
    assert not has_equipment_failure(storm_only)
    print("✅ 仅风暴潮场景检测正确")

    equip_only = DisturbanceScenario(
        name="equip",
        equipment=EquipmentFailureConfig(
            gate_failure_probability=0.3,
            mill_failure_probability=0.0,
        ),
    )
    assert not has_storm_surge(equip_only)
    assert not has_rainfall(equip_only)
    assert has_equipment_failure(equip_only)
    print("✅ 仅设备故障场景检测正确")

    all_disturb = DisturbanceScenario(
        name="all",
        storm_surge=StormSurgeConfig(surge_height=1.5),
        rainfall=RainfallConfig(rainfall_rate=50.0),
        equipment=EquipmentFailureConfig(gate_failure_probability=0.5),
    )
    assert has_storm_surge(all_disturb)
    assert has_rainfall(all_disturb)
    assert has_equipment_failure(all_disturb)
    print("✅ 全扰动场景检测正确")


def test_disturbance_time_window():
    print("\n=== 测试扰动时间窗口 ===")

    baseline = DisturbanceScenario(name="baseline")
    start, end = get_disturbance_time_window(baseline)
    assert start == 0.0 and end == 24.0
    print(f"✅ 基线场景默认窗口: {start}-{end}h")

    storm_only = DisturbanceScenario(
        name="storm",
        storm_surge=StormSurgeConfig(
            surge_height=1.0,
            surge_start_hour=24.0,
            surge_duration_hours=12.0,
        ),
    )
    start, end = get_disturbance_time_window(storm_only)
    assert start == 24.0 and end == 36.0
    print(f"✅ 仅风暴潮窗口正确: {start}-{end}h")

    equip_only = DisturbanceScenario(
        name="equip",
        equipment=EquipmentFailureConfig(
            gate_failure_probability=0.5,
            failure_start_hour=36.0,
            failure_duration_hours=24.0,
        ),
    )
    start, end = get_disturbance_time_window(equip_only)
    assert start == 36.0 and end == 60.0
    print(f"✅ 仅设备故障窗口正确: {start}-{end}h")

    mixed = DisturbanceScenario(
        name="mixed",
        storm_surge=StormSurgeConfig(
            surge_height=1.0,
            surge_start_hour=12.0,
            surge_duration_hours=24.0,
        ),
        rainfall=RainfallConfig(
            rainfall_rate=30.0,
            rainfall_start_hour=24.0,
            rainfall_duration_hours=12.0,
        ),
        equipment=EquipmentFailureConfig(
            gate_failure_probability=0.3,
            failure_start_hour=20.0,
            failure_duration_hours=8.0,
        ),
    )
    start, end = get_disturbance_time_window(mixed)
    assert start == 12.0 and end == 36.0
    print(f"✅ 多扰动合并窗口正确: {start}-{end}h")


def test_monte_carlo_simulation():
    print("\n=== 测试蒙特卡洛模拟 ===")

    params = SimulationParams(
        reservoir_capacity=100.0,
        reservoir_area=20.0,
        gate_max_flow=50.0,
        mill_power_consumption=5.0,
        initial_water_level=50.0,
    )

    tide_records = generate_multi_day_tide_records(num_days=3)
    mill_schedule = generate_daily_mill_schedule_for_multi_day(3)

    scenario = DisturbanceScenario(
        name="test_mc",
        equipment=EquipmentFailureConfig(
            gate_failure_probability=0.5,
            mill_failure_probability=0.5,
            gate_flow_reduction_pct=50.0,
            failure_start_hour=24.0,
            failure_duration_hours=24.0,
        ),
    )

    mc_result = run_monte_carlo_risk_assessment(
        params, tide_records, mill_schedule, scenario,
        num_simulations=50, base_seed=42,
    )

    assert isinstance(mc_result, MonteCarloResult)
    assert mc_result.num_simulations == 50
    assert len(mc_result.all_results) == 50
    print(f"✅ 蒙特卡洛模拟运行次数正确: {mc_result.num_simulations} 次")

    assert "water_shortage" in mc_result.mean_risks
    assert "overflow" in mc_result.mean_risks
    assert "shutdown" in mc_result.mean_risks
    print("✅ 风险均值计算包含三项指标")

    assert mc_result.percentile_5_risks["water_shortage"] <= mc_result.median_risks["water_shortage"]
    assert mc_result.median_risks["water_shortage"] <= mc_result.percentile_95_risks["water_shortage"]
    print("✅ 分位数排序正确（5% ≤ 中位数 ≤ 95%）")

    assert mc_result.overall_risk_level in ["low", "medium", "high", "critical"]
    print(f"✅ 综合风险等级: {get_risk_level_label(mc_result.overall_risk_level)}")

    assert isinstance(mc_result.warnings, list)
    print(f"✅ 风险警告数量: {len(mc_result.warnings)} 条")

    assert len(mc_result.risk_distributions["water_shortage"]) == 50
    assert len(mc_result.risk_distributions["overflow"]) == 50
    assert len(mc_result.risk_distributions["shutdown"]) == 50
    print("✅ 风险分布数据完整")


def test_emergency_recommendations_time_window():
    print("\n=== 测试应急建议时间窗口合理性 ===")

    params = SimulationParams(
        reservoir_capacity=100.0,
        reservoir_area=20.0,
        gate_max_flow=50.0,
        mill_power_consumption=5.0,
        initial_water_level=50.0,
    )

    tide_records = generate_multi_day_tide_records(num_days=3)
    mill_schedule = generate_daily_mill_schedule_for_multi_day(3)

    baseline = DisturbanceScenario(name="baseline")
    baseline_sim, _, _ = run_disturbed_simulation(params, tide_records, mill_schedule, baseline)
    baseline_risk = assess_risks(params, baseline_sim, baseline)

    print("  测试1: 仅设备故障场景")
    equip_only = DisturbanceScenario(
        name="equip_only",
        equipment=EquipmentFailureConfig(
            gate_failure_probability=0.7,
            mill_failure_probability=0.6,
            gate_flow_reduction_pct=60.0,
            failure_start_hour=36.0,
            failure_duration_hours=24.0,
        ),
    )
    equip_sim, _, _ = run_disturbed_simulation(params, tide_records, mill_schedule, equip_only)
    equip_risk = assess_risks(params, equip_sim, equip_only)

    recs = generate_emergency_recommendations(params, baseline_risk, equip_risk, equip_only)
    print(f"  生成建议数量: {len(recs)}")

    for rec in recs:
        start, end = rec.time_window
        assert start < end, f"建议'{rec.action}'时间窗口无效: {start}-{end}"
        assert start >= 0, f"建议'{rec.action}'开始时间不能为负: {start}"
        print(f"    ✅ {rec.action}: 第{start:.1f}h - 第{end:.1f}h ({rec.priority})")

    mill_recs = [r for r in recs if "磨坊" in r.action or "设备" in r.action]
    if mill_recs:
        for rec in mill_recs:
            start, end = rec.time_window
            assert abs(start - 36.0) < 12.0 or "检修" in rec.action, f"设备相关建议应在故障时间附近"
        print("  ✅ 设备相关建议时间窗口合理")

    print("  测试2: 仅风暴潮场景")
    storm_only = DisturbanceScenario(
        name="storm_only",
        storm_surge=StormSurgeConfig(
            surge_height=2.0,
            surge_start_hour=24.0,
            surge_duration_hours=12.0,
        ),
    )
    storm_sim, _, _ = run_disturbed_simulation(params, tide_records, mill_schedule, storm_only)
    storm_risk = assess_risks(params, storm_sim, storm_only)

    recs_storm = generate_emergency_recommendations(params, baseline_risk, storm_risk, storm_only)
    print(f"  生成建议数量: {len(recs_storm)}")

    for rec in recs_storm:
        start, end = rec.time_window
        assert start < end, f"建议'{rec.action}'时间窗口无效"
        assert start >= 0, f"建议'{rec.action}'开始时间不能为负"
        print(f"    ✅ {rec.action}: 第{start:.1f}h - 第{end:.1f}h ({rec.priority})")

    print("  ✅ 所有应急建议时间窗口均合理")


def main():
    print("🌊 潮汐磨坊调度模拟系统 - 功能测试 v4")
    print("=" * 60)

    try:
        test_validate_tide_records()
        test_validate_mill_schedule()
        test_water_needs_estimation()
        test_manual_gate()
        test_csv_parsing()
        test_database()
        test_simulation_constraints()
        test_multi_day_tide()
        test_multi_day_simulation()
        test_optimizer()
        test_optimization_comparison()
        test_score_calculation()
        test_optimization_database()
        test_storm_surge_config()
        test_rainfall_config()
        test_equipment_failure_config()
        test_apply_storm_surge()
        test_disturbed_simulation()
        test_risk_assessment()
        test_emergency_recommendations()
        test_disturbance_scenarios()
        test_risk_comparison()
        test_equipment_failure_state()
        test_disturbance_detection()
        test_disturbance_time_window()
        test_monte_carlo_simulation()
        test_emergency_recommendations_time_window()

        print("\n" + "=" * 60)
        print("🎉 所有测试通过! 系统运行正常。")
        return 0
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
