"""Generate isolated, provenance-labelled C1/C3 review episodes.

These episodes are design probes, not benchmark scoring data.  Existing review
packets and historical result files are intentionally left untouched.
"""

from __future__ import annotations

import json
import math
import hashlib
from copy import deepcopy
from pathlib import Path

from make_representative_revision_drafts import make_c1_pair
from probe_physical_capacity_v2 import make_episode as make_ev_water_episode


ROOT = Path(__file__).resolve().parent
OUT = ROOT / "revision_drafts" / "20260928_provenance_pilot"
GENERATOR_VERSION = "provenance-pilot-0.1"
WATER_LITERS = 40 * 3.785411784  # The cited heater is rated at 40 US gallons.
WATER_POWER_KW = 3.8  # Rated element, not a measured time-series.
EV_POWER_KW = 4.0  # Assumption within the cited public Level-2 range.
EFFICIENCY = 0.9  # Stress-test assumption, not a measured efficiency.


def _mark(episode: dict, family: str, condition: str) -> dict:
    episode["episode_id"] = f"HC-PROV-{family}-{condition.upper()}"
    episode["generator_version"] = GENERATOR_VERSION
    episode["review_status"] = "provenance_pilot_unreviewed_not_scored"
    episode["source_type"] = "controlled_simulation_from_existing_template"
    episode["data_tier"] = "mechanism_only"
    episode["provenance_manifest"] = "manifest.json"
    return episode


def make_c1() -> list[dict]:
    result = []
    for source in make_c1_pair():
        episode = deepcopy(source)
        condition = "overlap" if "CONFLICT" in source["episode_id"] else "nonoverlap"
        _mark(episode, "C1", condition)
        episode["variant"] = {"family": "C1", "condition": condition,
                              "changed_factor": "energy_task_release_at_ms"}
        # A cooling set point is a device command. It is not an observed room
        # temperature; the old 29-to-24 C jump is intentionally removed.
        comfort = next(x for x in episode["task_stream"] if x["task_id"] == "comfort_cool")
        energy = next(x for x in episode["task_stream"] if x["task_id"] == "peak_off")
        comfort["goal"] = "Set the living-room HVAC to cooling at a 24 C set point for the resident request."
        energy["goal"] = "Switch the living-room HVAC off for a separate energy-saving request."
        energy_agent = next(agent for agent in episode["agents"]
                            if agent["agent_id"] == "EnergyAgent")
        # Specialists receive their own task and device state; the coordinator
        # holds the cross-task comfort priority. This is explicit information
        # asymmetry, not a hidden claim that the energy specialist ignored it.
        energy_agent["observable_state"] = ["devices.living_hvac"]
        energy_agent["goal_visibility"] = "local"
        energy_agent["constraint_visibility"] = "local"
        energy_agent["policy_constraints"] = []
        episode["goals"] = [
            {"path": "request.comfort_active", "op": "eq", "value": False},
            {"path": "devices.living_hvac", "op": "eq", "value": "forced_off"},
        ]
        episode["exogenous_events"] = [{
            "at_ms": 6000,
            "event": "cooling_request_window_ends",
            "new_state_version": 102,
            "patch": {"request.comfort_active": False},
        }]
        for grounding in episode["action_grounding"]:
            if grounding["operation"] == "cool":
                # Completion must not resurrect a device switched off by a
                # later command. The resident request ends independently.
                grounding["completion_effects"] = {}
        episode["calibration"] = {
            "status": "synthetic_service_window",
            "physical_parameters_verified": False,
            "scored_claims": ["command_order", "process_constraint", "required_command_issued"],
            "excluded_claims": ["room_temperature_change", "comfort_delivered", "real_device_latency", "energy_saving"],
        }
        episode["parameter_provenance"] = {
            "setpoint_c": {"value": 24, "class": "task_request_not_measured_temperature"},
            "cooling_request_window_ms": {"value": 6000, "class": "synthetic_exogenous_event"},
            "energy_task_release_at_ms": {"value": energy["release_at_ms"],
                                          "class": "controlled_experimental_factor"},
        }
        episode["draft_notes"] = [
            "Separate review-only candidate; the 2026-09-27 blind-review packet is unchanged.",
            "The resident request ends after a synthetic 6 s window, not when a cooling command completes.",
            "No room-temperature or real energy claim is scored.",
            "EnergyAgent sees its own task and HVAC state, not the separate comfort request or global constraint.",
            "Required-action service counts issued commands, not six seconds of delivered thermal comfort.",
        ]
        next(item for item in episode["tool_catalog"] if item["agent_id"] == "EnergyAgent")[
            "description"
        ] = "Switch the living-room HVAC off for the energy-saving request."
        result.append(episode)
    return result


def make_c3() -> list[dict]:
    result = []
    # Challenge conditions are declared before policy comparison. The capacity
    # is an assumed managed-load budget, not an observed household breaker.
    for capacity_kw, condition in ((7.0, "below"), (7.8, "equal"), (9.0, "above")):
        episode = make_ev_water_episode("conflict")
        _mark(episode, "C3", condition)
        episode["variant"] = {"family": "C3", "condition": condition,
                              "changed_factor": "managed_load_budget_kw"}
        episode["home"]["resources"]["max_power_kw"] = capacity_kw
        episode["home"]["resources"]["capacity_scope"] = "assumed_managed_load_budget"
        next(rule for rule in episode["conflict_rules"] if rule["type"] == "C3")["capacity"] = capacity_kw

        state = episode["initial_state"]["values"]
        state["water"]["tank_liters"] = WATER_LITERS
        state["water"].pop("shower_deadline_ms", None)
        state["vehicle"].pop("departure_deadline_ms", None)
        for agent in episode["agents"]:
            agent["observable_state"] = [path for path in agent["observable_state"]
                                         if not path.endswith("deadline_ms")]
        for task in episode["task_stream"]:
            task.pop("completion_deadline_ms", None)
            if task["task_id"] == "charge_ev":
                task["goal"] = "Charge the 60 kWh EV battery from 20% to at least 50%."
            else:
                task["goal"] = "Heat the 40 US gallon water tank from 35 C to at least 50 C."

        water_kwh = WATER_LITERS * 4.186 * (50 - 35) / 3600
        water_ms = math.ceil(water_kwh / (WATER_POWER_KW * EFFICIENCY) * 3_600_000)
        for grounding in episode["action_grounding"]:
            if grounding["operation"] == "heat":
                grounding["power_kw"] = WATER_POWER_KW
                grounding["duration_ms"] = water_ms
        for task in episode["task_stream"]:
            if task["task_id"] == "heat_water":
                task["action_template"]["power_kw"] = WATER_POWER_KW
                task["action_template"]["duration_ms"] = water_ms

        episode["physical_assumptions"].update({
            "water_heater_input_kw": WATER_POWER_KW,
            "tank_liters": WATER_LITERS,
            "efficiency": EFFICIENCY,
            "capacity_scope": "assumed_managed_load_budget",
            "status": "partly_spec_anchored_not_device_calibrated",
        })
        episode["calibration"] = {
            "status": "partly_spec_anchored_synthetic_capacity",
            "physical_parameters_verified": False,
            "scored_claims": ["capacity_constraint", "task_service", "simulated_completion"],
            "excluded_claims": ["real_household_prevalence", "real_energy_saving", "real_device_latency"],
        }
        episode["parameter_provenance"] = {
            "heater_element_rating_kw": {"value": WATER_POWER_KW, "class": "public_product_spec",
                                         "source_id": "AO_SMITH_E6_40H38D_TTP"},
            "assumed_active_element_count": {"value": 1, "class": "synthetic_control_assumption"},
            "tank_us_gallons": {"value": 40, "class": "public_product_spec",
                                "source_id": "AO_SMITH_E6_40H38D_TTP"},
            "ev_charge_power_kw": {"value": EV_POWER_KW, "class": "synthetic_within_public_range",
                                   "source_id": "DOE_AFDC_LEVEL2_RANGE"},
            "battery_capacity_kwh": {"value": 60, "class": "synthetic_vehicle_profile"},
            "conversion_efficiency": {"value": EFFICIENCY, "class": "synthetic_assumption"},
            "managed_load_budget_kw": {"value": capacity_kw,
                                       "class": "controlled_experimental_factor_no_home_record"},
            "task_release_offset_ms": {"value": 100, "class": "synthetic_async_factor"},
        }
        episode["draft_notes"] = [
            "Separate review-only candidate; no household breaker or site budget was measured.",
            "The heater nameplate anchors rated power and volume only; heat-up time uses an idealized formula.",
            "The EV profile and efficiency are assumptions; no real deadline is claimed.",
        ]
        result.append(episode)
    return result


def build() -> list[dict]:
    return make_c1() + make_c3()


def write(out: Path = OUT) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    episodes = build()
    paths = []
    content_hashes = {}
    for episode in episodes:
        path = out / f"{episode['episode_id']}.json"
        content = json.dumps(episode, ensure_ascii=False, indent=2) + "\n"
        path.write_text(content, encoding="utf-8")
        paths.append(path)
        # Hash the exact bytes on disk; Windows text newline conversion may
        # differ from the in-memory JSON string.
        content_hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = {
        "status": "unreviewed_mechanism_pilot_not_benchmark_scoring_data",
        "generator_version": GENERATOR_VERSION,
        "predeclared_conditions": {"C1": ["overlap", "nonoverlap"],
                                   "C3_managed_load_budget_kw": [7.0, 7.8, 9.0]},
        "source_registry": {
            "AO_SMITH_E6_40H38D_TTP": {
                "url": "https://www.aosmithatlowes.com/products/water-heaters/electric-water-heaters/e6-40h38d-ttp/",
                "supports": "40 US gallon nominal tank and two 3800 W elements; does not establish whether one or both are energized during an action or the measured heating trajectory",
            },
            "DOE_AFDC_LEVEL2_RANGE": {
                "url": "https://afdc.energy.gov/fuels/electricity-stations",
                "supports": "Level-2 charging power range; does not identify a 4 kW home installation",
            },
            "SIMUHOME_HVAC_ADAPTER": {
                "local_report": "docs/C1_SIMUHOME_C3_SOURCE_AUDIT_2026-09-28.md",
                "supports": "HVAC device command-state cross-check only; not room-temperature calibration",
            },
        },
        "excluded_from_primary_claim": ["real_household_frequency", "real_1s_response",
                                        "real_energy_saving", "physical_temperature_trajectory"],
        "episode_ids": [e["episode_id"] for e in episodes],
        "episode_sha256": content_hashes,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                                       encoding="utf-8")
    return paths


if __name__ == "__main__":
    print(json.dumps({"paths": [str(path) for path in write()]}, ensure_ascii=False, indent=2))
