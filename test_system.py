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


def main():
    print("🌊 潮汐磨坊调度模拟系统 - 功能测试 v2")
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
