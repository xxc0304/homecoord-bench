"""Write engineering traces only. No model client, environment keys or network."""
import json
from pathlib import Path
from time import perf_counter

from time_protocol import run_case


def main():
    start = perf_counter()
    runs = []
    for structure in ("dependency", "resource"):
        for policy in ("immediate", "wait_released"):
            for durations in ((4000, 4000), (3_600_000, 1_800_000)):
                for latency in ((300, 700), (8000, 12000)):
                    run = run_case(structure, policy, durations, latency)
                    reference = run_case(structure, policy, durations, latency,
                                         clock_mode="continuous_reference")
                    run["reference_semantics_equal"] = all(
                        run[key] == reference[key]
                        for key in ("trace", "requests", "completion_ms", "on_time"))
                    runs.append(run)
    output = {"schema": "homecoord-hybrid-clock-engineering-pilot-v1",
              "runs": runs, "run_count": len(runs),
              "logical_scripted_requests": sum(r["model_request_count"] for r in runs),
              "actual_api_requests": 0, "api_cost_usd": 0,
              "offline_execution_wall_seconds": perf_counter() - start,
              "all_reference_semantics_equal": all(r["reference_semantics_equal"] for r in runs),
              "limitations": ["not integrated into the latest live runner",
                              "model latencies and outputs are scripted",
                              "resource and duration fixtures are synthetic",
                              "no new benchmark findings or live concurrency evidence"]}
    target = Path(__file__).with_name("pilot_results.json")
    target.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in output.items() if key != "runs"},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
