"""Offline reference for a hybrid clock; never calls a model or sleeps.

Scripted wall-time increments verify the protocol. They are not measured API
latencies. A live runner must supply monotonic-clock observations separately.
"""
from __future__ import annotations

import heapq
from copy import deepcopy


def milliseconds(value):
    if type(value) is not int or value < 0:
        raise ValueError("time must be a nonnegative integer in milliseconds")
    return value


class HybridClock:
    def __init__(self):
        self.now_ms = 0
        self.pending = {}
        self.log = []

    def begin(self, request_id):
        if request_id in self.pending:
            raise ValueError("duplicate pending request")
        self.pending[request_id] = self.now_ms

    def finish(self, request_id):
        start = self.pending.pop(request_id)
        return self.now_ms - start

    def advance_wall_ms(self, elapsed_ms):
        elapsed_ms = milliseconds(elapsed_ms)
        self.log.append({"mode": "wall_elapsed", "from_ms": self.now_ms,
                         "to_ms": self.now_ms + elapsed_ms,
                         "pending_requests": len(self.pending)})
        self.now_ms += elapsed_ms

    def fast_forward(self, target_ms):
        target_ms = milliseconds(target_ms)
        if target_ms < self.now_ms:
            raise ValueError("clock cannot go backwards")
        if self.pending:
            raise RuntimeError("cannot skip wall time with a model request in flight")
        self.log.append({"mode": "idle_jump", "from_ms": self.now_ms,
                         "to_ms": target_ms, "pending_requests": 0})
        self.now_ms = target_ms


def run_case(structure, policy, service_ms, latency_ms, *, releases=(0, 0),
             updates=(), clock_mode="hybrid", command_ms=100):
    """Two scripted agents, one abstract capacity slot; engineering fixture.

Dependency: A must have a successful completion receipt before B starts.
Resource: A and B share a non-preemptive slot. Policies see released tasks only.
No task is silently abandoned after its deadline; late service remains visible.
"""
    if structure not in {"dependency", "resource"}:
        raise ValueError("unknown structure")
    if policy not in {"immediate", "wait_released"}:
        raise ValueError("unknown policy")
    if clock_mode not in {"hybrid", "continuous_reference"}:
        raise ValueError("unknown clock mode")
    if len(service_ms) != 2 or len(latency_ms) != 2 or len(releases) != 2:
        raise ValueError("fixture requires two tasks")
    for value in (*service_ms, *latency_ms, *releases, command_ms):
        milliseconds(value)
    deadlines = {"A": 10_000_000, "B": 180_000 if structure == "resource" else 10_000_000}
    task_ids = ("A", "B")
    tasks = {key: {"task_id": key, "agent_id": "agent_" + key,
                   "release_ms": releases[i], "service_ms": service_ms[i],
                   "deadline_ms": deadlines[key]} for i, key in enumerate(task_ids)}
    private_latencies = dict(zip(task_ids, latency_ms))
    clock, queue, trace, calls = HybridClock(), [], [], []
    sequence = 0
    state = {"authorised": True, "version": 0}
    released, ready, completed, rejected = set(), set(), {}, set()
    busy = None
    maximum_pending = 0

    def push(at, phase, kind, payload):
        nonlocal sequence
        sequence += 1
        heapq.heappush(queue, (milliseconds(at), phase, sequence, kind, payload))

    def emit(kind, **fields):
        trace.append({"type": kind, "at_ms": clock.now_ms, **fields})

    def dispatch():
        nonlocal busy
        if busy is not None or not ready:
            return
        awaiting = {key for key in released if key not in ready
                    and key not in completed and key not in rejected}
        if policy == "wait_released" and awaiting:
            return
        eligible = [key for key in ready if structure != "dependency"
                    or key == "A" or "A" in completed]
        if not eligible:
            return
        if policy == "wait_released":
            eligible.sort(key=lambda key: (tasks[key]["deadline_ms"], key))
        else:
            eligible.sort(key=lambda key: (response_times[key], key))
        key = eligible[0]
        ready.remove(key)
        if not state["authorised"]:
            rejected.add(key)
            emit("rejected", task_id=key, reason="current_authorisation")
            dispatch()
            return
        busy = key
        push(clock.now_ms + command_ms, 4, "start", key)

    response_times = {}
    for task in tasks.values():
        push(task["release_ms"], 2, "release", task["task_id"])
    for at, patch in updates:
        push(at, 0, "update", deepcopy(patch))

    while queue:
        at, phase, seq, kind, payload = heapq.heappop(queue)
        if at < clock.now_ms:
            raise AssertionError("event order went backwards")
        if clock.pending or clock_mode == "continuous_reference":
            clock.advance_wall_ms(at - clock.now_ms)
        else:
            clock.fast_forward(at)
        if kind == "update":
            state.update(payload)
            state["version"] += 1
            emit("public_update", patch=payload, state_version=state["version"])
        elif kind == "release":
            key = payload
            released.add(key)
            request_id = "request_" + key
            request = {"request_id": request_id, "agent_id": tasks[key]["agent_id"],
                       "now_ms": clock.now_ms, "state": deepcopy(state),
                       "released_tasks": [deepcopy(tasks[t]) for t in sorted(released)]}
            calls.append(request)
            clock.begin(request_id)
            maximum_pending = max(maximum_pending, len(clock.pending))
            emit("request_started", task_id=key, request_id=request_id)
            push(clock.now_ms + private_latencies[key], 3, "response", key)
        elif kind == "response":
            key = payload
            duration = clock.finish("request_" + key)
            response_times[key] = clock.now_ms
            ready.add(key)
            emit("proposal_returned", task_id=key, scripted_wall_latency_ms=duration)
            dispatch()
        elif kind == "start":
            key = payload
            if not state["authorised"]:
                rejected.add(key)
                emit("rejected", task_id=key, reason="start_recheck")
                busy = None
                dispatch()
                continue
            if structure == "dependency" and key == "B" and "A" not in completed:
                raise AssertionError("dependency must use successful completion receipt")
            emit("service_started", task_id=key, duration_ms=tasks[key]["service_ms"])
            push(clock.now_ms + tasks[key]["service_ms"], 1, "complete", key)
        elif kind == "complete":
            key = payload
            completed[key] = clock.now_ms
            emit("service_completed", task_id=key)
            busy = None
            dispatch()
        else:
            raise AssertionError("unknown event")
    if clock.pending:
        raise AssertionError("all requests must have terminal responses")
    return {"structure": structure, "policy": policy, "clock_mode": clock_mode,
            "service_ms": list(service_ms), "scripted_latency_ms": list(latency_ms),
            "trace": trace, "requests": calls, "clock_log": clock.log,
            "completion_ms": completed, "rejected": sorted(rejected),
            "on_time": {key: key in completed and completed[key] <= deadlines[key]
                        for key in task_ids}, "model_request_count": len(calls),
            "maximum_logical_requests_in_flight": maximum_pending,
            "actual_api_requests": 0, "simulated_end_ms": clock.now_ms,
            "evidence_scope": "synthetic engineering verification; no live LLM or calibrated physics"}
