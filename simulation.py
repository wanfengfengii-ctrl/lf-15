import math
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass


@dataclass
class SimulationParams:
    reservoir_capacity: float
    reservoir_area: float
    gate_max_flow: float
    mill_power_consumption: float
    initial_water_level: float
    time_step_hours: float = 0.1

    @property
    def max_water_height(self) -> float:
        return self.reservoir_capacity / self.reservoir_area

    def volume_to_height(self, volume: float) -> float:
        return volume / self.reservoir_area

    def height_to_volume(self, height: float) -> float:
        return height * self.reservoir_area


def validate_tide_records(tide_records: List[Dict], total_hours: float = 24.0) -> Tuple[bool, str]:
    if not tide_records:
        return False, "潮位记录不能为空"

    if len(tide_records) < 2:
        return False, "至少需要2条潮位记录"

    for i, record in enumerate(tide_records):
        if "time_hour" not in record or "tide_level" not in record:
            return False, f"第 {i+1} 条记录格式不正确"
        if record["time_hour"] < 0 or record["time_hour"] > total_hours:
            return False, f"第 {i+1} 条记录的时间 {record['time_hour']} 超出范围 [0, {total_hours}]"
        if record["tide_level"] < 0:
            return False, f"第 {i+1} 条记录的潮位不能为负值"

    sorted_records = sorted(tide_records, key=lambda r: r["time_hour"])

    for i in range(len(sorted_records) - 1):
        if sorted_records[i]["time_hour"] == sorted_records[i + 1]["time_hour"]:
            return False, f"存在重复的时间点: {sorted_records[i]['time_hour']}"

    return True, "潮位记录有效"


def interpolate_tide(
    tide_records: List[Dict],
    time_hours: List[float],
) -> List[float]:
    sorted_records = sorted(tide_records, key=lambda r: r["time_hour"])
    tide_levels = []

    for t in time_hours:
        if t <= sorted_records[0]["time_hour"]:
            tide_levels.append(sorted_records[0]["tide_level"])
        elif t >= sorted_records[-1]["time_hour"]:
            tide_levels.append(sorted_records[-1]["tide_level"])
        else:
            for i in range(len(sorted_records) - 1):
                t0 = sorted_records[i]["time_hour"]
                t1 = sorted_records[i + 1]["time_hour"]
                if t0 <= t <= t1:
                    ratio = (t - t0) / (t1 - t0)
                    level = sorted_records[i]["tide_level"] + ratio * (
                        sorted_records[i + 1]["tide_level"] - sorted_records[i]["tide_level"]
                    )
                    tide_levels.append(level)
                    break

    return tide_levels


def is_mill_running(mill_schedule: List[Dict], time_hour: float) -> bool:
    for sched in mill_schedule:
        if sched["start_hour"] <= time_hour < sched["end_hour"]:
            return True
    return False


def calculate_gate_flow(
    tide_level: float,
    water_level: float,
    gate_open_ratio: float,
    gate_max_flow: float,
) -> float:
    if gate_open_ratio <= 0:
        return 0.0

    effective_ratio = max(0.0, min(1.0, gate_open_ratio / 100.0))
    height_diff = tide_level - water_level

    if abs(height_diff) < 0.001:
        return 0.0

    flow_direction = 1.0 if height_diff > 0 else -1.0
    flow_rate = gate_max_flow * effective_ratio * math.sqrt(abs(height_diff))
    return flow_direction * flow_rate


def generate_gate_schedule(
    time_hours: List[float],
    tide_levels: List[float],
    water_levels: List[float],
    gate_ratios: List[float],
) -> List[Dict]:
    if not time_hours:
        return []

    schedule = []
    current_start = 0
    current_ratio = gate_ratios[0]

    threshold = 1.0

    for i in range(1, len(time_hours)):
        if abs(gate_ratios[i] - current_ratio) > threshold:
            if current_ratio > 0.5:
                action = "开启"
            else:
                action = "关闭"

            schedule.append(
                {
                    "start_hour": time_hours[current_start],
                    "end_hour": time_hours[i - 1],
                    "open_ratio": current_ratio,
                    "action": action,
                }
            )
            current_start = i
            current_ratio = gate_ratios[i]

    if current_ratio > 0.5:
        action = "开启"
    else:
        action = "关闭"

    schedule.append(
        {
            "start_hour": time_hours[current_start],
            "end_hour": time_hours[-1],
            "open_ratio": current_ratio,
            "action": action,
        }
    )

    return schedule


def run_simulation(
    params: SimulationParams,
    tide_records: List[Dict],
    mill_schedule: List[Dict],
    total_hours: float = 24.0,
) -> Tuple[List[Dict], List[Dict], List[str]]:
    warnings = []

    if params.initial_water_level < 0:
        warnings.append("初始蓄水量不能为负，已设为0")
        params.initial_water_level = 0
    if params.initial_water_level > params.reservoir_capacity:
        warnings.append(f"初始蓄水量超过容量，已设为容量值: {params.reservoir_capacity}")
        params.initial_water_level = params.reservoir_capacity

    if params.reservoir_area <= 0:
        raise ValueError("蓄水池面积必须大于0")

    valid, msg = validate_tide_records(tide_records, total_hours)
    if not valid:
        raise ValueError(msg)

    num_steps = int(total_hours / params.time_step_hours) + 1
    time_hours = [i * params.time_step_hours for i in range(num_steps)]

    tide_levels = interpolate_tide(tide_records, time_hours)

    water_volumes = [params.initial_water_level]
    water_heights = [params.volume_to_height(params.initial_water_level)]
    gate_ratios = [0.0]
    mill_running_list = [False]

    for i in range(1, num_steps):
        t = time_hours[i]
        tide_level = tide_levels[i]
        prev_volume = water_volumes[i - 1]
        prev_height = water_heights[i - 1]

        mill_running = is_mill_running(mill_schedule, t)

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

        mill_consumption = 0.0
        if mill_running:
            if prev_volume > params.reservoir_capacity * 0.05:
                mill_consumption = params.mill_power_consumption * params.time_step_hours
            else:
                mill_running = False
                warnings.append(f"时间 {t:.1f}h: 蓄水量不足，磨坊无法运行")

        volume_change = flow_rate * params.time_step_hours - mill_consumption
        new_volume = prev_volume + volume_change

        if new_volume > params.reservoir_capacity:
            new_volume = params.reservoir_capacity
            if gate_ratio > 0 and flow_rate > 0:
                warnings.append(f"时间 {t:.1f}h: 蓄水池已满，限制进水")
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
        results.append(
            {
                "time_hour": time_hours[i],
                "tide_level": tide_levels[i],
                "water_level": water_heights[i],
                "water_volume": water_volumes[i],
                "gate_open_ratio": gate_ratios[i],
                "mill_running": mill_running_list[i],
            }
        )

    gate_schedule = generate_gate_schedule(
        time_hours, tide_levels, water_heights, gate_ratios
    )

    return results, gate_schedule, warnings


def generate_default_tide_records() -> List[Dict]:
    records = []
    for i in range(25):
        hour = i
        tide_level = 2.5 + 2.0 * math.sin(2 * math.pi * (hour - 6) / 12.4)
        records.append({"time_hour": float(hour), "tide_level": round(tide_level, 2)})
    return records


def generate_default_mill_schedule() -> List[Dict]:
    return [
        {"start_hour": 8.0, "end_hour": 12.0},
        {"start_hour": 14.0, "end_hour": 18.0},
    ]
