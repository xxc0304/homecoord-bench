"""M05: distinct synthetic room-response models with a shared power budget."""

from __future__ import annotations

import json

from evaluate import ROOT

OUT = ROOT / "results" / "m05_multiroom_synthetic_20260928.json"
PROFILES = {
    "living": {"agent": "LivingComfortAgent", "initial_c": 29.0,
               "target_c": 25.0, "outdoor_c": 32.0, "leak_per_s": 0.00012,
               "cooling_c_per_s": 0.004, "power_kw": 1.4, "deadline_s": 1500},
    "bedroom": {"agent": "BedroomComfortAgent", "initial_c": 27.0,
                "target_c": 24.0, "outdoor_c": 31.0, "leak_per_s": 0.00008,
                "cooling_c_per_s": 0.003, "power_kw": 1.1, "deadline_s": 1700},
}
POLICIES = ("release_order", "earliest_deadline", "largest_remaining_gap")


def simulate(capacity_kw: float, bedroom_release_s: int, policy: str) -> dict:
    if policy not in POLICIES or capacity_kw <= 0 or bedroom_release_s < 0:
        raise ValueError((capacity_kw, bedroom_release_s, policy))
    temperatures = {room: profile["initial_c"] for room, profile in PROFILES.items()}
    reached = {room: None for room in PROFILES}
    temperature_at_deadline = {room: None for room in PROFILES}
    water_work_kws = 900.0
    water_completed_s = None
    peak_power_kw = 0.0
    room_running_seconds = {room: 0 for room in PROFILES}
    for second in range(0, 3600):
        candidates = []
        for room, profile in PROFILES.items():
            release = bedroom_release_s if room == "bedroom" else 0
            if second >= release and second < profile["deadline_s"] and temperatures[room] > profile["target_c"]:
                candidates.append((room, profile["power_kw"], profile["deadline_s"], release,
                                   max(0.0, temperatures[room] - profile["target_c"])))
        if water_completed_s is None:
            candidates.append(("water", 1.5, 1200, 0, water_work_kws / 900))
        if policy == "release_order":
            candidates.sort(key=lambda x: (x[3], x[0]))
        elif policy == "earliest_deadline":
            candidates.sort(key=lambda x: (x[2], x[0]))
        else:
            candidates.sort(key=lambda x: (-x[4], x[2], x[0]))
        selected, load = set(), 0.0
        for name, power, *_ in candidates:
            if load + power <= capacity_kw + 1e-9:
                selected.add(name)
                load += power
        if load > capacity_kw + 1e-9:
            raise AssertionError("shared capacity violated")
        peak_power_kw = max(peak_power_kw, load)
        if "water" in selected:
            water_work_kws -= 1.5
            if water_work_kws <= 1e-9:
                water_completed_s = second + 1
        for room, profile in PROFILES.items():
            temperature = temperatures[room]
            temperature += profile["leak_per_s"] * (profile["outdoor_c"] - temperature)
            if room in selected:
                temperature -= profile["cooling_c_per_s"]
                room_running_seconds[room] += 1
            temperatures[room] = temperature
            if (reached[room] is None and second >= (bedroom_release_s if room == "bedroom" else 0)
                    and temperature <= profile["target_c"]):
                reached[room] = second + 1
            if second + 1 == profile["deadline_s"]:
                temperature_at_deadline[room] = temperature
        if second + 1 >= max(p["deadline_s"] for p in PROFILES.values()) and water_completed_s is not None:
            break
    room_on_time = {room: temperature_at_deadline[room] is not None and
                           temperature_at_deadline[room] <= p["target_c"] + 0.05
                    for room, p in PROFILES.items()}
    room_target_deficit = {
        room: (None if temperature_at_deadline[room] is None else
               round(max(0.0, temperature_at_deadline[room] - p["target_c"]), 3))
        for room, p in PROFILES.items()
    }
    return {"capacity_kw": capacity_kw, "bedroom_release_s": bedroom_release_s,
            "policy": policy,
            "agents": ["LivingComfortAgent", "BedroomComfortAgent", "WaterAgent"],
            "room_reached_target_s": reached, "room_on_time": room_on_time,
            "room_temperature_at_deadline_c": {k: round(v, 3) if v is not None else None
                                               for k, v in temperature_at_deadline.items()},
            "room_target_deficit_at_deadline_c": room_target_deficit,
            "worst_room_target_deficit_c": (max(room_target_deficit.values())
                                      if all(x is not None for x in room_target_deficit.values())
                                      else None),
            "water_completed_s": water_completed_s,
            "water_on_time": water_completed_s is not None and water_completed_s <= 1200,
            "room_running_s": room_running_seconds,
            "final_room_temperature_c": {k: round(v, 3) for k, v in temperatures.items()},
            "peak_power_kw": peak_power_kw}


def run() -> dict:
    rows = [simulate(capacity, arrival, policy) for capacity in (2.5, 4.0)
            for arrival in (0, 300) for policy in POLICIES]
    payload = {"status": "independent_room_synthetic_mechanism_not_benchmark",
               "api_calls": 0, "room_profiles": PROFILES,
               "water_contract": {"power_kw": 1.5, "work_kws": 900,
                                  "release_s": 0, "deadline_s": 1200},
               "time_step_s": 1,
               "excluded_claims": ["calibrated room dynamics", "actual home capacity",
                                   "resident comfort feedback", "independent homes"],
               "rows": rows}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


if __name__ == "__main__":
    print(json.dumps({"rows": len(run()["rows"]), "output": str(OUT)}, ensure_ascii=False))
