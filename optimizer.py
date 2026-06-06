from typing import List, Dict, Tuple
from dataclasses import dataclass, field
from simulation import (
    SimulationParams,
    run_simulation,
    interpolate_tide,
    get_total_hours,
    compute_simulation_metrics,
    generate_gate_schedule,
    calculate_gate_flow,
)
import math


@dataclass
class OptimizationConfig:
    optimization_target: str = "balanced"
    num_days: int = 7
    daily_mill_hours_target: float = 8.0
    mill_running_windows: List[Tuple[float, float]] = field(default_factory=list)

    def __post_init__(self):
        if not self.mill_running_windows:
            self.mill_running_windows = [(8.0, 12.0), (14.0, 18.0)]


@dataclass
class OptimizationResult:
    target: str
    mill_schedule: List[Dict]
    gate_schedule: List[Dict]
    simulation_results: List[Dict]
    metrics: Dict
    score: float = 0.0


def generate_mill_windows_for_day(
    day_offset: float,
    windows: List[Tuple[float, float]],
) -> List[Dict]:
    schedule = []
    for start, end in windows:
        schedule.append({
            "start_hour": day_offset + start,
            "end_hour": day_offset + end,
        })
    return schedule


def build_full_mill_schedule(
    num_days: int,
    daily_windows: List[Tuple[float, float]],
) -> List[Dict]:
    full_schedule = []
    for day in range(num_days):
        day_offset = day * 24.0
        full_schedule.extend(generate_mill_windows_for_day(day_offset, daily_windows))
    return full_schedule


def evaluate_schedule(
    params: SimulationParams,
    tide_records: List[Dict],
    mill_schedule: List[Dict],
    gate_schedule: List[Dict],
    target: str,
) -> Tuple[List[Dict], List[Dict], Dict, float]:
    total_hours = get_total_hours(tide_records)

    results, generated_gate, warnings = run_simulation(
        params,
        tide_records,
        mill_schedule,
        total_hours=total_hours,
        manual_gate_schedule=gate_schedule if gate_schedule else None,
    )

    metrics = compute_simulation_metrics(results, params)

    score = calculate_score(metrics, target, params)

    return results, generated_gate, metrics, score


def calculate_score(metrics: Dict, target: str, params: SimulationParams) -> float:
    if not metrics:
        return -float('inf')

    mill_hours = metrics.get("total_mill_hours", 0)
    overflow = metrics.get("overflow_volume", 0)
    avg_water = metrics.get("avg_water_volume", 0)
    capacity = params.reservoir_capacity

    if target == "water_saving":
        water_level_score = (avg_water / capacity) * 100
        overflow_penalty = overflow * 2
        mill_penalty = mill_hours * 0.5
        score = water_level_score - overflow_penalty - mill_penalty

    elif target == "high_yield":
        mill_score = mill_hours * 10
        overflow_penalty = overflow * 1
        water_penalty = max(0, (capacity * 0.2 - avg_water)) * 0.1
        score = mill_score - overflow_penalty - water_penalty

    elif target == "low_overflow":
        overflow_score = -overflow * 10
        mill_score = mill_hours * 2
        water_stability_score = (1 - abs(avg_water - capacity * 0.6) / (capacity * 0.6)) * 50
        score = overflow_score + mill_score + water_stability_score

    elif target == "balanced":
        mill_score = mill_hours * 3
        overflow_penalty = overflow * 3
        water_score = (avg_water / capacity) * 30
        score = mill_score + water_score - overflow_penalty

    else:
        score = mill_hours

    return round(score, 2)


def optimize_gate_schedule_heuristic(
    params: SimulationParams,
    tide_records: List[Dict],
    mill_schedule: List[Dict],
    target: str,
) -> Tuple[List[Dict], List[Dict], Dict, float]:
    total_hours = get_total_hours(tide_records)
    num_steps = int(total_hours / params.time_step_hours) + 1
    time_hours = [i * params.time_step_hours for i in range(num_steps)]
    tide_levels = interpolate_tide(tide_records, time_hours)

    best_gate_ratios = []
    best_score = -float('inf')

    configurations = generate_gate_strategies(target)

    for config in configurations:
        gate_ratios = simulate_gate_strategy(
            params, time_hours, tide_levels, mill_schedule, config
        )

        gate_schedule = gate_ratios_to_schedule(time_hours, gate_ratios)

        results, _, metrics, score = evaluate_schedule(
            params, tide_records, mill_schedule, gate_schedule, target
        )

        if score > best_score:
            best_score = score
            best_gate_ratios = gate_ratios
            best_results = results
            best_metrics = metrics
            best_gate_schedule = gate_schedule

    best_gate_schedule_final = generate_gate_schedule(
        time_hours, tide_levels,
        [params.volume_to_height(v) for v in [r["water_volume"] for r in best_results]],
        [r["gate_open_ratio"] for r in best_results],
    )

    return best_results, best_gate_schedule_final, best_metrics, best_score


def generate_gate_strategies(target: str) -> List[Dict]:
    strategies = []

    if target == "water_saving":
        high_thresholds = [0.5, 0.6, 0.7, 0.8]
        for ht in high_thresholds:
            strategies.append({
                "type": "conservative",
                "open_when_tide_high": True,
                "high_water_threshold": ht,
                "low_water_threshold": ht - 0.2,
                "gate_open_pct": 70.0,
            })

    elif target == "high_yield":
        thresholds = [0.2, 0.3, 0.4, 0.5]
        for t in thresholds:
            strategies.append({
                "type": "aggressive",
                "open_when_tide_high": True,
                "high_water_threshold": 0.9,
                "low_water_threshold": t,
                "gate_open_pct": 100.0,
                "open_during_mill_if_low": True,
            })

    elif target == "low_overflow":
        thresholds = [0.6, 0.7, 0.75, 0.8]
        for t in thresholds:
            strategies.append({
                "type": "moderate",
                "open_when_tide_high": True,
                "high_water_threshold": t,
                "low_water_threshold": t - 0.3,
                "gate_open_pct": 60.0,
                "close_before_overflow": True,
            })

    else:
        for ht in [0.5, 0.6, 0.7]:
            for lt in [0.2, 0.3]:
                strategies.append({
                    "type": "balanced",
                    "open_when_tide_high": True,
                    "high_water_threshold": ht,
                    "low_water_threshold": lt,
                    "gate_open_pct": 80.0,
                })

    return strategies


def simulate_gate_strategy(
    params: SimulationParams,
    time_hours: List[float],
    tide_levels: List[float],
    mill_schedule: List[Dict],
    config: Dict,
) -> List[float]:
    gate_ratios = []
    water_volume = params.initial_water_level

    high_threshold = params.reservoir_capacity * config.get("high_water_threshold", 0.7)
    low_threshold = params.reservoir_capacity * config.get("low_water_threshold", 0.3)
    gate_open_pct = config.get("gate_open_pct", 80.0)

    for i in range(len(time_hours)):
        t = time_hours[i]
        tide_level = tide_levels[i]

        water_height = water_volume / params.reservoir_area

        mill_running = any(
            s["start_hour"] <= t < s["end_hour"] for s in mill_schedule
        )

        gate_ratio = 0.0
        tide_higher_than_reservoir = tide_level > water_height + 0.05

        if config.get("open_when_tide_high", True):
            if tide_higher_than_reservoir and water_volume < high_threshold:
                gate_ratio = gate_open_pct
            elif water_volume < low_threshold and tide_higher_than_reservoir:
                gate_ratio = gate_open_pct

        if config.get("open_during_mill_if_low", False):
            if mill_running and water_volume < low_threshold and tide_higher_than_reservoir:
                gate_ratio = gate_open_pct

        if config.get("close_before_overflow", False):
            if water_volume > high_threshold * 0.9:
                gate_ratio = min(gate_ratio, gate_open_pct * 0.3)
            if water_volume >= high_threshold:
                gate_ratio = 0.0

        flow_rate = calculate_gate_flow(
            tide_level, water_height, gate_ratio, params.gate_max_flow
        )

        mill_consumption = 0.0
        if mill_running and water_volume > params.reservoir_capacity * 0.05:
            mill_consumption = params.mill_power_consumption * params.time_step_hours

        volume_change = flow_rate * params.time_step_hours - mill_consumption
        water_volume += volume_change
        water_volume = max(0.0, min(params.reservoir_capacity, water_volume))

        gate_ratios.append(gate_ratio)

    return gate_ratios


def gate_ratios_to_schedule(
    time_hours: List[float], gate_ratios: List[float]
) -> List[Dict]:
    if not time_hours or len(time_hours) < 2:
        return []

    schedule = []
    current_start = 0
    current_ratio = gate_ratios[0]

    threshold = 1.0

    for i in range(1, len(time_hours)):
        if abs(gate_ratios[i] - current_ratio) > threshold:
            if current_ratio > 0.5:
                start_time = time_hours[current_start]
                end_time = time_hours[i - 1]
                if end_time > start_time + 0.001:
                    schedule.append({
                        "start_hour": start_time,
                        "end_hour": end_time,
                        "open_ratio": current_ratio,
                    })
            current_start = i
            current_ratio = gate_ratios[i]

    if current_ratio > 0.5:
        start_time = time_hours[current_start]
        end_time = time_hours[-1]
        if end_time > start_time + 0.001:
            schedule.append({
                "start_hour": start_time,
                "end_hour": end_time,
                "open_ratio": current_ratio,
            })

    return schedule


def optimize_mill_schedule(
    params: SimulationParams,
    tide_records: List[Dict],
    target: str,
    num_days: int,
    daily_target_hours: float = 8.0,
) -> Tuple[List[Dict], List[Dict], Dict, float]:
    best_schedule = []
    best_score = -float('inf')
    best_results = []
    best_gate = []
    best_metrics = {}

    candidate_schedules = generate_candidate_mill_schedules(
        num_days, daily_target_hours, target
    )

    for mill_sched in candidate_schedules:
        results, gate_sched, metrics, score = optimize_gate_schedule_heuristic(
            params, tide_records, mill_sched, target
        )

        if score > best_score:
            best_score = score
            best_schedule = mill_sched
            best_results = results
            best_gate = gate_sched
            best_metrics = metrics

    return best_schedule, best_gate, best_results, best_metrics, best_score


def generate_candidate_mill_schedules(
    num_days: int,
    daily_hours: float,
    target: str,
) -> List[List[Dict]]:
    candidates = []

    base_configs = []

    if target == "high_yield":
        base_configs = [
            [(6.0, 10.0), (12.0, 16.0)],
            [(7.0, 11.0), (13.0, 17.0)],
            [(8.0, 12.0), (14.0, 18.0)],
            [(9.0, 13.0), (15.0, 19.0)],
            [(5.0, 9.0), (11.0, 15.0), (17.0, 19.0)],
            [(6.0, 10.0), (14.0, 18.0)],
        ]
    elif target == "water_saving":
        base_configs = [
            [(8.0, 11.0), (14.0, 17.0)],
            [(9.0, 12.0), (15.0, 18.0)],
            [(10.0, 13.0), (16.0, 19.0)],
            [(8.0, 12.0)],
            [(9.0, 13.0)],
        ]
    elif target == "low_overflow":
        base_configs = [
            [(7.0, 11.0), (13.0, 17.0)],
            [(8.0, 12.0), (14.0, 18.0)],
            [(9.0, 13.0), (15.0, 19.0)],
            [(6.0, 10.0), (12.0, 16.0), (18.0, 20.0)],
        ]
    else:
        base_configs = [
            [(8.0, 12.0), (14.0, 18.0)],
            [(7.0, 11.0), (13.0, 17.0)],
            [(9.0, 13.0), (15.0, 19.0)],
            [(8.5, 12.5), (14.5, 18.5)],
        ]

    for config in base_configs:
        total_daily = sum(end - start for start, end in config)
        if total_daily > 0:
            scale = daily_hours / total_daily
            scaled_config = []
            for start, end in config:
                mid = (start + end) / 2
                duration = (end - start) * scale
                new_start = mid - duration / 2
                new_end = mid + duration / 2
                new_start = max(0.0, min(24.0, new_start))
                new_end = max(0.0, min(24.0, new_end))
                if new_end - new_start > 0.5:
                    scaled_config.append((new_start, new_end))
            if scaled_config:
                full_schedule = build_full_mill_schedule(num_days, scaled_config)
                candidates.append(full_schedule)

    if not candidates:
        default_windows = [(8.0, 12.0), (14.0, 18.0)]
        candidates.append(build_full_mill_schedule(num_days, default_windows))

    return candidates


def run_full_optimization(
    params: SimulationParams,
    tide_records: List[Dict],
    target: str = "balanced",
    num_days: int = 7,
    daily_mill_hours: float = 8.0,
) -> OptimizationResult:
    mill_schedule, gate_schedule, sim_results, metrics, score = optimize_mill_schedule(
        params, tide_records, target, num_days, daily_mill_hours
    )

    return OptimizationResult(
        target=target,
        mill_schedule=mill_schedule,
        gate_schedule=gate_schedule,
        simulation_results=sim_results,
        metrics=metrics,
        score=score,
    )


def compare_optimization_targets(
    params: SimulationParams,
    tide_records: List[Dict],
    targets: List[str] = None,
    num_days: int = 7,
    daily_mill_hours: float = 8.0,
) -> List[OptimizationResult]:
    if targets is None:
        targets = ["water_saving", "high_yield", "low_overflow", "balanced"]

    results = []
    for target in targets:
        opt_result = run_full_optimization(
            params, tide_records, target, num_days, daily_mill_hours
        )
        results.append(opt_result)

    return results
