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

    if sorted_records[0]["time_hour"] > 0.01:
        return False, f"潮位记录必须从0小时开始，当前起始时间: {sorted_records[0]['time_hour']} 小时"

    if sorted_records[-1]["time_hour"] < total_hours - 0.01:
        return False, f"潮位记录必须覆盖到 {total_hours} 小时，当前结束时间: {sorted_records[-1]['time_hour']} 小时"

    return True, "潮位记录有效"


def validate_mill_schedule(mill_schedule: List[Dict], total_hours: float = 24.0) -> Tuple[bool, str, List[str]]:
    warnings = []

    if not mill_schedule:
        return True, "磨坊计划有效", warnings

    sorted_schedule = sorted(mill_schedule, key=lambda s: s["start_hour"])

    for i, sched in enumerate(sorted_schedule):
        if sched["start_hour"] < 0 or sched["start_hour"] > total_hours:
            return False, f"第 {i+1} 个时段的开始时间 {sched['start_hour']} 超出范围 [0, {total_hours}]", warnings
        if sched["end_hour"] < 0 or sched["end_hour"] > total_hours:
            return False, f"第 {i+1} 个时段的结束时间 {sched['end_hour']} 超出范围 [0, {total_hours}]", warnings
        if sched["start_hour"] >= sched["end_hour"]:
            return False, f"第 {i+1} 个时段的开始时间必须小于结束时间", warnings

    for i in range(len(sorted_schedule) - 1):
        if sorted_schedule[i]["end_hour"] > sorted_schedule[i + 1]["start_hour"] + 0.001:
            return False, f"时段 {i+1} 与时段 {i+2} 重叠: {sorted_schedule[i]['end_hour']} > {sorted_schedule[i+1]['start_hour']}", warnings

    return True, "磨坊计划有效", warnings


def estimate_mill_water_needs(
    mill_schedule: List[Dict],
    mill_power_consumption: float,
    reservoir_capacity: float,
) -> Tuple[float, List[str]]:
    warnings = []

    total_hours = sum(s["end_hour"] - s["start_hour"] for s in mill_schedule)
    total_water_needed = total_hours * mill_power_consumption

    if total_water_needed > reservoir_capacity:
        warnings.append(
            f"磨坊总需水量 {total_water_needed:.1f} m³ 超过蓄水池容量 {reservoir_capacity:.1f} m³，"
            f"需要依靠潮汐补水才能完成磨粉"
        )

    if total_hours > 12:
        warnings.append(f"磨坊计划运行 {total_hours:.1f} 小时，时间较长，需确保有足够的潮汐周期补水")

    return total_water_needed, warnings


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


def parse_tide_csv(csv_content: str) -> Tuple[List[Dict], str]:
    import csv
    import io

    records = []
    try:
        reader = csv.DictReader(io.StringIO(csv_content))
        fieldnames = reader.fieldnames

        time_col = None
        level_col = None

        for name in fieldnames:
            name_lower = name.lower().strip()
            if time_col is None and ("time" in name_lower or "小时" in name or "时间" in name or "hour" in name_lower):
                time_col = name
            if level_col is None and ("level" in name_lower or "tide" in name_lower or "潮位" in name or "水位" in name):
                level_col = name

        if time_col is None and len(fieldnames) >= 1:
            time_col = fieldnames[0]
        if level_col is None and len(fieldnames) >= 2:
            level_col = fieldnames[1]

        if time_col is None or level_col is None:
            return [], "CSV 文件格式不正确，需要包含时间和潮位列"

        for i, row in enumerate(reader):
            try:
                time_hour = float(row[time_col].strip())
                tide_level = float(row[level_col].strip())
                records.append({"time_hour": time_hour, "tide_level": tide_level})
            except (ValueError, KeyError) as e:
                return [], f"第 {i+2} 行数据解析失败: {e}"

        if not records:
            return [], "CSV 文件中没有有效数据"

        return records, f"成功解析 {len(records)} 条潮位记录"

    except Exception as e:
        return [], f"CSV 解析失败: {str(e)}"


def validate_manual_gate_schedule(
    gate_schedule: List[Dict],
    total_hours: float = 24.0,
) -> Tuple[bool, str, List[str]]:
    warnings = []

    if not gate_schedule:
        return True, "手动闸门计划有效（空）", warnings

    sorted_schedule = sorted(gate_schedule, key=lambda s: s["start_hour"])

    for i, sched in enumerate(sorted_schedule):
        if "start_hour" not in sched or "end_hour" not in sched or "open_ratio" not in sched:
            return False, f"第 {i+1} 条闸门记录格式不正确", warnings

        if sched["start_hour"] < 0 or sched["start_hour"] > total_hours:
            return False, f"第 {i+1} 条记录的开始时间 {sched['start_hour']} 超出范围 [0, {total_hours}]", warnings
        if sched["end_hour"] < 0 or sched["end_hour"] > total_hours:
            return False, f"第 {i+1} 条记录的结束时间 {sched['end_hour']} 超出范围 [0, {total_hours}]", warnings
        if sched["start_hour"] >= sched["end_hour"]:
            return False, f"第 {i+1} 条记录的开始时间必须小于结束时间", warnings
        if sched["open_ratio"] < 0 or sched["open_ratio"] > 100:
            return False, f"第 {i+1} 条记录的开启比例 {sched['open_ratio']}% 超出范围 [0, 100]", warnings

    for i in range(len(sorted_schedule) - 1):
        if sorted_schedule[i]["end_hour"] > sorted_schedule[i + 1]["start_hour"] + 0.001:
            return False, f"闸门时段 {i+1} 与 {i+2} 重叠", warnings

    if sorted_schedule[0]["start_hour"] > 0.01:
        warnings.append(f"0:00 - {sorted_schedule[0]['start_hour']}:00 闸门未设置，默认关闭")

    if sorted_schedule[-1]["end_hour"] < total_hours - 0.01:
        warnings.append(f"{sorted_schedule[-1]['end_hour']}:00 - {total_hours}:00 闸门未设置，默认关闭")

    return True, "手动闸门计划有效", warnings


def get_gate_ratio_at_time(
    manual_schedule: List[Dict],
    time_hour: float,
    default_ratio: float = 0.0,
) -> float:
    for sched in manual_schedule:
        if sched["start_hour"] <= time_hour < sched["end_hour"]:
            return sched["open_ratio"]
    return default_ratio


def run_simulation(
    params: SimulationParams,
    tide_records: List[Dict],
    mill_schedule: List[Dict],
    total_hours: float = 24.0,
    manual_gate_schedule: List[Dict] = None,
) -> Tuple[List[Dict], List[Dict], List[str]]:
    warnings = []

    use_manual_gate = manual_gate_schedule is not None and len(manual_gate_schedule) > 0

    if use_manual_gate:
        valid, msg, gate_warnings = validate_manual_gate_schedule(manual_gate_schedule, total_hours)
        if not valid:
            raise ValueError(msg)
        warnings.extend(gate_warnings)

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

        if use_manual_gate:
            gate_ratio = get_gate_ratio_at_time(manual_gate_schedule, t, 0.0)
        else:
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


def generate_multi_day_tide_records(num_days: int = 7, base_level: float = 2.5, amplitude: float = 2.0) -> List[Dict]:
    records = []
    total_hours = num_days * 24.0
    step_hours = 1.0

    t = 0.0
    while t <= total_hours + 0.001:
        tide_level = base_level + amplitude * math.sin(2 * math.pi * (t - 6) / 12.4)
        spring_neap_factor = 0.85 + 0.15 * math.sin(2 * math.pi * t / (14.8 * 24))
        tide_level = base_level + amplitude * spring_neap_factor * math.sin(2 * math.pi * (t - 6) / 12.4)
        records.append({"time_hour": round(t, 2), "tide_level": round(tide_level, 2)})
        t += step_hours

    return records


def validate_multi_day_tide_records(tide_records: List[Dict], min_hours: float = 24.0) -> Tuple[bool, str]:
    if not tide_records:
        return False, "潮位记录不能为空"

    if len(tide_records) < 2:
        return False, "至少需要2条潮位记录"

    for i, record in enumerate(tide_records):
        if "time_hour" not in record or "tide_level" not in record:
            return False, f"第 {i+1} 条记录格式不正确"
        if record["time_hour"] < 0:
            return False, f"第 {i+1} 条记录的时间不能为负值"
        if record["tide_level"] < 0:
            return False, f"第 {i+1} 条记录的潮位不能为负值"

    sorted_records = sorted(tide_records, key=lambda r: r["time_hour"])

    for i in range(len(sorted_records) - 1):
        if sorted_records[i]["time_hour"] == sorted_records[i + 1]["time_hour"]:
            return False, f"存在重复的时间点: {sorted_records[i]['time_hour']}"

    total_span = sorted_records[-1]["time_hour"] - sorted_records[0]["time_hour"]
    if total_span < min_hours - 0.01:
        return False, f"潮位记录覆盖时长不足 {min_hours} 小时，当前仅 {total_span:.1f} 小时"

    if sorted_records[0]["time_hour"] > 0.01:
        return False, f"潮位记录必须从0小时开始，当前起始时间: {sorted_records[0]['time_hour']} 小时"

    return True, f"潮位记录有效，覆盖 {total_span:.1f} 小时 ({total_span/24:.1f} 天)"


def get_total_hours(tide_records: List[Dict]) -> float:
    sorted_records = sorted(tide_records, key=lambda r: r["time_hour"])
    return sorted_records[-1]["time_hour"] - sorted_records[0]["time_hour"]


def generate_daily_mill_schedule_for_multi_day(
    num_days: int,
    daily_schedule: List[Dict] = None,
) -> List[Dict]:
    if daily_schedule is None:
        daily_schedule = generate_default_mill_schedule()

    full_schedule = []
    for day in range(num_days):
        day_offset = day * 24.0
        for sched in daily_schedule:
            full_schedule.append({
                "start_hour": day_offset + sched["start_hour"],
                "end_hour": day_offset + sched["end_hour"],
            })

    return full_schedule


def compute_simulation_metrics(results: List[Dict], params: SimulationParams) -> Dict:
    if not results:
        return {}

    water_volumes = [r["water_volume"] for r in results]
    gate_ratios = [r["gate_open_ratio"] for r in results]
    mill_running = [r["mill_running"] for r in results]
    tide_levels = [r["tide_level"] for r in results]

    time_step = params.time_step_hours

    total_mill_hours = sum(1 for m in mill_running if m) * time_step

    total_gate_open_hours = sum(1 for g in gate_ratios if g > 0.5) * time_step

    total_inflow = 0.0
    total_outflow = 0.0
    for i in range(1, len(results)):
        vol_change = water_volumes[i] - water_volumes[i - 1]
        mill_consumed = params.mill_power_consumption * time_step if mill_running[i] else 0.0
        net_flow = vol_change + mill_consumed
        if net_flow > 0:
            total_inflow += net_flow
        else:
            total_outflow += abs(net_flow)

    overflow_volume = 0.0
    for i in range(len(results)):
        if water_volumes[i] >= params.reservoir_capacity - 0.01:
            if i < len(results) - 1 and gate_ratios[i] > 0:
                overflow_volume += params.gate_max_flow * (gate_ratios[i] / 100.0) * time_step * 0.1

    avg_water_level = sum(water_volumes) / len(water_volumes)
    capacity_utilization = avg_water_level / params.reservoir_capacity * 100

    return {
        "total_mill_hours": round(total_mill_hours, 2),
        "total_gate_open_hours": round(total_gate_open_hours, 2),
        "total_inflow": round(total_inflow, 2),
        "total_outflow": round(total_outflow, 2),
        "overflow_volume": round(overflow_volume, 2),
        "avg_water_volume": round(avg_water_level, 2),
        "capacity_utilization_pct": round(capacity_utilization, 2),
        "max_water_volume": round(max(water_volumes), 2),
        "min_water_volume": round(min(water_volumes), 2),
        "max_tide_level": round(max(tide_levels), 2),
        "min_tide_level": round(min(tide_levels), 2),
        "num_days": round((results[-1]["time_hour"] - results[0]["time_hour"]) / 24, 2),
    }
