import sqlite3
import json
from datetime import datetime
from typing import List, Dict, Optional, Tuple


DB_PATH = "tide_mill.db"


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS scenarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            reservoir_capacity REAL NOT NULL,
            reservoir_area REAL NOT NULL DEFAULT 20.0,
            gate_max_flow REAL NOT NULL,
            mill_power_consumption REAL NOT NULL,
            initial_water_level REAL NOT NULL
        )
        """
    )

    try:
        cursor.execute("ALTER TABLE scenarios ADD COLUMN reservoir_area REAL NOT NULL DEFAULT 20.0")
    except sqlite3.OperationalError:
        pass

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS tide_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scenario_id INTEGER NOT NULL,
            time_index INTEGER NOT NULL,
            tide_level REAL NOT NULL,
            FOREIGN KEY (scenario_id) REFERENCES scenarios (id) ON DELETE CASCADE
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS mill_schedule (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scenario_id INTEGER NOT NULL,
            start_hour REAL NOT NULL,
            end_hour REAL NOT NULL,
            FOREIGN KEY (scenario_id) REFERENCES scenarios (id) ON DELETE CASCADE
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS simulation_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scenario_id INTEGER NOT NULL,
            time_hour REAL NOT NULL,
            tide_level REAL NOT NULL,
            water_level REAL NOT NULL,
            gate_open_ratio REAL NOT NULL,
            mill_running INTEGER NOT NULL,
            FOREIGN KEY (scenario_id) REFERENCES scenarios (id) ON DELETE CASCADE
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS gate_schedule (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scenario_id INTEGER NOT NULL,
            start_hour REAL NOT NULL,
            end_hour REAL NOT NULL,
            open_ratio REAL NOT NULL,
            action TEXT NOT NULL,
            FOREIGN KEY (scenario_id) REFERENCES scenarios (id) ON DELETE CASCADE
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS optimization_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scenario_id INTEGER NOT NULL,
            optimization_target TEXT NOT NULL,
            num_days INTEGER NOT NULL,
            daily_mill_hours REAL NOT NULL,
            score REAL NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (scenario_id) REFERENCES scenarios (id) ON DELETE CASCADE
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS optimization_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            optimization_run_id INTEGER NOT NULL,
            metric_key TEXT NOT NULL,
            metric_value REAL NOT NULL,
            FOREIGN KEY (optimization_run_id) REFERENCES optimization_runs (id) ON DELETE CASCADE
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS opt_mill_schedule (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            optimization_run_id INTEGER NOT NULL,
            start_hour REAL NOT NULL,
            end_hour REAL NOT NULL,
            FOREIGN KEY (optimization_run_id) REFERENCES optimization_runs (id) ON DELETE CASCADE
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS opt_gate_schedule (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            optimization_run_id INTEGER NOT NULL,
            start_hour REAL NOT NULL,
            end_hour REAL NOT NULL,
            open_ratio REAL NOT NULL,
            action TEXT NOT NULL,
            FOREIGN KEY (optimization_run_id) REFERENCES optimization_runs (id) ON DELETE CASCADE
        )
        """
    )

    conn.commit()
    conn.close()


def create_scenario(
    name: str,
    description: str,
    reservoir_capacity: float,
    reservoir_area: float,
    gate_max_flow: float,
    mill_power_consumption: float,
    initial_water_level: float,
    tide_records: List[Dict[str, float]],
    mill_schedule: List[Dict[str, float]],
) -> int:
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO scenarios (name, description, reservoir_capacity, reservoir_area, 
                               gate_max_flow, mill_power_consumption, initial_water_level)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (name, description, reservoir_capacity, reservoir_area, gate_max_flow, 
         mill_power_consumption, initial_water_level),
    )
    scenario_id = cursor.lastrowid

    for i, record in enumerate(tide_records):
        cursor.execute(
            """
            INSERT INTO tide_records (scenario_id, time_index, tide_level)
            VALUES (?, ?, ?)
            """,
            (scenario_id, i, record["tide_level"]),
        )

    for sched in mill_schedule:
        cursor.execute(
            """
            INSERT INTO mill_schedule (scenario_id, start_hour, end_hour)
            VALUES (?, ?, ?)
            """,
            (scenario_id, sched["start_hour"], sched["end_hour"]),
        )

    conn.commit()
    conn.close()
    return scenario_id


def get_scenario(scenario_id: int) -> Optional[Dict]:
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM scenarios WHERE id = ?", (scenario_id,))
    scenario_row = cursor.fetchone()

    if not scenario_row:
        conn.close()
        return None

    scenario = dict(scenario_row)

    cursor.execute(
        "SELECT time_index, tide_level FROM tide_records WHERE scenario_id = ? ORDER BY time_index",
        (scenario_id,),
    )
    tide_records = [
        {"time_index": row["time_index"], "tide_level": row["tide_level"]}
        for row in cursor.fetchall()
    ]
    scenario["tide_records"] = tide_records

    cursor.execute(
        "SELECT start_hour, end_hour FROM mill_schedule WHERE scenario_id = ? ORDER BY start_hour",
        (scenario_id,),
    )
    mill_schedule = [
        {"start_hour": row["start_hour"], "end_hour": row["end_hour"]}
        for row in cursor.fetchall()
    ]
    scenario["mill_schedule"] = mill_schedule

    conn.close()
    return scenario


def list_scenarios() -> List[Dict]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, name, description, created_at, updated_at, reservoir_capacity FROM scenarios ORDER BY updated_at DESC"
    )
    scenarios = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return scenarios


def update_scenario(
    scenario_id: int,
    name: str,
    description: str,
    reservoir_capacity: float,
    reservoir_area: float,
    gate_max_flow: float,
    mill_power_consumption: float,
    initial_water_level: float,
    tide_records: List[Dict[str, float]],
    mill_schedule: List[Dict[str, float]],
):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        UPDATE scenarios 
        SET name = ?, description = ?, reservoir_capacity = ?, reservoir_area = ?,
            gate_max_flow = ?, mill_power_consumption = ?, initial_water_level = ?, 
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (name, description, reservoir_capacity, reservoir_area, gate_max_flow,
         mill_power_consumption, initial_water_level, scenario_id),
    )

    cursor.execute("DELETE FROM tide_records WHERE scenario_id = ?", (scenario_id,))
    for i, record in enumerate(tide_records):
        cursor.execute(
            """
            INSERT INTO tide_records (scenario_id, time_index, tide_level)
            VALUES (?, ?, ?)
            """,
            (scenario_id, i, record["tide_level"]),
        )

    cursor.execute("DELETE FROM mill_schedule WHERE scenario_id = ?", (scenario_id,))
    for sched in mill_schedule:
        cursor.execute(
            """
            INSERT INTO mill_schedule (scenario_id, start_hour, end_hour)
            VALUES (?, ?, ?)
            """,
            (scenario_id, sched["start_hour"], sched["end_hour"]),
        )

    conn.commit()
    conn.close()


def delete_scenario(scenario_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM scenarios WHERE id = ?", (scenario_id,))
    conn.commit()
    conn.close()


def copy_scenario(scenario_id: int, new_name: str) -> int:
    scenario = get_scenario(scenario_id)
    if not scenario:
        raise ValueError(f"Scenario {scenario_id} not found")

    return create_scenario(
        name=new_name,
        description=f"Copy of {scenario['name']}",
        reservoir_capacity=scenario["reservoir_capacity"],
        reservoir_area=scenario.get("reservoir_area", 20.0),
        gate_max_flow=scenario["gate_max_flow"],
        mill_power_consumption=scenario["mill_power_consumption"],
        initial_water_level=scenario["initial_water_level"],
        tide_records=scenario["tide_records"],
        mill_schedule=scenario["mill_schedule"],
    )


def save_simulation_results(
    scenario_id: int,
    results: List[Dict[str, float]],
    gate_schedule: List[Dict[str, float]],
):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("DELETE FROM simulation_results WHERE scenario_id = ?", (scenario_id,))
    cursor.execute("DELETE FROM gate_schedule WHERE scenario_id = ?", (scenario_id,))

    for r in results:
        cursor.execute(
            """
            INSERT INTO simulation_results 
            (scenario_id, time_hour, tide_level, water_level, gate_open_ratio, mill_running)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                scenario_id,
                r["time_hour"],
                r["tide_level"],
                r["water_level"],
                r["gate_open_ratio"],
                1 if r["mill_running"] else 0,
            ),
        )

    for g in gate_schedule:
        cursor.execute(
            """
            INSERT INTO gate_schedule (scenario_id, start_hour, end_hour, open_ratio, action)
            VALUES (?, ?, ?, ?, ?)
            """,
            (scenario_id, g["start_hour"], g["end_hour"], g["open_ratio"], g["action"]),
        )

    cursor.execute(
        "UPDATE scenarios SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (scenario_id,),
    )

    conn.commit()
    conn.close()


def get_simulation_results(scenario_id: int) -> Tuple[List[Dict], List[Dict]]:
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT time_hour, tide_level, water_level, gate_open_ratio, mill_running
        FROM simulation_results WHERE scenario_id = ? ORDER BY time_hour
        """,
        (scenario_id,),
    )
    results = [dict(row) for row in cursor.fetchall()]
    for r in results:
        r["mill_running"] = bool(r["mill_running"])

    cursor.execute(
        """
        SELECT start_hour, end_hour, open_ratio, action
        FROM gate_schedule WHERE scenario_id = ? ORDER BY start_hour
        """,
        (scenario_id,),
    )
    gate_schedule = [dict(row) for row in cursor.fetchall()]

    conn.close()
    return results, gate_schedule


def save_optimization_run(
    scenario_id: int,
    optimization_target: str,
    num_days: int,
    daily_mill_hours: float,
    score: float,
    metrics: Dict,
    mill_schedule: List[Dict],
    gate_schedule: List[Dict],
) -> int:
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO optimization_runs (scenario_id, optimization_target, num_days, daily_mill_hours, score)
        VALUES (?, ?, ?, ?, ?)
        """,
        (scenario_id, optimization_target, num_days, daily_mill_hours, score),
    )
    run_id = cursor.lastrowid

    for key, value in metrics.items():
        if isinstance(value, (int, float)):
            cursor.execute(
                """
                INSERT INTO optimization_results (optimization_run_id, metric_key, metric_value)
                VALUES (?, ?, ?)
                """,
                (run_id, key, float(value)),
            )

    for sched in mill_schedule:
        cursor.execute(
            """
            INSERT INTO opt_mill_schedule (optimization_run_id, start_hour, end_hour)
            VALUES (?, ?, ?)
            """,
            (run_id, sched["start_hour"], sched["end_hour"]),
        )

    for g in gate_schedule:
        cursor.execute(
            """
            INSERT INTO opt_gate_schedule (optimization_run_id, start_hour, end_hour, open_ratio, action)
            VALUES (?, ?, ?, ?, ?)
            """,
            (run_id, g["start_hour"], g["end_hour"], g["open_ratio"], g["action"]),
        )

    conn.commit()
    conn.close()
    return run_id


def get_optimization_runs(scenario_id: int) -> List[Dict]:
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT * FROM optimization_runs 
        WHERE scenario_id = ? 
        ORDER BY created_at DESC
        """,
        (scenario_id,),
    )
    runs = [dict(row) for row in cursor.fetchall()]

    conn.close()
    return runs


def get_optimization_run_detail(run_id: int) -> Optional[Dict]:
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM optimization_runs WHERE id = ?", (run_id,))
    run_row = cursor.fetchone()

    if not run_row:
        conn.close()
        return None

    run = dict(run_row)

    cursor.execute(
        "SELECT metric_key, metric_value FROM optimization_results WHERE optimization_run_id = ?",
        (run_id,),
    )
    metrics = {}
    for row in cursor.fetchall():
        metrics[row["metric_key"]] = row["metric_value"]
    run["metrics"] = metrics

    cursor.execute(
        "SELECT start_hour, end_hour FROM opt_mill_schedule WHERE optimization_run_id = ? ORDER BY start_hour",
        (run_id,),
    )
    mill_schedule = [dict(row) for row in cursor.fetchall()]
    run["mill_schedule"] = mill_schedule

    cursor.execute(
        "SELECT start_hour, end_hour, open_ratio, action FROM opt_gate_schedule WHERE optimization_run_id = ? ORDER BY start_hour",
        (run_id,),
    )
    gate_schedule = [dict(row) for row in cursor.fetchall()]
    run["gate_schedule"] = gate_schedule

    conn.close()
    return run


def delete_optimization_run(run_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM optimization_runs WHERE id = ?", (run_id,))
    conn.commit()
    conn.close()
