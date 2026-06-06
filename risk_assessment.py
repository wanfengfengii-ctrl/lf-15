import math
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass, field
from simulation import (
    SimulationParams,
    run_simulation,
    interpolate_tide,
    get_total_hours,
    compute_simulation_metrics,
    calculate_gate_flow,
    generate_multi_day_tide_records,
    generate_daily_mill_schedule_for_multi_day,
)


@dataclass
class StormSurgeConfig:
    surge_height: float = 0.0
    surge_start_hour: float = 0.0
    surge_duration_hours: float = 24.0
    surge_shape: str = "sinusoidal"

    def surge_at_time(self, time_hour: float) -> float:
        if self.surge_height <= 0:
            return 0.0
        if time_hour < self.surge_start_hour or time_hour > self.surge_start_hour + self.surge_duration_hours:
            return 0.0

        elapsed = time_hour - self.surge_start_hour
        if self.surge_shape == "sinusoidal":
            ratio = math.sin(math.pi * elapsed / self.surge_duration_hours)
        elif self.surge_shape == "triangular":
            half = self.surge_duration_hours / 2
            if elapsed <= half:
                ratio = elapsed / half
            else:
                ratio = 1 - (elapsed - half) / half
        elif self.surge_shape == "rectangular":
            ratio = 1.0
        else:
            ratio = math.sin(math.pi * elapsed / self.surge_duration_hours)

        return self.surge_height * max(0.0, ratio)


@dataclass
class RainfallConfig:
    rainfall_rate: float = 0.0
    rainfall_start_hour: float = 0.0
    rainfall_duration_hours: float = 12.0
    runoff_coefficient: float = 0.6
    catchment_area: float = 100.0

    def inflow_at_time(self, time_hour: float) -> float:
        if self.rainfall_rate <= 0:
            return 0.0
        if time_hour < self.rainfall_start_hour or time_hour > self.rainfall_start_hour + self.rainfall_duration_hours:
            return 0.0

        return self.rainfall_rate * self.catchment_area * self.runoff_coefficient / 1000.0


@dataclass
class EquipmentFailureConfig:
    gate_failure_probability: float = 0.0
    mill_failure_probability: float = 0.0
    gate_flow_reduction_pct: float = 50.0
    failure_start_hour: float = 0.0
    failure_duration_hours: float = 6.0

    def is_failure_period(self, time_hour: float) -> bool:
        return (self.failure_start_hour <= time_hour <=
                self.failure_start_hour + self.failure_duration_hours)

    def effective_gate_flow(self, base_flow: float, time_hour: float) -> float:
        if not self.is_failure_period(time_hour):
            return base_flow
        reduction = self.gate_flow_reduction_pct / 100.0
        return base_flow * (1 - reduction)

    def mill_available(self, time_hour: float) -> bool:
        if not self.is_failure_period(time_hour):
            return True
        return self.mill_failure_probability < 0.5


@dataclass
class DisturbanceScenario:
    name: str = "baseline"
    description: str = "无扰动基线场景"
    storm_surge: StormSurgeConfig = field(default_factory=StormSurgeConfig)
    rainfall: RainfallConfig = field(default_factory=RainfallConfig)
    equipment: EquipmentFailureConfig = field(default_factory=EquipmentFailureConfig)
    risk_level: str = "low"


@dataclass
class RiskAssessmentResult:
    scenario_name: str
    water_shortage_risk: float
    overflow_risk: float
    shutdown_risk: float
    overall_risk_level: str
    risk_details: Dict[str, float]
    simulation_results: List[Dict]
    metrics: Dict
    warnings: List[str]


def apply_storm_surge_to_tide(
    tide_records: List[Dict],
    storm_config: StormSurgeConfig,
) -> List[Dict]:
    modified = []
    for record in tide_records:
        surge = storm_config.surge_at_time(record["time_hour"])
        modified.append({
            "time_hour": record["time_hour"],
            "tide_level": record["tide_level"] + surge,
        })
    return modified


def run_disturbed_simulation(
    params: SimulationParams,
    tide_records: List[Dict],
    mill_schedule: List[Dict],
    disturbance: DisturbanceScenario,
    total_hours: float = None,
) -> Tuple[List[Dict], List[Dict], List[str]]:
    if total_hours is None:
        total_hours = get_total_hours(tide_records)

    modified_tide = apply_storm_surge_to_tide(tide_records, disturbance.storm_surge)

    num_steps = int(total_hours / params.time_step_hours) + 1
    time_hours = [i * params.time_step_hours for i in range(num_steps)]

    tide_levels = interpolate_tide(modified_tide, time_hours)

    water_volumes = [params.initial_water_level]
    water_heights = [params.volume_to_height(params.initial_water_level)]
    gate_ratios = [0.0]
    mill_running_list = [False]
    warnings = []

    for i in range(1, num_steps):
        t = time_hours[i]
        tide_level = tide_levels[i]
        prev_volume = water_volumes[i - 1]
        prev_height = water_heights[i - 1]

        mill_running = any(
            s["start_hour"] <= t < s["end_hour"] for s in mill_schedule
        )

        if mill_running and not disturbance.equipment.mill_available(t):
            mill_running = False
            if not any("磨坊设备故障" in w for w in warnings):
                warnings.append(f"时间 {t:.1f}h: 磨坊设备故障，无法运行")

        target_gate_ratio = 0.0
        if mill_running:
            if prev_volume > params.reservoir_capacity * 0.4:
                target_gate_ratio = 0.0
            elif tide_level > prev_height and prev_volume < params.reservoir_capacity * 0.95:
                target_gate_ratio = 100.0
            else:
                target_gate_ratio = 0.0
        else:
            if tide_level > prev_height and prev_volume < params.reservoir_capacity * 0.95:
                target_gate_ratio = 100.0
            elif tide_level < prev_height and prev_volume > params.reservoir_capacity * 0.1:
                target_gate_ratio = 0.0
            else:
                target_gate_ratio = 0.0

        gate_ratio = max(0.0, min(100.0, target_gate_ratio))

        flow_rate = calculate_gate_flow(
            tide_level, prev_height, gate_ratio, params.gate_max_flow
        )
        flow_rate = disturbance.equipment.effective_gate_flow(flow_rate, t)

        rainfall_inflow = disturbance.rainfall.inflow_at_time(t)
        total_inflow = flow_rate + rainfall_inflow if flow_rate > 0 else flow_rate
        if flow_rate <= 0 and rainfall_inflow > 0:
            total_inflow = rainfall_inflow

        mill_consumption = 0.0
        if mill_running:
            if prev_volume > params.reservoir_capacity * 0.05:
                mill_consumption = params.mill_power_consumption * params.time_step_hours
            else:
                mill_running = False
                warnings.append(f"时间 {t:.1f}h: 蓄水量不足，磨坊无法运行")

        volume_change = total_inflow * params.time_step_hours - mill_consumption
        new_volume = prev_volume + volume_change

        if new_volume > params.reservoir_capacity:
            overflow = new_volume - params.reservoir_capacity
            new_volume = params.reservoir_capacity
            if not any("蓄水池溢流" in w for w in warnings):
                warnings.append(f"时间 {t:.1f}h: 蓄水池溢流约 {overflow:.2f} m³/h")
        elif new_volume < 0:
            new_volume = 0.0
            if mill_running:
                warnings.append(f"时间 {t:.1f}h: 蓄水量不足，磨坊停止运行")
                mill_running = False

        new_height = params.volume_to_height(new_volume)

        water_volumes.append(new_volume)
        water_heights.append(new_height)
        gate_ratios.append(gate_ratio)
        mill_running_list.append(mill_running)

    results = []
    for i in range(num_steps):
        results.append({
            "time_hour": time_hours[i],
            "tide_level": tide_levels[i],
            "water_level": water_heights[i],
            "water_volume": water_volumes[i],
            "gate_open_ratio": gate_ratios[i],
            "mill_running": mill_running_list[i],
            "storm_surge": disturbance.storm_surge.surge_at_time(time_hours[i]),
            "rainfall_inflow": disturbance.rainfall.inflow_at_time(time_hours[i]),
        })

    from simulation import generate_gate_schedule
    gate_schedule = generate_gate_schedule(
        time_hours, tide_levels, water_heights, gate_ratios
    )

    return results, gate_schedule, warnings


def assess_risks(
    params: SimulationParams,
    simulation_results: List[Dict],
    disturbance: DisturbanceScenario,
) -> RiskAssessmentResult:
    if not simulation_results:
        return RiskAssessmentResult(
            scenario_name=disturbance.name,
            water_shortage_risk=0.0,
            overflow_risk=0.0,
            shutdown_risk=0.0,
            overall_risk_level="unknown",
            risk_details={},
            simulation_results=[],
            metrics={},
            warnings=["无模拟结果"],
        )

    metrics = compute_simulation_metrics(simulation_results, params)

    water_volumes = [r["water_volume"] for r in simulation_results]
    mill_running = [r["mill_running"] for r in simulation_results]
    total_steps = len(simulation_results)

    low_water_threshold = params.reservoir_capacity * 0.1
    critical_water_threshold = params.reservoir_capacity * 0.05

    low_water_steps = sum(1 for v in water_volumes if v <= low_water_threshold)
    critical_water_steps = sum(1 for v in water_volumes if v <= critical_water_threshold)

    water_shortage_risk = (
        0.4 * (low_water_steps / total_steps) +
        0.6 * (critical_water_steps / total_steps)
    ) * 100

    overflow_threshold = params.reservoir_capacity * 0.95
    overflow_steps = sum(1 for v in water_volumes if v >= overflow_threshold)
    full_overflow_steps = sum(1 for v in water_volumes if v >= params.reservoir_capacity - 0.001)

    overflow_risk = (
        0.3 * (overflow_steps / total_steps) +
        0.7 * (full_overflow_steps / total_steps)
    ) * 100

    planned_mill_schedule_hours = sum(
        s["end_hour"] - s["start_hour"]
        for s in _get_mill_schedule_from_results(simulation_results)
    ) if _get_mill_schedule_from_results(simulation_results) else 0

    actual_mill_hours = sum(1 for m in mill_running if m) * params.time_step_hours

    if planned_mill_schedule_hours > 0:
        shutdown_ratio = 1 - (actual_mill_hours / planned_mill_schedule_hours)
    else:
        shutdown_ratio = 0.0

    equipment_factor = (
        disturbance.equipment.gate_failure_probability * 0.3 +
        disturbance.equipment.mill_failure_probability * 0.7
    )

    shutdown_risk = max(0.0, min(100.0, (shutdown_ratio * 80 + equipment_factor * 20) * 100))

    overall_score = (
        water_shortage_risk * 0.35 +
        overflow_risk * 0.35 +
        shutdown_risk * 0.30
    )

    if overall_score >= 70:
        overall_risk_level = "critical"
    elif overall_score >= 40:
        overall_risk_level = "high"
    elif overall_score >= 20:
        overall_risk_level = "medium"
    else:
        overall_risk_level = "low"

    risk_details = {
        "low_water_duration_pct": round(low_water_steps / total_steps * 100, 2),
        "critical_water_duration_pct": round(critical_water_steps / total_steps * 100, 2),
        "overflow_duration_pct": round(overflow_steps / total_steps * 100, 2),
        "full_overflow_duration_pct": round(full_overflow_steps / total_steps * 100, 2),
        "mill_availability_pct": round(actual_mill_hours / max(1, planned_mill_schedule_hours) * 100, 2),
        "avg_water_volume": metrics.get("avg_water_volume", 0),
        "min_water_volume": metrics.get("min_water_volume", 0),
        "max_water_volume": metrics.get("max_water_volume", 0),
        "overflow_volume": metrics.get("overflow_volume", 0),
        "total_mill_hours": metrics.get("total_mill_hours", 0),
    }

    warnings = []
    if water_shortage_risk > 50:
        warnings.append("⚠️ 高缺水风险：蓄水量长期处于低位，磨坊可能频繁停机")
    elif water_shortage_risk > 20:
        warnings.append("⚡ 中等缺水风险：部分时段蓄水量偏低")

    if overflow_risk > 50:
        warnings.append("🌊 高溢流风险：蓄水池频繁满溢，水资源浪费严重")
    elif overflow_risk > 20:
        warnings.append("💧 中等溢流风险：部分时段可能发生溢流")

    if shutdown_risk > 50:
        warnings.append("🔧 高停机风险：磨坊运行时间严重不足")
    elif shutdown_risk > 20:
        warnings.append("⚙️ 中等停机风险：部分时段磨坊无法运行")

    return RiskAssessmentResult(
        scenario_name=disturbance.name,
        water_shortage_risk=round(water_shortage_risk, 2),
        overflow_risk=round(overflow_risk, 2),
        shutdown_risk=round(shutdown_risk, 2),
        overall_risk_level=overall_risk_level,
        risk_details=risk_details,
        simulation_results=simulation_results,
        metrics=metrics,
        warnings=warnings,
    )


def _get_mill_schedule_from_results(results: List[Dict]) -> List[Dict]:
    schedule = []
    in_mill = False
    start_time = 0.0

    for r in results:
        if r["mill_running"] and not in_mill:
            start_time = r["time_hour"]
            in_mill = True
        elif not r["mill_running"] and in_mill:
            schedule.append({"start_hour": start_time, "end_hour": r["time_hour"]})
            in_mill = False

    if in_mill and results:
        schedule.append({"start_hour": start_time, "end_hour": results[-1]["time_hour"]})

    return schedule


def generate_disturbance_scenarios() -> List[DisturbanceScenario]:
    scenarios = []

    scenarios.append(DisturbanceScenario(
        name="baseline",
        description="无扰动基线场景",
        risk_level="low",
    ))

    scenarios.append(DisturbanceScenario(
        name="minor_storm",
        description="小型风暴潮：潮位升高0.5米，持续12小时",
        storm_surge=StormSurgeConfig(
            surge_height=0.5,
            surge_start_hour=24.0,
            surge_duration_hours=12.0,
            surge_shape="sinusoidal",
        ),
        risk_level="low",
    ))

    scenarios.append(DisturbanceScenario(
        name="moderate_storm",
        description="中型风暴潮：潮位升高1.0米，伴随降雨入流",
        storm_surge=StormSurgeConfig(
            surge_height=1.0,
            surge_start_hour=48.0,
            surge_duration_hours=18.0,
            surge_shape="sinusoidal",
        ),
        rainfall=RainfallConfig(
            rainfall_rate=20.0,
            rainfall_start_hour=48.0,
            rainfall_duration_hours=12.0,
            runoff_coefficient=0.6,
            catchment_area=100.0,
        ),
        risk_level="medium",
    ))

    scenarios.append(DisturbanceScenario(
        name="severe_storm",
        description="严重风暴潮：潮位升高1.5米，强降雨，设备故障风险",
        storm_surge=StormSurgeConfig(
            surge_height=1.5,
            surge_start_hour=72.0,
            surge_duration_hours=24.0,
            surge_shape="sinusoidal",
        ),
        rainfall=RainfallConfig(
            rainfall_rate=50.0,
            rainfall_start_hour=72.0,
            rainfall_duration_hours=18.0,
            runoff_coefficient=0.7,
            catchment_area=150.0,
        ),
        equipment=EquipmentFailureConfig(
            gate_failure_probability=0.3,
            mill_failure_probability=0.2,
            gate_flow_reduction_pct=50.0,
            failure_start_hour=72.0,
            failure_duration_hours=12.0,
        ),
        risk_level="high",
    ))

    scenarios.append(DisturbanceScenario(
        name="equipment_failure",
        description="设备故障场景：闸门流量降低50%，磨坊故障风险高",
        equipment=EquipmentFailureConfig(
            gate_failure_probability=0.5,
            mill_failure_probability=0.4,
            gate_flow_reduction_pct=50.0,
            failure_start_hour=36.0,
            failure_duration_hours=24.0,
        ),
        risk_level="medium",
    ))

    scenarios.append(DisturbanceScenario(
        name="heavy_rainfall",
        description="强降雨入流：持续降雨24小时，入流量大",
        rainfall=RainfallConfig(
            rainfall_rate=80.0,
            rainfall_start_hour=12.0,
            rainfall_duration_hours=24.0,
            runoff_coefficient=0.8,
            catchment_area=200.0,
        ),
        risk_level="high",
    ))

    return scenarios


@dataclass
class EmergencyRecommendation:
    action: str
    description: str
    priority: str
    risk_impact: str
    time_window: Tuple[float, float]
    details: Dict = field(default_factory=dict)


def generate_emergency_recommendations(
    params: SimulationParams,
    baseline_result: RiskAssessmentResult,
    disturbed_result: RiskAssessmentResult,
    disturbance: DisturbanceScenario,
) -> List[EmergencyRecommendation]:
    recommendations = []

    delta_shortage = disturbed_result.water_shortage_risk - baseline_result.water_shortage_risk
    delta_overflow = disturbed_result.overflow_risk - baseline_result.overflow_risk
    delta_shutdown = disturbed_result.shutdown_risk - baseline_result.shutdown_risk

    if delta_overflow > 10 or disturbed_result.overflow_risk > 30:
        recommendations.append(EmergencyRecommendation(
            action="提前泄洪",
            description="风暴潮/降雨来临前，提前降低蓄水池水位，预留防洪库容",
            priority="high" if delta_overflow > 30 else "medium",
            risk_impact="降低溢流风险",
            time_window=(
                max(0.0, disturbance.storm_surge.surge_start_hour - 6.0),
                disturbance.storm_surge.surge_start_hour,
            ),
            details={
                "目标水位": f"{params.reservoir_capacity * 0.5:.1f} m³",
                "预计降低溢流风险": f"{min(delta_overflow * 0.6, 40):.1f}%",
            }
        ))

        recommendations.append(EmergencyRecommendation(
            action="限制进水",
            description="高潮位时段限制闸门开启，减少进水量，防止溢流",
            priority="high" if disturbed_result.overflow_risk > 50 else "medium",
            risk_impact="降低溢流风险",
            time_window=(
                disturbance.storm_surge.surge_start_hour,
                disturbance.storm_surge.surge_start_hour + disturbance.storm_surge.surge_duration_hours,
            ),
            details={
                "闸门最大开启比例": "50%",
                "触发水位阈值": f"{params.reservoir_capacity * 0.8:.1f} m³",
            }
        ))

    if delta_shortage > 10 or disturbed_result.water_shortage_risk > 30:
        recommendations.append(EmergencyRecommendation(
            action="提前蓄水",
            description="扰动来临前的高潮期加大蓄水，提高水位安全裕度",
            priority="high" if delta_shortage > 30 else "medium",
            risk_impact="降低缺水风险",
            time_window=(
                0.0,
                max(0.0, disturbance.storm_surge.surge_start_hour - 6.0),
            ),
            details={
                "目标水位": f"{params.reservoir_capacity * 0.85:.1f} m³",
                "预计降低缺水风险": f"{min(delta_shortage * 0.5, 30):.1f}%",
            }
        ))

    if delta_shutdown > 10 or disturbed_result.shutdown_risk > 30:
        recommendations.append(EmergencyRecommendation(
            action="调整磨坊计划",
            description="将磨粉作业提前或延后，避开设备故障和缺水高峰时段",
            priority="high" if delta_shutdown > 30 else "medium",
            risk_impact="降低停机风险",
            time_window=(
                disturbance.equipment.failure_start_hour,
                disturbance.equipment.failure_start_hour + disturbance.equipment.failure_duration_hours,
            ),
            details={
                "建议转移产量比例": "40%",
                "目标时段": "故障期前后的高潮位时段",
            }
        ))

        if disturbance.equipment.mill_failure_probability > 0.3:
            recommendations.append(EmergencyRecommendation(
                action="设备检修",
                description="风暴前对磨坊和闸门设备进行检查维护，降低故障概率",
                priority="medium",
                risk_impact="降低设备故障风险",
                time_window=(
                    max(0.0, disturbance.equipment.failure_start_hour - 12.0),
                    disturbance.equipment.failure_start_hour,
                ),
                details={
                    "预计降低故障概率": "约30%",
                    "检修重点": "闸门传动机构、磨坊水轮",
                }
            ))

    if disturbed_result.overall_risk_level in ["high", "critical"]:
        recommendations.append(EmergencyRecommendation(
            action="启用备用电源",
            description="确保应急供电系统就绪，应对极端情况下的设备运行",
            priority="medium",
            risk_impact="提升系统可靠性",
            time_window=(
                disturbance.storm_surge.surge_start_hour,
                disturbance.storm_surge.surge_start_hour + disturbance.storm_surge.surge_duration_hours,
            ),
            details={
                "备用容量": "100%",
                "启动条件": "主电源故障或水位超过警戒线",
            }
        ))

    if disturbance.rainfall.rainfall_rate > 30:
        recommendations.append(EmergencyRecommendation(
            action="启用备用水源",
            description="降雨量大时可考虑收集雨水作为备用水源",
            priority="low",
            risk_impact="增加水资源储备",
            time_window=(
                disturbance.rainfall.rainfall_start_hour,
                disturbance.rainfall.rainfall_start_hour + disturbance.rainfall.rainfall_duration_hours,
            ),
            details={
                "预计额外收集水量": f"{disturbance.rainfall.rainfall_rate * disturbance.rainfall.rainfall_duration_hours * 0.1:.1f} m³",
                "注意事项": "需确保水质符合使用标准",
            }
        ))

    priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    recommendations.sort(key=lambda r: priority_order.get(r.priority, 99))

    return recommendations


def compare_risk_scenarios(
    params: SimulationParams,
    tide_records: List[Dict],
    mill_schedule: List[Dict],
    scenarios: List[DisturbanceScenario],
) -> List[RiskAssessmentResult]:
    results = []
    total_hours = get_total_hours(tide_records)

    for scenario in scenarios:
        sim_results, _, warnings = run_disturbed_simulation(
            params, tide_records, mill_schedule, scenario, total_hours=total_hours
        )
        risk_result = assess_risks(params, sim_results, scenario)
        risk_result.warnings.extend(warnings)
        results.append(risk_result)

    return results


def get_risk_level_color(level: str) -> str:
    colors = {
        "low": "#2ca02c",
        "medium": "#ff7f0e",
        "high": "#d62728",
        "critical": "#9400d3",
        "unknown": "#7f7f7f",
    }
    return colors.get(level, "#7f7f7f")


def get_risk_level_label(level: str) -> str:
    labels = {
        "low": "低风险",
        "medium": "中风险",
        "high": "高风险",
        "critical": "严重风险",
        "unknown": "未知",
    }
    return labels.get(level, "未知")
