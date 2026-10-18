"""Behavioral checks for the five synthetic structure probes."""

from copy import deepcopy
import unittest

from probe_d03_return_message import TimedClient, make_episode
from probe_m04_joint_environment import simulate as m04
from probe_m05_multiroom import PROFILES, simulate as m05
from probe_m06_d02_dynamic_contracts import base_jobs
from runtime.dynamic_contracts import simulate as dynamic_simulate, validate_contracts
from runtime.event_simulator import run_event_simulation


def test_d03_report_completion_releases_comfort_and_changes_timing():
    episode = make_episode(1150)
    rows = []
    for latency in (1, 600):
        trace, result = run_event_simulation(deepcopy(episode), TimedClient(latency),
                                             "ConstraintCoordinator", "",
                                             shared_safety_gate=True)
        releases = {e["task_id"]: e["timestamp_ms"] for e in trace["events"]
                    if e["type"] == "task_released"}
        report_done = next(e["timestamp_ms"] for e in trace["events"]
                           if e["type"] == "action_completed" and e["task_id"] == "report_return")
        assert releases["cool_on_return"] == report_done
        assert result["task_service"]["report_return"]
        rows.append((releases["cool_on_return"], result["task_service"]["peak_off"]))
    assert rows[0][0] < rows[1][0]
    assert rows[0][1] != rows[1][1]


def test_m04_joint_capacity_and_co2_factors_are_both_active():
    tight = m04(1600, 3.0, "climate_first")
    loose = m04(1600, 4.0, "climate_first")
    control = m04(850, 3.0, "climate_first")
    assert tight["peak_power_kw"] <= 3.0
    assert loose["peak_power_kw"] <= 4.0
    assert not tight["all_by_deadline"] and loose["all_by_deadline"]
    assert control["vent_completion_ms"] == 0
    assert tight["vent_completion_ms"] > 0


def test_m05_rooms_are_distinct_and_wait_tradeoff_is_visible():
    assert PROFILES["living"]["cooling_c_per_s"] != PROFILES["bedroom"]["cooling_c_per_s"]
    tight = m05(2.5, 0, "earliest_deadline")
    loose = m05(4.0, 0, "earliest_deadline")
    assert tight["peak_power_kw"] <= 2.5
    assert loose["peak_power_kw"] <= 4.0
    assert tight["water_on_time"]
    assert all(loose["room_on_time"].values())
    assert not all(tight["room_on_time"].values())


def test_m06_pause_ack_and_mode_contracts():
    jobs = base_jobs()
    fixed = dynamic_simulate(jobs, [{"at_ms": 0, "capacity_kw": 6.0,
                                     "report_delay_ms": 0}], mode_choice=False)
    assert not fixed["jobs"]["water"]["deadline_met"]
    paused_jobs = deepcopy(jobs)
    paused_jobs[0]["interruptible"] = True
    paused_jobs[2]["interruptible"] = True
    paused = dynamic_simulate(paused_jobs, [{"at_ms": 0, "capacity_kw": 6.0,
                                             "report_delay_ms": 0}], mode_choice=False)
    assert paused["jobs"]["water"]["deadline_met"]
    assert any(e["type"] == "voluntary_pause" for e in paused["events"])
    assert paused["capacity_safe"]


def test_d02_report_delay_changes_rejected_starts_but_hardware_keeps_safety():
    jobs = base_jobs()
    jobs[0]["interruptible"] = True
    events = [{"at_ms": 0, "capacity_kw": 8.0, "report_delay_ms": 0},
              {"at_ms": 1500, "capacity_kw": 5.0, "report_delay_ms": 1000}]
    delayed = dynamic_simulate(jobs, events, mode_choice=False)
    prompt = dynamic_simulate(jobs, [events[0], {**events[1], "report_delay_ms": 0}],
                              mode_choice=False)
    assert delayed["capacity_safe"] and prompt["capacity_safe"]
    assert delayed["hardware_start_rejections"] > prompt["hardware_start_rejections"]
    assert sum(j["trip_count"] for j in delayed["jobs"].values()) >= 1
    after_completion = dynamic_simulate(jobs, [events[0],
        {"at_ms": 9000, "capacity_kw": 5.0, "report_delay_ms": 1000}],
        mode_choice=False)
    assert any(e["type"] == "energy_agent_report" and e["at_ms"] == 10_000
               for e in after_completion["events"])
    try:
        validate_contracts(jobs, [events[1], events[0]])
    except ValueError:
        pass
    else:
        raise AssertionError("unordered capacity events accepted")


class RemainingStructureProbeTests(unittest.TestCase):
    def test_d03(self):
        test_d03_report_completion_releases_comfort_and_changes_timing()

    def test_m04(self):
        test_m04_joint_capacity_and_co2_factors_are_both_active()

    def test_m05(self):
        test_m05_rooms_are_distinct_and_wait_tradeoff_is_visible()

    def test_m06(self):
        test_m06_pause_ack_and_mode_contracts()

    def test_d02(self):
        test_d02_report_delay_changes_rejected_starts_but_hardware_keeps_safety()
