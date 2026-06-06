from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass, field
from simulation import (
    SimulationParams,
    run_simulation,
    get_total_hours,
    compute_simulation_metrics,
)
from optimizer import run_full_optimization


@dataclass
class StrategyComparisonResult:
    strategy_names: List[str]
    metrics_comparison: Dict[str, List[float]]
    best_by_metric: Dict[str, str]
    overall_ranking: List[str]


@dataclass
class TimelineAnalysis:
    time_hours: List[float]
    water_volumes: Dict[str, List[float]]
    gate_ratios: Dict[str, List[float]]
    mill_running: Dict[str, List[bool]]
    overflow_flags: Dict[str, List[bool]]
    rolling_yield: Dict[str, List[float]]
    rolling_risk: Dict[str, Dict[str, List[float]]]


@dataclass
class RiskAction:
    action_type: str
    action_description: str
    start_hour: Optional[float] = None
    end_hour: Optional[float] = None
    priority: str = "medium"

    def to_dict(self) -> Dict:
        return {
            "action_type": self.action_type,
            "action_description": self.action_description,
            "start_hour": self.start_hour,
            "end_hour": self.end_hour,
            "priority": self.priority,
        }


def compute_rolling_metrics(
    simulation_results: List[Dict],
    window_hours: float = 6.0,
    params: SimulationParams = None,
) -> Dict[str, List[float]]:
    if not simulation_results:
        return {}

    times = [r["time_hour"] for r in simulation_results]
    water_volumes = [r.get("water_volume", 0) for r in simulation_results]
    mill_running = [r.get("mill_running", False) for r in simulation_results]
    gate_open = [r.get("gate_open_ratio", 0) for r in simulation_results]

    n = len(simulation_results)
    if n == 0:
        return {}

    dt = times[1] - times[0] if n > 1 else 0.1
    window_steps = max(1, int(window_hours / dt))

    rolling_yield = []
    rolling_overflow_risk = []
    rolling_shortage_risk = []
    rolling_shutdown_risk = []

    capacity = params.reservoir_capacity if params else 100.0

    for i in range(n):
        start_idx = max(0, i - window_steps + 1)
        window = simulation_results[start_idx:i + 1]

        mill_hours_in_window = sum(
            1 for r in window if r.get("mill_running", False)
        ) * dt
        rolling_yield.append(mill_hours_in_window)

        if params:
            avg_water = sum(r.get("water_volume", 0) for r in window) / len(window)
            min_water = min(r.get("water_volume", 0) for r in window)
            max_water = max(r.get("water_volume", 0) for r in window)

            overflow_risk = max(0.0, (max_water / capacity - 0.85)) / 0.15 * 100
            overflow_risk = min(100.0, max(0.0, overflow_risk))
            rolling_overflow_risk.append(overflow_risk)

            shortage_risk = max(0.0, (0.25 - min_water / capacity)) / 0.25 * 100
            shortage_risk = min(100.0, max(0.0, shortage_risk))
            rolling_shortage_risk.append(shortage_risk)

            mill_availability = sum(
                1 for r in window if r.get("mill_running", False)
            ) / len(window)
            shutdown_risk = (1.0 - mill_availability) * 100
            rolling_shutdown_risk.append(shutdown_risk)
        else:
            rolling_overflow_risk.append(0.0)
            rolling_shortage_risk.append(0.0)
            rolling_shutdown_risk.append(0.0)

    return {
        "time_hours": times,
        "rolling_yield": rolling_yield,
        "rolling_overflow_risk": rolling_overflow_risk,
        "rolling_shortage_risk": rolling_shortage_risk,
        "rolling_shutdown_risk": rolling_shutdown_risk,
    }


def compare_strategies(
    strategies_data: List[Dict],
    strategy_names: List[str] = None,
) -> StrategyComparisonResult:
    if not strategies_data:
        return StrategyComparisonResult([], {}, {}, [])

    names = strategy_names if strategy_names else [
        f"策略 {i+1}" for i in range(len(strategies_data))
    ]

    all_metrics_keys = set()
    for s in strategies_data:
        metrics = s.get("metrics", {})
        all_metrics_keys.update(metrics.keys())

    metrics_comparison = {}
    for key in all_metrics_keys:
        metrics_comparison[key] = [
            s.get("metrics", {}).get(key, 0) for s in strategies_data
        ]

    best_by_metric = {}
    higher_is_better = {
        "total_mill_hours": True,
        "capacity_utilization_pct": True,
        "avg_water_volume": True,
        "max_water_volume": True,
        "total_inflow": True,
        "total_gate_open_hours": True,
    }

    lower_is_better = {
        "overflow_volume": True,
        "min_water_volume": False,
    }

    for key in all_metrics_keys:
        values = metrics_comparison[key]
        if higher_is_better.get(key, False):
            best_idx = values.index(max(values))
        elif lower_is_better.get(key, False):
            best_idx = values.index(min(values))
        else:
            best_idx = 0
        best_by_metric[key] = names[best_idx]

    scores = []
    for i, s in enumerate(strategies_data):
        metrics = s.get("metrics", {})
        score = 0.0

        mill_hours = metrics.get("total_mill_hours", 0)
        overflow = metrics.get("overflow_volume", 0)
        cap_util = metrics.get("capacity_utilization_pct", 0)

        score += mill_hours * 2.0
        score -= overflow * 1.5
        score += cap_util * 0.5

        scores.append(score)

    ranked_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
    overall_ranking = [names[i] for i in ranked_indices]

    return StrategyComparisonResult(
        strategy_names=names,
        metrics_comparison=metrics_comparison,
        best_by_metric=best_by_metric,
        overall_ranking=overall_ranking,
    )


def build_timeline_analysis(
    strategies_data: List[Dict],
    strategy_names: List[str] = None,
    params: SimulationParams = None,
    window_hours: float = 6.0,
) -> TimelineAnalysis:
    if not strategies_data:
        return TimelineAnalysis([], {}, {}, {}, {}, {}, {})

    names = strategy_names if strategy_names else [
        f"策略 {i+1}" for i in range(len(strategies_data))
    ]

    all_times = set()
    for s in strategies_data:
        sim_results = s.get("simulation_results", [])
        for r in sim_results:
            all_times.add(r["time_hour"])

    time_hours = sorted(all_times)

    water_volumes = {}
    gate_ratios = {}
    mill_running = {}
    overflow_flags = {}
    rolling_yield = {}
    rolling_risk = {name: {} for name in names}

    for i, s in enumerate(strategies_data):
        name = names[i]
        sim_results = s.get("simulation_results", [])

        wv = []
        gr = []
        mr = []
        of = []

        time_idx = {r["time_hour"]: r for r in sim_results}

        for t in time_hours:
            if t in time_idx:
                r = time_idx[t]
                wv.append(r.get("water_volume", 0))
                gr.append(r.get("gate_open_ratio", 0))
                mr.append(r.get("mill_running", False))
                of.append(r.get("overflow_flag", False))
            else:
                wv.append(None)
                gr.append(None)
                mr.append(None)
                of.append(None)

        water_volumes[name] = wv
        gate_ratios[name] = gr
        mill_running[name] = mr
        overflow_flags[name] = of

        rolling = compute_rolling_metrics(sim_results, window_hours, params)
        rolling_yield[name] = rolling.get("rolling_yield", [])

        rolling_risk[name]["overflow"] = rolling.get("rolling_overflow_risk", [])
        rolling_risk[name]["shortage"] = rolling.get("rolling_shortage_risk", [])
        rolling_risk[name]["shutdown"] = rolling.get("rolling_shutdown_risk", [])

    return TimelineAnalysis(
        time_hours=time_hours,
        water_volumes=water_volumes,
        gate_ratios=gate_ratios,
        mill_running=mill_running,
        overflow_flags=overflow_flags,
        rolling_yield=rolling_yield,
        rolling_risk=rolling_risk,
    )


def generate_strategy_from_optimization(
    params: SimulationParams,
    tide_records: List[Dict],
    target: str,
    num_days: int,
    daily_mill_hours: float,
) -> Dict:
    opt_result = run_full_optimization(
        params, tide_records, target=target, num_days=num_days,
        daily_mill_hours=daily_mill_hours,
    )

    return {
        "strategy_type": "optimized",
        "optimization_target": target,
        "simulation_results": opt_result.simulation_results,
        "metrics": opt_result.metrics,
        "mill_schedule": opt_result.mill_schedule,
        "gate_schedule": opt_result.gate_schedule,
        "score": opt_result.score,
    }


def generate_strategy_from_manual(
    params: SimulationParams,
    tide_records: List[Dict],
    mill_schedule: List[Dict],
    manual_gate_schedule: List[Dict] = None,
    total_hours: float = None,
) -> Dict:
    if total_hours is None:
        total_hours = get_total_hours(tide_records)

    sim_results, gate_schedule, warnings = run_simulation(
        params, tide_records, mill_schedule,
        manual_gate_schedule=manual_gate_schedule,
        total_hours=total_hours,
    )

    metrics = compute_simulation_metrics(sim_results, params)

    return {
        "strategy_type": "manual",
        "simulation_results": sim_results,
        "metrics": metrics,
        "mill_schedule": mill_schedule,
        "gate_schedule": gate_schedule,
        "warnings": warnings,
    }


def generate_risk_actions_from_recommendations(
    recommendations: List,
) -> List[RiskAction]:
    actions = []
    for rec in recommendations:
        action = RiskAction(
            action_type=getattr(rec, "action", ""),
            action_description=getattr(rec, "description", ""),
            start_hour=getattr(rec, "time_window", [None, None])[0],
            end_hour=getattr(rec, "time_window", [None, None])[1],
            priority=getattr(rec, "priority", "medium"),
        )
        actions.append(action)
    return actions


def format_metric_value(key: str, value: float) -> str:
    format_map = {
        "total_mill_hours": "{:.1f} h",
        "total_gate_open_hours": "{:.1f} h",
        "overflow_volume": "{:.1f} m³",
        "avg_water_volume": "{:.1f} m³",
        "max_water_volume": "{:.1f} m³",
        "min_water_volume": "{:.1f} m³",
        "capacity_utilization_pct": "{:.1f} %",
        "total_inflow": "{:.1f} m³",
    }
    fmt = format_map.get(key, "{:.2f}")
    return fmt.format(value)


def get_metric_label(key: str) -> str:
    label_map = {
        "total_mill_hours": "磨坊总运行时长",
        "total_gate_open_hours": "闸门累计开启时长",
        "overflow_volume": "溢流水量",
        "avg_water_volume": "平均蓄水量",
        "max_water_volume": "最高蓄水量",
        "min_water_volume": "最低蓄水量",
        "capacity_utilization_pct": "库容利用率",
        "total_inflow": "总补水量",
        "num_days": "天数",
    }
    return label_map.get(key, key)
