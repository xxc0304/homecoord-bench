import unittest

from time_protocol import HybridClock, run_case


class ClockTests(unittest.TestCase):
    def test_no_jump_with_pending_request(self):
        clock = HybridClock()
        clock.begin("a")
        with self.assertRaises(RuntimeError):
            clock.fast_forward(3_600_000)

    def test_overlapping_delays_do_not_add_serially(self):
        clock = HybridClock()
        clock.begin("a")
        clock.begin("b")
        clock.advance_wall_ms(8000)
        self.assertEqual(clock.finish("a"), 8000)
        clock.advance_wall_ms(4000)
        self.assertEqual(clock.finish("b"), 12000)
        self.assertEqual(clock.now_ms, 12000)

    def test_jump_after_last_response(self):
        clock = HybridClock()
        clock.begin("a")
        clock.advance_wall_ms(8000)
        clock.finish("a")
        clock.fast_forward(3_608_100)
        self.assertEqual(clock.now_ms, 3_608_100)

    def test_bad_times(self):
        for value in (-1, 1.2, True):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    HybridClock().advance_wall_ms(value)

    def test_backwards_jump(self):
        clock = HybridClock()
        clock.advance_wall_ms(5)
        with self.assertRaises(ValueError):
            clock.fast_forward(4)

    def test_duplicate_request(self):
        clock = HybridClock()
        clock.begin("a")
        with self.assertRaises(ValueError):
            clock.begin("a")


class FixtureTests(unittest.TestCase):
    def test_long_dependency_closed_form(self):
        run = run_case("dependency", "immediate", (3_600_000, 1_800_000), (8000, 12000))
        self.assertEqual(run["completion_ms"], {"A": 3_608_100, "B": 5_408_200})
        self.assertEqual(run["model_request_count"], 2)
        self.assertEqual(run["actual_api_requests"], 0)

    def test_late_predecessor_response(self):
        run = run_case("dependency", "immediate", (4000, 4000), (12000, 8000))
        self.assertEqual(run["completion_ms"], {"A": 16100, "B": 20200})

    def test_no_model_call_per_virtual_tick(self):
        short = run_case("dependency", "immediate", (4000, 4000), (8000, 12000))
        long = run_case("dependency", "immediate", (3_600_000, 1_800_000), (8000, 12000))
        self.assertEqual(short["model_request_count"], long["model_request_count"])
        self.assertEqual(len(short["trace"]), len(long["trace"]))

    def test_resource_exclusion_closed_form(self):
        run = run_case("resource", "immediate", (3_600_000, 120000), (8000, 12000))
        self.assertEqual(run["completion_ms"], {"A": 3_608_100, "B": 3_728_200})
        self.assertFalse(run["on_time"]["B"])
        self.assertEqual(len(run["completion_ms"]), 2)

    def test_waiting_order_closed_form(self):
        run = run_case("resource", "wait_released", (3_600_000, 120000), (8000, 12000))
        self.assertEqual(run["completion_ms"], {"B": 132100, "A": 3_732_200})
        self.assertTrue(run["on_time"]["B"])

    def test_update_during_inflight_call_is_not_skipped(self):
        run = run_case("dependency", "immediate", (4000, 4000), (8000, 12000),
                       updates=((4000, {"authorised": False}),))
        self.assertEqual(run["completion_ms"], {})
        self.assertEqual(run["requests"][0]["state"]["authorised"], True)
        update = next(e for e in run["trace"] if e["type"] == "public_update")
        self.assertEqual(update["at_ms"], 4000)
        self.assertIn("A", run["rejected"])

    def test_update_same_time_precedes_response(self):
        run = run_case("resource", "immediate", (4000, 4000), (8000, 12000),
                       updates=((8000, {"authorised": False}),))
        events = [e for e in run["trace"] if e["at_ms"] == 8000]
        self.assertEqual(events[0]["type"], "public_update")
        self.assertEqual(run["completion_ms"], {})

    def test_gate_recheck_after_command_latency(self):
        run = run_case("resource", "immediate", (4000, 4000), (8000, 12000),
                       updates=((8050, {"authorised": False}),))
        first = next(e for e in run["trace"] if e["type"] == "rejected")
        self.assertEqual(first["reason"], "start_recheck")

    def test_future_task_not_visible(self):
        run = run_case("resource", "wait_released", (4000, 4000), (300, 700), releases=(0, 60000))
        self.assertEqual([t["task_id"] for t in run["requests"][0]["released_tasks"]], ["A"])
        self.assertEqual(run["completion_ms"]["A"], 4400)
        self.assertEqual(run["model_request_count"], 2)

    def test_acceleration_preserves_semantic_trace(self):
        for structure in ("dependency", "resource"):
            for policy in ("immediate", "wait_released"):
                for durations in ((4000, 4000), (3_600_000, 1_800_000)):
                    with self.subTest(structure=structure, policy=policy, durations=durations):
                        a = run_case(structure, policy, durations, (8000, 12000))
                        b = run_case(structure, policy, durations, (8000, 12000),
                                     clock_mode="continuous_reference")
                        for field in ("trace", "requests", "completion_ms", "on_time"):
                            self.assertEqual(a[field], b[field])

    def test_idle_jumps_have_no_requests_in_flight(self):
        run = run_case("dependency", "immediate", (3_600_000, 1_800_000), (8000, 12000))
        self.assertTrue(all(e["pending_requests"] == 0 for e in run["clock_log"]
                            if e["mode"] == "idle_jump"))
        self.assertEqual(run["maximum_logical_requests_in_flight"], 2)


if __name__ == "__main__":
    unittest.main()
