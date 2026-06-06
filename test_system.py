#!/usr/bin/env python3
"""测试潮汐磨坊调度模拟系统的核心功能"""

from database import (
    init_db, create_scenario, list_scenarios, get_scenario,
    copy_scenario, delete_scenario, save_simulation_results, get_simulation_results
)
from simulation import (
    SimulationParams, run_simulation, validate_tide_records,
    generate_default_tide_records, generate_default_mill_schedule
)


def test_database():
    print("\n=== 测试数据库功能 ===")
    init_db()
    print("✅ 数据库初始化成功")

    tide_records = generate_default_tide_records()
    mill_schedule = generate_default_mill_schedule()

    scenario_id = create_scenario(
        name='测试方案',
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
    assert scenario['name'] == '测试方案'
    assert scenario['reservoir_capacity'] == 100.0
    assert scenario['reservoir_area'] == 20.0
    assert len(scenario['tide_records']) == 25
    assert len(scenario['mill_schedule']) == 2
    print("✅ 方案读取成功")

    scenarios = list_scenarios()
    assert len(scenarios) >= 1
    print(f"✅ 方案列表获取成功, 共 {len(scenarios)} 个方案")

    new_id = copy_scenario(scenario_id, '测试方案副本')
    new_scenario = get_scenario(new_id)
    assert new_scenario is not None
    assert new_scenario['reservoir_capacity'] == scenario['reservoir_capacity']
    assert new_scenario['reservoir_area'] == scenario['reservoir_area']
    print(f"✅ 方案复制成功, 新ID: {new_id}")

    results, gate_schedule, warnings = run_simulation(
        SimulationParams(
            reservoir_capacity=100.0,
            reservoir_area=20.0,
            gate_max_flow=50.0,
            mill_power_consumption=5.0,
            initial_water_level=50.0,
        ),
        tide_records,
        mill_schedule,
    )
    save_simulation_results(scenario_id, results, gate_schedule)
    saved_results, saved_gate = get_simulation_results(scenario_id)
    assert len(saved_results) == len(results)
    assert len(saved_gate) == len(gate_schedule)
    print("✅ 模拟结果保存和读取成功")

    delete_scenario(new_id)
    deleted = get_scenario(new_id)
    assert deleted is None
    print("✅ 方案删除成功")

    delete_scenario(scenario_id)
    print("✅ 清理测试数据完成")


def test_simulation():
    print("\n=== 测试模拟逻辑 ===")

    tide_records = generate_default_tide_records()
    valid, msg = validate_tide_records(tide_records)
    assert valid, f"验证失败: {msg}"
    print(f"✅ 潮位记录验证通过: {msg}")

    invalid_records = [
        {"time_hour": 1.0, "tide_level": 2.0},
        {"time_hour": 1.0, "tide_level": 3.0},
    ]
    valid, msg = validate_tide_records(invalid_records)
    assert not valid
    print(f"✅ 重复时间检测通过: {msg}")

    params = SimulationParams(
        reservoir_capacity=100.0,
        reservoir_area=20.0,
        gate_max_flow=50.0,
        mill_power_consumption=5.0,
        initial_water_level=50.0,
    )
    mill_schedule = generate_default_mill_schedule()

    results, gate_schedule, warnings = run_simulation(params, tide_records, mill_schedule)
    assert len(results) > 0
    print(f"✅ 模拟运行成功, 共 {len(results)} 个时间步")
    print(f"✅ 闸门调度建议: {len(gate_schedule)} 条")

    water_volumes = [r['water_volume'] for r in results]
    assert min(water_volumes) >= -0.001, f"蓄水量低于0: {min(water_volumes)}"
    assert max(water_volumes) <= params.reservoir_capacity + 0.001, f"蓄水量超过容量: {max(water_volumes)}"
    print(f"✅ 蓄水量约束验证通过: {min(water_volumes):.2f} - {max(water_volumes):.2f} m³")

    water_heights = [r['water_level'] for r in results]
    print(f"✅ 蓄水池水位范围: {min(water_heights):.2f} - {max(water_heights):.2f} m")

    gate_ratios = [r['gate_open_ratio'] for r in results]
    assert min(gate_ratios) >= -0.001, f"闸门比例低于0: {min(gate_ratios)}"
    assert max(gate_ratios) <= 100.001, f"闸门比例超过100: {max(gate_ratios)}"
    print(f"✅ 闸门开启比例约束验证通过: {min(gate_ratios):.1f}% - {max(gate_ratios):.1f}%")

    mill_running_volumes = [r['water_volume'] for r in results if r['mill_running']]
    if mill_running_volumes:
        assert min(mill_running_volumes) >= -0.001, f"磨坊运行时蓄水量为负"
        print(f"✅ 磨坊运行时水位约束验证通过")
    else:
        print("⚠️  警告: 没有磨坊运行时段")

    if warnings:
        print(f"⚠️  模拟警告: {len(warnings)} 条")
        for w in warnings[:3]:
            print(f"   - {w}")

    open_periods = [g for g in gate_schedule if g["action"] == "开启"]
    if open_periods:
        print(f"✅ 闸门开启时段: {len(open_periods)} 个")
        for p in open_periods[:3]:
            print(f"   - {p['start_hour']:.1f}h - {p['end_hour']:.1f}h")
    else:
        print("⚠️  警告: 没有闸门开启时段")

    print(f"✅ 所有模拟约束验证通过")


def test_edge_cases():
    print("\n=== 测试边界情况 ===")

    tide_records = generate_default_tide_records()
    mill_schedule = generate_default_mill_schedule()

    params = SimulationParams(
        reservoir_capacity=100.0,
        reservoir_area=20.0,
        gate_max_flow=50.0,
        mill_power_consumption=5.0,
        initial_water_level=-10.0,
    )
    results, gate_schedule, warnings = run_simulation(params, tide_records, mill_schedule)
    assert results[0]['water_volume'] >= 0
    print("✅ 负初始蓄水量处理通过")

    params2 = SimulationParams(
        reservoir_capacity=50.0,
        reservoir_area=10.0,
        gate_max_flow=50.0,
        mill_power_consumption=5.0,
        initial_water_level=100.0,
    )
    results2, _, warnings2 = run_simulation(params2, tide_records, mill_schedule)
    assert results2[0]['water_volume'] <= params2.reservoir_capacity + 0.001
    print("✅ 初始蓄水量超容量处理通过")

    params3 = SimulationParams(
        reservoir_capacity=20.0,
        reservoir_area=5.0,
        gate_max_flow=5.0,
        mill_power_consumption=20.0,
        initial_water_level=10.0,
    )
    mill_schedule3 = [{"start_hour": 0.0, "end_hour": 24.0}]
    results3, _, warnings3 = run_simulation(params3, tide_records, mill_schedule3)
    water_volumes3 = [r['water_volume'] for r in results3]
    assert min(water_volumes3) >= -0.001
    print("✅ 高耗水低容量边界情况处理通过")

    try:
        params4 = SimulationParams(
            reservoir_capacity=100.0,
            reservoir_area=0.0,
            gate_max_flow=50.0,
            mill_power_consumption=5.0,
            initial_water_level=50.0,
        )
        run_simulation(params4, tide_records, mill_schedule)
        assert False, "应该抛出面积为0的错误"
    except ValueError as e:
        print(f"✅ 零面积检测通过: {e}")

    print("✅ 所有边界情况测试通过")


def test_physical_model():
    print("\n=== 测试物理模型合理性 ===")

    tide_records = generate_default_tide_records()
    mill_schedule = generate_default_mill_schedule()

    params = SimulationParams(
        reservoir_capacity=100.0,
        reservoir_area=20.0,
        gate_max_flow=50.0,
        mill_power_consumption=5.0,
        initial_water_level=20.0,
    )

    results, gate_schedule, warnings = run_simulation(params, tide_records, mill_schedule)

    tide_levels = [r['tide_level'] for r in results]
    water_heights = [r['water_level'] for r in results]
    gate_ratios = [r['gate_open_ratio'] for r in results]

    print(f"潮位范围: {min(tide_levels):.2f} - {max(tide_levels):.2f} m")
    print(f"蓄水池水位范围: {min(water_heights):.2f} - {max(water_heights):.2f} m")
    print(f"最大水位高度(容量/面积): {params.max_water_height:.2f} m")

    gate_open_count = sum(1 for r in gate_ratios if r > 50)
    print(f"闸门开启时间步数: {gate_open_count} / {len(results)}")

    if gate_open_count > 0:
        print("✅ 闸门有开启动作，物理模型合理")
    else:
        print("⚠️  警告: 闸门未开启，可能需要调整参数")

    print("✅ 物理模型测试完成")


def main():
    print("🌊 潮汐磨坊调度模拟系统 - 功能测试")
    print("=" * 50)

    try:
        test_database()
        test_simulation()
        test_edge_cases()
        test_physical_model()
        print("\n" + "=" * 50)
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
