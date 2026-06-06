#!/usr/bin/env python3
"""测试潮汐磨坊调度模拟系统的核心功能 - v2"""

from database import (
    init_db, create_scenario, list_scenarios, get_scenario,
    copy_scenario, delete_scenario, save_simulation_results, get_simulation_results
)
from simulation import (
    SimulationParams, run_simulation, validate_tide_records,
    validate_mill_schedule, estimate_mill_water_needs,
    validate_manual_gate_schedule, parse_tide_csv,
    generate_default_tide_records, generate_default_mill_schedule
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
