# Phase B审查代码摘录

2026-10-02读取；源文件与证据包manifest源码哈希一致。下列为原文摘录，行号为原源码一基行号，未修改源代码。

## E1：F1容量预约与实际启动安全门

源位置：`homecoord_bench/runtime/event_simulator.py:122`；摘录至第227行。

```text
122: def _candidate_start(episode: dict[str, Any], candidate: dict[str, Any],
123:                      reserved: list[dict[str, Any]], now_ms: int,
124:                      policy: str) -> tuple[int | None, str | None]:
125:     """Return the earliest online start allowed by the selected policy."""
126:     start = now_ms + int(episode.get("simulation", {}).get("command_latency_ms", DEVICE_DELAY_MS))
127:     start = max(start, candidate.get("scheduled_not_before_ms", start))
128:     reasons: list[str] = []
129:     max_iterations = 2 * (len(reserved) + 1)
130:     capacity = float(episode.get("home", {}).get("resources", {}).get("max_power_kw", float("inf")))
131: 
132:     for _ in range(max_iterations):
133:         changed = False
134:         proposed_interval = {**candidate, "timestamp_ms": start}
135: 
136:         if policy == "CentralSingleAgent":
137:             blockers = [item for item in reserved if _overlap(item, proposed_interval) > 0]
138:             if blockers:
139:                 start = max(item["timestamp_ms"] + item["duration_ms"] for item in blockers)
140:                 reasons.append("central_serialization")
141:                 changed = True
142: 
143:         elif policy == "RuleCoordinator":
144:             blockers = [item for item in reserved
145:                         if item["target"] == candidate["target"]
146:                         and _overlap(item, proposed_interval) > 0]
147:             if blockers:
148:                 start = max(item["timestamp_ms"] + item["duration_ms"] for item in blockers)
149:                 reasons.append("device_lock")
150:                 changed = True
151: 
152:         elif policy in {"ConstraintCoordinator", "DeadlineAwareCoordinator",
153:                         "CapacityAwareDeadlineCoordinator"}:
154:             c1 = [item for item in reserved
155:                   if _incompatible(item, candidate, episode)
156:                   and _overlap(item, proposed_interval) > 0]
157:             c2 = [item for item in reserved
158:                   if _indirect_conflict(item, proposed_interval, episode)]
159:             conflict_blockers = c1 + c2
160:             if conflict_blockers:
161:                 start = max(item["timestamp_ms"] + item["duration_ms"]
162:                             for item in conflict_blockers)
163:                 reasons.append("declared_action_conflict")
164:                 changed = True
165: 
166:             capacity_rule = next((rule for rule in episode.get("conflict_rules", [])
167:                                   if rule.get("type") == "C3"), None)
168:             if capacity_rule:
169:                 capacity = float(capacity_rule["capacity"])
170:             if candidate["power_kw"] > capacity:
171:                 # No amount of waiting can make this action feasible by itself.
172:                 return None, "resource_capacity_exceeded"
173:             for _ in range(max_iterations):
174:                 candidate_interval = {**candidate, "timestamp_ms": start}
175:                 boundaries = {start, start + candidate["duration_ms"]}
176:                 for item in reserved:
177:                     if item["timestamp_ms"] < start + candidate["duration_ms"] and start < item["timestamp_ms"] + item["duration_ms"]:
178:                         boundaries.add(max(start, item["timestamp_ms"]))
179:                         boundaries.add(min(start + candidate["duration_ms"], item["timestamp_ms"] + item["duration_ms"]))
180:                 shifted_to = None
181:                 ordered = sorted(boundaries)
182:                 for left, right in zip(ordered, ordered[1:]):
183:                     if right <= left:
184:                         continue
185:                     active = [item for item in reserved
186:                               if item["timestamp_ms"] < right
187:                               and item["timestamp_ms"] + item["duration_ms"] > left]
188:                     load = candidate["power_kw"] + sum(item["power_kw"] for item in active)
189:                     if load > capacity:
190:                         possible = [item["timestamp_ms"] + item["duration_ms"] for item in active]
191:                         if possible:
192:                             shifted_to = min(possible)
193:                             break
194:                         raise RuntimeError("capacity violation without an active reservation")
195:                 if shifted_to is None:
196:                     break
197:                 start = shifted_to
198:                 reasons.append("resource_capacity")
199:                 changed = True
200: 
201:         if not changed:
202:             return start, "+".join(dict.fromkeys(reasons)) or None
203: 
204:     raise RuntimeError("online scheduler failed to find a safe start")
205: 
206: 
207: def _shared_safety_gate_reason(
208:     episode: dict[str, Any], candidate: dict[str, Any],
209:     active: list[dict[str, Any]], now_ms: int,
210: ) -> str | None:
211:     """Veto an unsafe start; never plan, defer, or retry an action.
212: 
213:     This is a common physical safety floor for policy comparisons. It only
214:     inspects actions already in flight and episode-declared resource limits.
215:     """
216:     interval = {**candidate, "timestamp_ms": now_ms}
217:     for other in active:
218:         if _incompatible(other, interval, episode) or _indirect_conflict(other, interval, episode):
219:             return "shared_gate_action_conflict"
220:     capacity_rule = next((rule for rule in episode.get("conflict_rules", [])
221:                           if rule.get("type") == "C3"), None)
222:     capacity = float(capacity_rule["capacity"]) if capacity_rule else float(
223:         episode.get("home", {}).get("resources", {}).get("max_power_kw", float("inf"))
224:     )
225:     if candidate["power_kw"] + sum(item["power_kw"] for item in active) > capacity:
226:         return "shared_gate_capacity"
227:     return None
```

## E2：F1启动、真实完成、资源释放

源位置：`homecoord_bench/runtime/event_simulator.py:899`；摘录至第1070行。

```text
899:             continue
900: 
901:         if kind == "reserve_tick":
902:             events.append({"type": "reserve_tick", "timestamp_ms": now})
903:             try_dispatch_robust(now)
904:             continue
905: 
906:         if kind == "action_start":
907:             candidate, task, agent = payload["candidate"], payload["task"], payload["agent"]
908:             failing = [item for item in candidate["requires"] if not _condition_holds(state, item)]
909:             if batch_compute_ms is not None or compute_profile is not None:
910:                 events.append({"type": "action_precondition_recheck", "timestamp_ms": now,
911:                                "task_id": task["task_id"], "proposal_id": candidate["proposal_id"],
912:                                "state_version": state_version, "passed": not failing,
913:                                "scope": "preconditions_only; safety gate follows"})
914:             if failing:
915:                 rejected_item = {
916:                     "type": "action_rejected", "timestamp_ms": now,
917:                     "task_id": task["task_id"], "agent_id": task["agent_id"],
918:                     "proposal_id": candidate["proposal_id"],
919:                     "reason": "stale_state" if candidate["based_on_state_version"] < state_version else "unsafe_precondition",
920:                     "failed_requirements": deepcopy(failing),
921:                     "state_version": state_version,
922:                 }
923:                 events.append(rejected_item)
924:                 rejected.append(rejected_item)
925:                 reservations.remove(candidate)
926:                 continue
927: 
928:             if shared_safety_gate:
929:                 gate_reason = _shared_safety_gate_reason(
930:                     episode, candidate,
931:                     [item["candidate"] for item in in_flight_actions.values()], now,
932:                 )
933:                 if gate_reason:
934:                     event = {"type": "action_rejected", "timestamp_ms": now,
935:                              "task_id": task["task_id"], "agent_id": task["agent_id"],
936:                              "proposal_id": candidate["proposal_id"],
937:                              "reason": gate_reason, "state_version": state_version}
938:                     events.append(event)
939:                     rejected.append(event)
940:                     reservations.remove(candidate)
941:                     if policy == "GateRetryRule" and in_flight_actions:
942:                         pending_gate_retries[task["task_id"]] = payload
943:                         events.append({
944:                             "type": "retry_queued", "timestamp_ms": now,
945:                             "task_id": task["task_id"], "reason": gate_reason,
946:                         })
947:                     continue
948: 
949:             projected = deepcopy(state)
950:             _apply_patch(projected, candidate.get("start_effects", {}))
951:             if (shared_safety_gate or policy != "IndependentMultiAgent") and not constraints_hold(projected, episode.get("constraints", [])):
952:                 event = {"type": "action_rejected", "timestamp_ms": now,
953:                          "task_id": task["task_id"], "agent_id": task["agent_id"],
954:                          "proposal_id": candidate["proposal_id"],
955:                          "reason": "constraint_violation", "state_version": state_version}
956:                 events.append(event)
957:                 rejected.append(event)
958:                 reservations.remove(candidate)
959:                 continue
960: 
961:             # The older closed-loop runner applies final effects at action
962:             # start. In this event simulator they happen at completion, so a
963:             # coordinated policy must also inspect the projected completion
964:             # state before allowing an irreversible physical action to start.
965:             # Exogenous changes during execution can still invalidate this
966:             # projection; that residual risk is recorded at completion below.
967:             if shared_safety_gate or policy != "IndependentMultiAgent":
968:                 projected_completion = _projected_action_state(state, candidate)
969:                 if not constraints_hold(projected_completion, episode.get("constraints", [])):
970:                     event = {
971:                         "type": "action_rejected", "timestamp_ms": now,
972:                         "task_id": task["task_id"], "agent_id": task["agent_id"],
973:                         "proposal_id": candidate["proposal_id"],
974:                         "reason": "predicted_completion_constraint_violation",
975:                         "predicted_completion_at_ms": now + candidate["duration_ms"],
976:                         "state_version": state_version,
977:                     }
978:                     events.append(event)
979:                     rejected.append(event)
980:                     reservations.remove(candidate)
981:                     continue
982: 
983:             state_before_start = deepcopy(state)
984:             before_start_distance = goal_distance(state, episode.get("goals", []))
985:             _apply_patch(state, candidate.get("start_effects", {}))
986:             after_start_distance = goal_distance(state, episode.get("goals", []))
987:             if (first_effective_action_latency_ms is None
988:                     and after_start_distance < before_start_distance
989:                     and constraints_hold(state, constraints)):
990:                 first_effective_action_latency_ms = now - int(episode.get("episode_release_at_ms", 0))
991:             if candidate.get("start_effects"):
992:                 state_version += 1
993:                 state_event = {"type": "state_update", "timestamp_ms": now,
994:                                "new_state_version": state_version,
995:                                "patch": deepcopy(candidate["start_effects"]),
996:                                "source": "action_started", "task_id": task["task_id"]}
997:                 observe_constraint_state(state_event, now)
998:                 record_in_flight_precondition_invalidations(
999:                     state_before_start, now, "action_started", "action_started",
1000:                     task["task_id"], task["agent_id"],
1001:                 )
1002:                 events.append(state_event)
1003:             started = {
1004:                 "type": "action_started", "timestamp_ms": now,
1005:                 "agent_id": task["agent_id"], "task_id": task["task_id"],
1006:                 "proposal_id": candidate["proposal_id"],
1007:                 "target": candidate["target"], "operation": candidate["operation"],
1008:                 "duration_ms": candidate["duration_ms"], "power_kw": candidate["power_kw"],
1009:                 "based_on_state_version": candidate["based_on_state_version"],
1010:                 "requires": deepcopy(candidate["requires"]),
1011:                 "start_effects": deepcopy(candidate.get("start_effects", {})),
1012:                 "completion_effects": deepcopy(candidate.get("effects", {})),
1013:                 "state_version_at_start": state_version,
1014:             }
1015:             if first_action_start_latency_ms is None:
1016:                 first_action_start_latency_ms = now - int(episode.get("episode_release_at_ms", 0))
1017:             events.append(started)
1018:             in_flight_actions[candidate["proposal_id"]] = {
1019:                 "task_id": task["task_id"],
1020:                 "agent_id": task["agent_id"],
1021:                 "requires": deepcopy(candidate["requires"]),
1022:                 "candidate": candidate,
1023:             }
1024:             push(now + candidate["duration_ms"], _PRIORITY_STATE_OR_COMPLETION, "action_completion", {
1025:                 "candidate": candidate, "task": task, "agent": agent, "started_event": started,
1026:             })
1027:             continue
1028: 
1029:         if kind == "action_completion":
1030:             candidate, task = payload["candidate"], payload["task"]
1031:             state_before_completion = deepcopy(state)
1032:             before_distance = goal_distance(state, episode.get("goals", []))
1033:             _apply_patch(state, candidate.get("effects", {}))
1034:             state_version += 1
1035:             completion = {
1036:                 "type": "action_completed", "timestamp_ms": now,
1037:                 "agent_id": task["agent_id"], "task_id": task["task_id"],
1038:                 "proposal_id": candidate["proposal_id"],
1039:                 "target": candidate["target"], "operation": candidate["operation"],
1040:                 "effects": deepcopy(candidate.get("effects", {})),
1041:                 "new_state_version": state_version,
1042:             }
1043:             after_distance = goal_distance(state, episode.get("goals", []))
1044:             if (first_effective_action_latency_ms is None
1045:                     and after_distance < before_distance
1046:                     and constraints_hold(state, constraints)):
1047:                 first_effective_action_latency_ms = now - int(episode.get("episode_release_at_ms", 0))
1048:             observe_constraint_state(completion, now)
1049:             events.append(completion)
1050:             if completion.get("constraint_violation_started"):
1051:                 completion["constraint_violation"] = True
1052:                 if in_flight_actions:
1053:                     unsafe_state_onsets_during_action.append({
1054:                         "timestamp_ms": now,
1055:                         "trigger_event": "action_completed",
1056:                         "active_task_ids": sorted({
1057:                             action["task_id"] for action in in_flight_actions.values()
1058:                         }),
1059:                     })
1060:             in_flight_actions.pop(candidate["proposal_id"], None)
1061:             completed_task_ids.add(task["task_id"])
1062:             if candidate.get("effects"):
1063:                 record_in_flight_precondition_invalidations(
1064:                     state_before_completion, now, "action_completed", "action_completed",
1065:                     task["task_id"], task["agent_id"],
1066:                 )
1067:             reservations.remove(candidate)
1068:             schedule_gate_retries(now)
1069:             try_dispatch_robust(now)
1070:             continue
```

## E3：F1旧评分投影与真实逐任务指标汇总

源位置：`homecoord_bench/runtime/event_simulator.py:230`；摘录至第263行。

```text
230: def _legacy_evaluation_trace(episode: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
231:     projected = []
232:     for event in events:
233:         if event["type"] == "state_update":
234:             # The following action_started record is projected as the single
235:             # state-changing action_effective event. Keeping this synthetic
236:             # state_update as well would apply start_effects twice and could
237:             # make an action appear stale against its own start transition.
238:             if event.get("source") == "action_started":
239:                 continue
240:             projected.append({
241:                 "type": "state_update", "timestamp_ms": event["timestamp_ms"],
242:                 "new_state_version": event["new_state_version"],
243:                 "patch": deepcopy(event.get("patch", {})),
244:             })
245:         elif event["type"] == "action_started":
246:             projected.append({
247:                 "type": "action_effective", "timestamp_ms": event["timestamp_ms"],
248:                 "agent_id": event["agent_id"], "task_id": event["task_id"],
249:                 "proposal_id": event["proposal_id"], "target": event["target"],
250:                 "operation": event["operation"], "duration_ms": event["duration_ms"],
251:                 "power_kw": event["power_kw"],
252:                 "based_on_state_version": event["based_on_state_version"],
253:                 "requires": deepcopy(event["requires"]),
254:                 "effects": deepcopy(event.get("start_effects", {})),
255:             })
256:         elif event["type"] == "action_completed":
257:             projected.append({
258:                 "type": "state_update", "timestamp_ms": event["timestamp_ms"],
259:                 "new_state_version": event["new_state_version"],
260:                 "patch": deepcopy(event.get("effects", {})),
261:             })
262:     return {"trace_id": "event_simulator.projected", "episode_id": episode["episode_id"],
263:             "events": projected}
```

## E4：F1最终评分汇总

源位置：`homecoord_bench/runtime/event_simulator.py:1089`；摘录至第1151行。

```text
1089:     projected_trace = _legacy_evaluation_trace(episode, ordered_events)
1090:     result = evaluate(episode, projected_trace)
1091:     completion_violations = sum(bool(event.get("constraint_violation"))
1092:                                 for event in ordered_events if event["type"] == "action_completed")
1093:     if constraint_violation_active and constraint_violation_started_ms is not None:
1094:         constraint_violation_duration_ms += max(0, current_time - constraint_violation_started_ms)
1095:     rejected_preconditions = sum(event.get("reason") in {"stale_state", "unsafe_precondition"}
1096:                                  for event in rejected)
1097:     result.update({
1098:         "policy": policy,
1099:         "proposal_architecture": getattr(decision_provider, "proposal_architecture", policy),
1100:         "proposal_count": sum(event["type"] == "proposal_returned" for event in ordered_events),
1101:         "accepted_action_count": sum(event["type"] == "action_started" for event in ordered_events),
1102:         "rejected_action_count": len(rejected),
1103:         "completion_constraint_violation_count": completion_violations,
1104:         "state_constraint_violation_episode_count": constraint_violation_episode_count,
1105:         "state_constraint_violation_duration_ms": constraint_violation_duration_ms,
1106:         "precondition_violations_at_start": rejected_preconditions,
1107:         "stale_at_action_start_count": sum(
1108:             event.get("reason") == "stale_state" for event in rejected
1109:         ),
1110:         "unsafe_precondition_rejection_count": sum(
1111:             event.get("reason") == "unsafe_precondition" for event in rejected
1112:         ),
1113:         "in_flight_precondition_invalidated_action_count": len(
1114:             in_flight_precondition_invalidations
1115:         ),
1116:         "in_flight_precondition_invalidations": in_flight_precondition_invalidations,
1117:         "in_flight_precondition_invalidation_source_counts": {
1118:             kind: sum(item["trigger_kind"] == kind
1119:                       for item in in_flight_precondition_invalidations)
1120:             for kind in ("exogenous_update", "action_started", "action_completed")
1121:         },
1122:         "cross_agent_in_flight_precondition_invalidated_action_count": sum(
1123:             item["cross_agent"] for item in in_flight_precondition_invalidations
1124:         ),
1125:         "unsafe_state_onset_during_action_count": len(unsafe_state_onsets_during_action),
1126:         "unsafe_state_onsets_during_action": unsafe_state_onsets_during_action,
1127:         "process_valid_success": (result["process_valid_success"]
1128:                                   and completion_violations == 0
1129:                                   and constraint_violation_episode_count == 0),
1130:         "model_latency_by_task_ms": model_latencies,
1131:         "coordination_delay_ms": effective_coordination_delay_ms,
1132:         "coordination_compute_measurements": compute_measurements,
1133:         "coordination_compute_profile": deepcopy(compute_profile),
1134:         "shared_safety_gate": shared_safety_gate,
1135:         "shared_safety_gate_rejection_count": sum(
1136:             event.get("reason", "").startswith("shared_gate_") for event in rejected
1137:         ),
1138:         "retry_queued_count": sum(event["type"] == "retry_queued" for event in ordered_events),
1139:         "retry_scheduled_count": sum(event["type"] == "retry_scheduled" for event in ordered_events),
1140:         "task_action_finish_time_ms": result["task_action_finish_time_ms"],
1141:         "first_action_start_latency_ms": first_action_start_latency_ms,
1142:         "first_goal_progress_latency_ms": first_effective_action_latency_ms,
1143:         # Keep the historical key for existing analysis code. In this event
1144:         # simulator it means goal progress, not the time at which a device starts.
1145:         "first_effective_action_latency_ms": first_effective_action_latency_ms,
1146:         "physical_completion_semantics": "final effects apply on action_completed",
1147:         "api_calls_concurrent": False,
1148:     })
1149:     trace["event_count"] = len(ordered_events)
1150:     result.update(task_response_metrics(episode, ordered_events))
1151:     return trace, result
```

## D1：真实完成回执集合与依赖唤醒

源位置：`homecoord_bench/task_revision/event_simulator_v3.py:412`；摘录至第441行。

```text
412:     dependency_receipts: set[str] = set()
413:     dependency_pending: dict[str, dict[str, Any]] = {}
414:     dependency_blocked: set[str] = set()
415:     dependency_ready_at: dict[str, int] = {}
416: 
417:     def dependencies_met(tid: str) -> bool:
418:         return all(dep in dependency_receipts and dep not in withdrawn_tasks
419:                    for dep in dependencies.get(tid, []))
420: 
421:     def wake_dependencies(at_ms: int) -> None:
422:         changed = True
423:         while changed:
424:             changed = False
425:             for tid, response in list(dependency_pending.items()):
426:                 failed = [d for d in dependencies[tid] if d in withdrawn_tasks or d in dependency_blocked]
427:                 if failed or tid in withdrawn_tasks:
428:                     dependency_pending.pop(tid)
429:                     dependency_blocked.add(tid)
430:                     events.append({"type": "dependency_blocked", "timestamp_ms": at_ms,
431:                                    "task_id": tid, "reason": "predecessor_or_request_withdrawn",
432:                                    "blocked_by": failed})
433:                     changed = True
434:                 elif dependencies_met(tid):
435:                     dependency_pending.pop(tid)
436:                     dependency_ready_at.setdefault(tid, at_ms)
437:                     events.append({"type": "dependency_ready", "timestamp_ms": at_ms,
438:                                    "task_id": tid, "predecessors": list(dependencies[tid])})
439:                     response = {**response, "proposal_ready_at_ms": at_ms}
440:                     dispatch_proposal(response, at_ms)
441:                     changed = True
```

## D2：提案授权、依赖等待和成本grounding

源位置：`homecoord_bench/task_revision/event_simulator_v3.py:569`；摘录至第619行。

```text
569:     def dispatch_proposal_body(response: dict[str, Any], at_ms: int) -> None:
570:         """Validate, coordinate, and schedule a returned physical action."""
571:         task = response["task"]
572:         specialist = response["specialist"]
573:         agent = response["agent"]
574:         action = response["decision"]["actions"][0]
575:         authorization_error = validate_tool_call(
576:             episode, specialist["agent_id"], task["task_id"], action
577:         )
578:         if authorization_error:
579:             rejected_item = {
580:                 "type": "action_rejected", "timestamp_ms": at_ms,
581:                 "task_id": task["task_id"], "agent_id": specialist["agent_id"],
582:                 "proposal_id": action["proposal_id"], "reason": authorization_error,
583:             }
584:             events.append(rejected_item)
585:             rejected.append(rejected_item)
586:             return
587:         if task["task_id"] in withdrawn_tasks:
588:             rejected_item = {"type": "action_rejected", "timestamp_ms": at_ms,
589:                              "task_id": task["task_id"], "proposal_id": action["proposal_id"],
590:                              "reason": "request_withdrawn"}
591:             events.append(rejected_item)
592:             rejected.append(rejected_item)
593:             return
594:         if task["task_id"] in lifecycle:
595:             lifecycle_responses[task["task_id"]] = deepcopy(response)
596:         tid = task["task_id"]
597:         if tid in dependencies:
598:             failed = [d for d in dependencies[tid] if d in withdrawn_tasks or d in dependency_blocked]
599:             if failed:
600:                 dependency_blocked.add(tid)
601:                 events.append({"type": "dependency_blocked", "timestamp_ms": at_ms,
602:                                "task_id": tid, "reason": "predecessor_withdrawn", "blocked_by": failed})
603:                 return
604:             if not dependencies_met(tid):
605:                 dependency_pending[tid] = deepcopy(response)
606:                 events.append({"type": "dependency_waiting", "timestamp_ms": at_ms,
607:                                "task_id": tid, "predecessors": list(dependencies[tid])})
608:                 return
609:             dependency_ready_at.setdefault(tid, at_ms)
610:         candidate = materialize_action(
611:             episode, specialist["agent_id"], task["task_id"], action,
612:             at_ms + int(episode.get("simulation", {}).get("command_latency_ms", DEVICE_DELAY_MS)),
613:         )
614:         grounding = next((item for item in episode.get("action_grounding", [])
615:                           if item.get("agent_id") == specialist["agent_id"]
616:                           and item.get("task_id") == task["task_id"]
617:                           and item.get("operation", "*") in {"*", action.get("operation")}), {})
618:         candidate["start_effects"] = deepcopy(grounding.get("start_effects", {}))
619:         candidate["effects"] = deepcopy(grounding.get("completion_effects", candidate.get("effects", {})))
```

## D3：依赖动作启动前复查与容量安全门

源位置：`homecoord_bench/task_revision/event_simulator_v3.py:1067`；摘录至第1130行。

```text
1067:         if kind == "action_start":
1068:             candidate, task, agent = payload["candidate"], payload["task"], payload["agent"]
1069:             if task["task_id"] in dependencies and not dependencies_met(task["task_id"]):
1070:                 event = {"type": "action_rejected", "timestamp_ms": now,
1071:                          "task_id": task["task_id"], "proposal_id": candidate["proposal_id"],
1072:                          "reason": "dependency_not_satisfied_at_start"}
1073:                 events.append(event)
1074:                 rejected.append(event)
1075:                 reservations.remove(candidate)
1076:                 continue
1077:             if task["task_id"] in withdrawn_tasks:
1078:                 event = {"type": "action_rejected", "timestamp_ms": now,
1079:                          "task_id": task["task_id"], "proposal_id": candidate["proposal_id"],
1080:                          "reason": "request_withdrawn"}
1081:                 events.append(event)
1082:                 rejected.append(event)
1083:                 reservations.remove(candidate)
1084:                 continue
1085:             failing = [item for item in candidate["requires"] if not _condition_holds(state, item)]
1086:             if batch_compute_ms is not None or compute_profile is not None:
1087:                 events.append({"type": "action_precondition_recheck", "timestamp_ms": now,
1088:                                "task_id": task["task_id"], "proposal_id": candidate["proposal_id"],
1089:                                "state_version": state_version, "passed": not failing,
1090:                                "scope": "preconditions_only; safety gate follows"})
1091:             if failing:
1092:                 rejected_item = {
1093:                     "type": "action_rejected", "timestamp_ms": now,
1094:                     "task_id": task["task_id"], "agent_id": task["agent_id"],
1095:                     "proposal_id": candidate["proposal_id"],
1096:                     "reason": "stale_state" if candidate["based_on_state_version"] < state_version else "unsafe_precondition",
1097:                     "failed_requirements": deepcopy(failing),
1098:                     "state_version": state_version,
1099:                 }
1100:                 events.append(rejected_item)
1101:                 rejected.append(rejected_item)
1102:                 reservations.remove(candidate)
1103:                 if task["task_id"] in lifecycle:
1104:                     if lifecycle[task["task_id"]]["mode"] == "restart_from_zero":
1105:                         lifecycle_waiting.add(task["task_id"])
1106:                     react_lifecycle(now)
1107:                 continue
1108: 
1109:             if shared_safety_gate:
1110:                 gate_reason = _shared_safety_gate_reason(
1111:                     episode, candidate,
1112:                     [item["candidate"] for item in in_flight_actions.values()], now,
1113:                 )
1114:                 if gate_reason:
1115:                     event = {"type": "action_rejected", "timestamp_ms": now,
1116:                              "task_id": task["task_id"], "agent_id": task["agent_id"],
1117:                              "proposal_id": candidate["proposal_id"],
1118:                              "reason": gate_reason, "state_version": state_version}
1119:                     events.append(event)
1120:                     rejected.append(event)
1121:                     reservations.remove(candidate)
1122:                     if policy == "GateRetryRule" and in_flight_actions:
1123:                         pending_gate_retries[task["task_id"]] = payload
1124:                         events.append({
1125:                             "type": "retry_queued", "timestamp_ms": now,
1126:                             "task_id": task["task_id"], "reason": gate_reason,
1127:                         })
1128:                     elif task["task_id"] in lifecycle and lifecycle[task["task_id"]]["mode"] == "restart_from_zero":
1129:                         lifecycle_waiting.add(task["task_id"])
1130:                     continue
```

## D4：依赖真实完成并登记回执

源位置：`homecoord_bench/task_revision/event_simulator_v3.py:1213`；摘录至第1261行。

```text
1213:         if kind == "action_completion":
1214:             candidate, task = payload["candidate"], payload["task"]
1215:             if candidate["proposal_id"] in cancelled_proposals:
1216:                 events.append({"type": "completion_discarded", "timestamp_ms": now,
1217:                                "task_id": task["task_id"], "proposal_id": candidate["proposal_id"]})
1218:                 continue
1219:             state_before_completion = deepcopy(state)
1220:             before_distance = goal_distance(state, episode.get("goals", []))
1221:             _apply_patch(state, candidate.get("effects", {}))
1222:             state_version += 1
1223:             completion = {
1224:                 "type": "action_completed", "timestamp_ms": now,
1225:                 "agent_id": task["agent_id"], "task_id": task["task_id"],
1226:                 "proposal_id": candidate["proposal_id"],
1227:                 "target": candidate["target"], "operation": candidate["operation"],
1228:                 "effects": deepcopy(candidate.get("effects", {})),
1229:                 "new_state_version": state_version,
1230:             }
1231:             after_distance = goal_distance(state, episode.get("goals", []))
1232:             if (first_effective_action_latency_ms is None
1233:                     and after_distance < before_distance
1234:                     and constraints_hold(state, constraints)):
1235:                 first_effective_action_latency_ms = now - int(episode.get("episode_release_at_ms", 0))
1236:             observe_constraint_state(completion, now)
1237:             events.append(completion)
1238:             if completion.get("constraint_violation_started"):
1239:                 completion["constraint_violation"] = True
1240:                 if in_flight_actions:
1241:                     unsafe_state_onsets_during_action.append({
1242:                         "timestamp_ms": now,
1243:                         "trigger_event": "action_completed",
1244:                         "active_task_ids": sorted({
1245:                             action["task_id"] for action in in_flight_actions.values()
1246:                         }),
1247:                     })
1248:             in_flight_actions.pop(candidate["proposal_id"], None)
1249:             completed_task_ids.add(task["task_id"])
1250:             if task_accepts_action(completion, task) and task["task_id"] not in withdrawn_tasks:
1251:                 dependency_receipts.add(task["task_id"])
1252:             if candidate.get("effects"):
1253:                 record_in_flight_precondition_invalidations(
1254:                     state_before_completion, now, "action_completed", "action_completed",
1255:                     task["task_id"], task["agent_id"],
1256:                 )
1257:             reservations.remove(candidate)
1258:             schedule_gate_retries(now)
1259:             try_dispatch_robust(now)
1260:             react_lifecycle(now)
1261:             continue
```

## D5：依赖服务、完成和期限以真实事件覆写

源位置：`homecoord_bench/task_revision/event_simulator_v3.py:1345`；摘录至第1372行。

```text
1345:     trace["event_count"] = len(ordered_events)
1346:     result.update(task_response_metrics(episode, ordered_events))
1347:     if lifecycle or dependencies:
1348:         result["lifecycle_version"] = "v2-local-interlock"
1349:         result["task_service"] = deepcopy(result["task_correct_action_completed"])
1350:         result["served_task_count"] = sum(result["task_service"].values())
1351:         result["task_service_rate"] = result["served_task_count"] / len(result["task_service"]) if result["task_service"] else None
1352:         result["task_action_finish_time_ms"] = {
1353:             tid: tasks_by_id[tid]["release_at_ms"] + latency - episode["episode_release_at_ms"] if latency is not None else None
1354:             for tid, latency in result["task_completion_latency_ms"].items()}
1355:         result["task_deadline_met"] = {
1356:             t["task_id"]: result["task_completion_tardiness_ms"][t["task_id"]] == 0
1357:             for t in episode["task_stream"] if t.get("completion_deadline_ms") is not None}
1358:         result["all_deadlines_met"] = all(result["task_deadline_met"].values()) if result["task_deadline_met"] else None
1359:         result["timely_process_valid_success"] = result["process_valid_success"] and result["all_deadlines_met"] is True
1360:         result["withdrawn_task_ids"] = sorted(withdrawn_tasks)
1361:         result["waiting_recovery_task_ids"] = sorted(lifecycle_waiting | lifecycle_restart_queued)
1362:         result["stop_requested_count"] = sum(e["type"] == "stop_requested" for e in ordered_events)
1363:         result["stop_confirmed_count"] = len(stopped_at)
1364:         result["stop_ack_too_late_count"] = sum(e["type"] == "stop_ack_too_late" for e in ordered_events)
1365:         result["restart_count"] = sum(e["type"] == "restart_proposed" for e in ordered_events)
1366:         result["active_reservations_at_end"] = len(reservations)
1367:     if dependencies:
1368:         result["dependency_version"] = "v3-actual-completion-dag"
1369:         result["dependency_completed_receipts"] = sorted(dependency_receipts)
1370:         result["dependency_waiting_task_ids"] = sorted(dependency_pending)
1371:         result["dependency_blocked_task_ids"] = sorted(dependency_blocked)
1372:         result["dependency_dispatch_ready_at_ms"] = dependency_ready_at
```

## D6：晚发布任务的请求与返回时钟

源位置：`homecoord_bench/task_revision/event_simulator_v3.py:948`；摘录至第989行。

```text
948:         if kind == "task_release":
949:             task = payload["task"]
950:             released_task_ids.add(task["task_id"])
951:             react_lifecycle(now)
952:             prepare_batch = getattr(decision_provider, "prepare_release_batch", None)
953:             if prepare_batch is not None:
954:                 prepare_batch(episode, now, _state_snapshot(state), state_version, instructions)
955:             specialist = agents[task["agent_id"]]
956:             agent = central_agent if policy == "CentralSingleAgent" else specialist
957:             request = build_agent_request(
958:                 episode, agent, task, architecture=policy,
959:                 current_time_ms=now, current_state=_state_snapshot(state),
960:                 state_version=state_version,
961:                 include_evaluation_hints=getattr(decision_provider, "include_evaluation_hints", False),
962:                 request_id=(
963:                     f"{episode.get('base_episode_id', episode['episode_id'])}:{policy}:{task['task_id']}"
964:                     if episode.get("simulation", {}).get("blind_future_task_arrivals", False)
965:                     else f"{episode['episode_id']}:{policy}:{task['task_id']}"
966:                 ),
967:                 released_task_ids=released_task_ids,
968:             )
969:             agent_requests.append(deepcopy(request))
970:             decision = decision_provider.decide(request, instructions)
971:             assert_agent_decision(decision)
972:             measured = max(1, int(round(getattr(decision_provider, "last_latency_ms", 1))))
973:             latency = (_synthetic_latency_ms(
974:                 episode.get("base_episode_id", episode["episode_id"]), agent["agent_id"], policy,
975:                 task.get("agent_id"),
976:             ) if synthetic_latency else measured)
977:             decisions[task["task_id"]] = deepcopy(decision)
978:             model_latencies[task["task_id"]] = latency
979:             push(now + latency, _PRIORITY_PROPOSAL_RESPONSE, "proposal_response", {
980:                 "task": task, "specialist": specialist, "agent": agent,
981:                 "decision": decision, "state_version_at_release": state_version,
982:                 "request_id": request["request_id"], "latency_ms": latency,
983:             })
984:             events.append({
985:                 "type": "task_released", "timestamp_ms": now,
986:                 "task_id": task["task_id"], "agent_id": task["agent_id"],
987:                 "state_version": state_version, "request_id": request["request_id"],
988:             })
989:             try_dispatch_robust(now)
```

## M1：逐任务等待、完成、迟到和null

源位置：`homecoord_bench/runtime/task_response_metrics.py:1`；摘录至第34行。

```text
1: """Per-task actual response metrics, relative to each request's own release."""
2: from evaluate import task_action_specs, task_accepts_action
3: 
4: 
5: def task_response_metrics(episode, events):
6:     tasks = [t for t in episode["task_stream"] if task_action_specs(t)]
7:     started, completed, waits, latencies, tardiness = {}, {}, {}, {}, {}
8:     for task in tasks:
9:         task_id, release = task["task_id"], task["release_at_ms"]
10:         starts = [e for e in events if e["type"] == "action_started"
11:                   and e.get("task_id") == task_id and task_accepts_action(e, task)]
12:         if any(e["timestamp_ms"] < release for e in starts):
13:             raise ValueError("correct action starts before its task release")
14:         finishes = [e for e in events if e["type"] == "action_completed"
15:                     and e.get("task_id") == task_id
16:                     and any(s["proposal_id"] == e.get("proposal_id") and s["timestamp_ms"] <= e["timestamp_ms"] for s in starts)]
17:         first_start = min((e["timestamp_ms"] for e in starts), default=None)
18:         first_finish = min((e["timestamp_ms"] for e in finishes), default=None)
19:         started[task_id], completed[task_id] = first_start is not None, first_finish is not None
20:         waits[task_id] = first_start - release if first_start is not None else None
21:         latencies[task_id] = first_finish - release if first_finish is not None else None
22:         deadline = task.get("completion_deadline_ms")
23:         tardiness[task_id] = max(0, first_finish - deadline) if first_finish is not None and deadline is not None else None
24:     finite_waits = [v for v in waits.values() if v is not None]
25:     return {
26:         "task_response_metric_version": "own-release-0.1",
27:         "task_correct_action_started": started, "task_correct_action_completed": completed,
28:         "task_start_wait_ms": waits, "task_completion_latency_ms": latencies,
29:         "task_completion_tardiness_ms": tardiness,
30:         "task_unstarted_count": sum(not v for v in started.values()),
31:         "task_incomplete_count": sum(not v for v in completed.values()),
32:         "max_observed_task_start_wait_ms": max(finite_waits, default=None),
33:         "task_start_within_1s": {t: w is not None and w <= 1000 for t, w in waits.items()},
34:     }
```

## M2：服务动作匹配和合法off排除

源位置：`homecoord_bench/evaluate.py:86`；摘录至第104行。

```text
86: def action_matches(event: dict[str, Any], spec: dict[str, Any]) -> bool:
87:     return all(event.get(key) == value for key, value in spec.items())
88: 
89: 
90: def task_action_specs(task: dict[str, Any]) -> list[dict[str, Any]]:
91:     """Explicit alternative service actions; preserve legacy single-action scoring."""
92:     if "acceptable_actions" in task:
93:         specs = task["acceptable_actions"]
94:         if not isinstance(specs, list) or not specs or any(
95:             not isinstance(s, dict) or not all(isinstance(s.get(k), str) and s[k] for k in ("target", "operation"))
96:             for s in specs
97:         ):
98:             raise ValueError("acceptable_actions must explicitly name target and operation")
99:         return specs
100:     return [task["required_action"]] if task.get("required_action") else []
101: 
102: 
103: def task_accepts_action(event: dict[str, Any], task: dict[str, Any]) -> bool:
104:     return any(action_matches(event, spec) for spec in task_action_specs(task))
```

## M3：通用容量、服务、截止和成功字段

源位置：`homecoord_bench/evaluate.py:208`；摘录至第280行。

```text
208:         elif category == "C3":
209:             points = sorted({point for event in actions for point in interval(event)})
210:             capacity = rule["capacity"]
211:             for start, end in zip(points, points[1:]):
212:                 if end <= start:
213:                     continue
214:                 power = sum(
215:                     event.get("power_kw", 0)
216:                     for event in actions
217:                     if interval(event)[0] < end and interval(event)[1] > start
218:                 )
219:                 if power > capacity:
220:                     counts["C3"] += 1
221:                     break
222: 
223:     final_success = goals_satisfied(state, goals)
224:     process_valid = final_success and violations == 0 and precondition_violations == 0 and sum(counts.values()) == 0
225:     serviceable_tasks = [task for task in episode["task_stream"] if task_action_specs(task)]
226:     task_service = {
227:         task["task_id"]: any(
228:             (
229:                 event.get("task_id") == task["task_id"]
230:                 or (event.get("task_id") is None and event.get("agent_id") == task["agent_id"])
231:             )
232:             and task_accepts_action(event, task)
233:             for event in actions
234:         )
235:         for task in serviceable_tasks
236:     }
237:     task_action_finish_time_ms = {
238:         task["task_id"]: min(
239:             (
240:                 event["timestamp_ms"] + event.get("duration_ms", 0) - release
241:                 for event in actions
242:                 if (
243:                     event.get("task_id") == task["task_id"]
244:                     or (event.get("task_id") is None and event.get("agent_id") == task["agent_id"])
245:                 ) and task_accepts_action(event, task)
246:             ),
247:             default=None,
248:         )
249:         for task in serviceable_tasks
250:     }
251:     task_deadline_met = {
252:         task["task_id"]: (
253:             task_action_finish_time_ms[task["task_id"]] is not None
254:             and task_action_finish_time_ms[task["task_id"]]
255:             <= task["completion_deadline_ms"] - release
256:         )
257:         for task in serviceable_tasks if task.get("completion_deadline_ms") is not None
258:     }
259:     all_deadlines_met = all(task_deadline_met.values())
260:     served_task_count = sum(task_service.values())
261:     return {
262:         "episode_id": episode["episode_id"],
263:         "trace_id": trace["trace_id"],
264:         "final_goal_success": final_success,
265:         "process_valid_success": process_valid,
266:         "constraint_violation_count": violations,
267:         "precondition_violation_count": precondition_violations,
268:         "conflict_counts": counts,
269:         "stale_action_count": stale_actions,
270:         "first_effective_action_latency_ms": None if first_effective is None else first_effective - release,
271:         "task_completion_time_ms": None if completion is None else completion - release,
272:         "task_action_finish_time_ms": task_action_finish_time_ms,
273:         "task_deadline_met": task_deadline_met,
274:         "all_deadlines_met": all_deadlines_met if task_deadline_met else None,
275:         "timely_process_valid_success": process_valid and all_deadlines_met,
276:         "coordination_decision_latency_ms": None if first_coordination is None else first_coordination - release,
277:         "task_service": task_service,
278:         "served_task_count": served_task_count,
279:         "serviceable_task_count": len(serviceable_tasks),
280:         "task_service_rate": served_task_count / len(serviceable_tasks) if serviceable_tasks else None,
```

## G1：实际持续时间和资源来自冻结grounding

源位置：`homecoord_bench/runtime/execution.py:43`；摘录至第77行。

```text
43: def materialize_action(
44:     episode_or_id: dict[str, Any] | str,
45:     agent_id: str,
46:     task_id: str,
47:     action: dict[str, Any],
48:     effective_at_ms: int,
49: ) -> dict[str, Any]:
50:     """Ground a proposal from episode data, retaining fallback for old records."""
51:     episode = episode_or_id if isinstance(episode_or_id, dict) else None
52:     episode_id = episode.get("base_episode_id", episode["episode_id"]) if episode else episode_or_id
53:     target = _target_name(action["target"])
54:     parameters = _decode_parameters(action)
55:     duration = action.get("estimated_duration_ms")
56:     power = action.get("estimated_power_kw")
57:     effects: dict[str, Any]
58:     operation: str
59: 
60:     grounding = None
61:     if episode:
62:         records = episode.get("action_grounding", [])
63:         grounding = next(
64:             (
65:                 item for item in records
66:                 if item.get("agent_id") == agent_id
67:                 and item.get("task_id") == task_id
68:                 and item.get("operation", "*") in {"*", action.get("operation")}
69:             ),
70:             None,
71:         )
72:     if grounding:
73:         target = _target_name(grounding.get("target", action["target"]))
74:         operation = grounding.get("grounded_operation", action["operation"])
75:         effects = deepcopy(grounding.get("effects", {}))
76:         actual_duration = grounding["duration_ms"]
77:         actual_power = grounding["power_kw"]
```

## G2：主体、工具、写权限和前提校验

源位置：`homecoord_bench/runtime/tool_contract.py:8`；摘录至第75行。

```text
8: def validate_tool_call(episode: dict[str, Any], agent_id: str,
9:                        task_id: str, action: dict[str, Any]) -> str | None:
10:     """Return a stable rejection reason, or None when an action is authorized.
11: 
12:     Legacy episodes keep their original semantics. Only episodes opting into
13:     strict-v1 are checked, avoiding silent changes to historical experiment data.
14:     """
15:     if episode.get("tool_contract_version") != "strict-v1":
16:         return None
17:     agent = next((a for a in episode["agents"] if a["agent_id"] == agent_id), None)
18:     if agent is None:
19:         return "unknown_agent"
20:     matches = [item for item in episode.get("tool_catalog", [])
21:                if item.get("agent_id") == agent_id
22:                and item.get("target") == action.get("target")
23:                and item.get("operation") == action.get("operation")]
24:     if len(matches) != 1:
25:         return "tool_not_authorized"
26:     tool = matches[0]
27:     if tool.get("tool_name") not in agent.get("tools", []):
28:         return "tool_not_authorized"
29:     if f"devices.{action['target']}" not in agent.get("writable_resources", []):
30:         return "target_not_writable"
31:     grounding = [item for item in episode.get("action_grounding", [])
32:                  if item.get("agent_id") == agent_id
33:                  and item.get("task_id") == task_id
34:                  and item.get("target") == action["target"]
35:                  and item.get("operation") == action["operation"]]
36:     if len(grounding) != 1:
37:         return "ungrounded_tool_action"
38:     entries = action.get("parameters", [])
39:     if not isinstance(entries, list) or any(not isinstance(p, dict) for p in entries):
40:         return "invalid_tool_parameters"
41:     values = {p.get("name"): p.get("value") for p in entries}
42:     if len(values) != len(entries):
43:         return "invalid_tool_parameters"
44:     specs = {p["name"]: p for p in tool.get("parameters", [])}
45:     if set(values) - set(specs) or any(p.get("required") and name not in values
46:                                      for name, p in specs.items()):
47:         return "invalid_tool_parameters"
48:     for name, value in values.items():
49:         spec = specs[name]
50:         declared_type = spec.get("type")
51:         if declared_type == "number":
52:             if isinstance(value, bool) or not isinstance(value, (int, float)):
53:                 return "invalid_tool_parameters"
54:         elif declared_type == "integer":
55:             if isinstance(value, bool) or not isinstance(value, int):
56:                 return "invalid_tool_parameters"
57:         elif declared_type == "boolean":
58:             if not isinstance(value, bool):
59:                 return "invalid_tool_parameters"
60:         elif declared_type == "string":
61:             if not isinstance(value, str):
62:                 return "invalid_tool_parameters"
63:         else:
64:             return "invalid_tool_parameters"
65:         if "minimum" in spec and value < spec["minimum"]:
66:             return "invalid_tool_parameters"
67:         if "maximum" in spec and value > spec["maximum"]:
68:             return "invalid_tool_parameters"
69:     requirements = action.get("requires", [])
70:     for required in tool.get("preconditions", []):
71:         if not any(r.get("path") == required["path"]
72:                    and r.get("op") == required["op"]
73:                    and r.get("value") == required["value"] for r in requirements):
74:             return "missing_tool_precondition"
75:     return None
```

## P1：调用状态与评分提示开关

源位置：`homecoord_bench/runtime/protocol.py:88`；摘录至第124行。

```text
88: def build_agent_request(
89:     episode: dict[str, Any],
90:     agent: dict[str, Any],
91:     task: dict[str, Any],
92:     *,
93:     architecture: str,
94:     current_time_ms: int,
95:     current_state: dict[str, Any] | None = None,
96:     state_version: int | None = None,
97:     pending_proposals: list[dict[str, Any]] | None = None,
98:     include_evaluation_hints: bool = False,
99:     request_id: str | None = None,
100:     released_task_ids: set[str] | None = None,
101: ) -> dict[str, Any]:
102:     """Build the exact provider-neutral input supplied to an agent."""
103:     source_state = deepcopy(episode["initial_state"]["values"] if current_state is None else current_state)
104:     observable = agent.get("observable_state", [])
105:     if observable == ["*"]:
106:         visible_state = source_state
107:     else:
108:         visible_state: dict[str, Any] = {}
109:         for path in dict.fromkeys([*observable, *agent.get("writable_resources", [])]):
110:             value = _get_path(source_state, path)
111:             if value is not _MISSING:
112:                 _set_path(visible_state, path, deepcopy(value))
113:     visible_task = deepcopy(task)
114:     if not include_evaluation_hints:
115:         # These fields are scoring keys or deterministic-script templates, not
116:         # information that a deployed agent would receive from a user.
117:         visible_task.pop("required_action", None)
118:         visible_task.pop("acceptable_actions", None)
119:         visible_task.pop("action_template", None)
120:     catalog = episode.get("tool_catalog", [])
121:     available_actions = [
122:         deepcopy(item) for item in catalog
123:         if agent["agent_id"] == "CentralAgent" or item.get("agent_id") == agent["agent_id"]
124:     ]
```
