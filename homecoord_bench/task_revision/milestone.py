"""Build and check development-only C1/C4 contracts; no API or held-out runs.

Print an artifact bundle; the caller persists it using apply_patch. C4 recovery
contracts are specified but NOT executed by the current shared event runtime.
"""
import hashlib
import json
import sys
from copy import deepcopy
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from make_representative_revision_drafts import load_candidate, _tool
from runtime.dry_run import DryRunClient
from runtime.event_simulator import run_event_simulation
from runtime.episode_validation import validate_event_episode
from evaluate import constraints_hold, get_path, set_path

OUT = 'homecoord_bench/revision_drafts/20261001_task_semantics'
STATUS = 'author_revised_not_independently_reviewed'

# The decisions concern structures, not approval of their old physics/labels.
DECISIONS = [
 ('M01','保留并修订','C1 同设备互斥','删除无关容量标签；温度跳变不作热响应证据','保护请求有效期 / 到期对照'),
 ('M02','修订','C1 持续使用权','能源 Agent 必须可见使用请求；初态安全','有效请求内 / 到期后关灯'),
 ('M03','修订','C1 持续隐私权','消除重复事件和初态违规；双方可见保护窗口','有效隐私内 / 到期后开帘'),
 ('M04','探索性重写','授权入户','缺到达、身份与合理解锁目标','有授权到达 / 无到达'),
 ('M05','合并结构后重写','C1 或期限 C3','和 M01 同设备结构重复；选定一个主机制','若转 C3 必须补期限与热服务合同'),
 ('M06','探索性保留','C2 通风制热','独立合成环境可跑，统一执行和参数因果依据不足','高 CO2 / 已达标；另需干预对照'),
 ('M07','探索性保留','C2 通风制冷','未执行环境效应，期限只有文字','冷热外界 / 兼容工况，需动力学'),
 ('M08','探索性重写','C2 湿度双控制','50% 与45%都安全，方向相反不等于冲突','先定义能源损失或互斥阈值'),
 ('M09','合并结构后重写','C2 通风制热','与 M06 类似；补通风结束/关门','相同周期、有无热损失'),
 ('M10','重分类重写','C3 功率限额','删能源表导致湿度上升的无因果效果','限额约束 / 足额供电'),
 ('M11','保留抽象结构','C3 两负载容量','声明预约单位/回路范围；不作物理照度响应','容量不足 / 充足，归入 F1'),
 ('M12','修订后另立依赖族','洗涤→烘干依赖','缺 washed 前提，不能当独立容量任务','依赖满足 / 未满足；再加容量因素'),
 ('M13','保留并修订','C3 期限竞争','把出发时间写成截止；SOC 跳变不作充电模型','紧 / 松期限与容量对照，归入 F1/F2'),
 ('M14','合并抽象结构','C3 固定负载','秒级餐食非真实周期；结构由 F1 覆盖','设备来源与周期须另审'),
 ('M15','合并抽象结构','C3 多房间分配','5秒降温不可信；可保留服务公平问题','先改设备服务，再定义公平指标'),
 ('M16','修订','C4 暂时失效后恢复','运行中可检测但未停止；第二观察动作不等于协作','无事件 / 启动前 / 运行中 / 完成后'),
 ('M17','修订','C4 请求撤回','降雨不再写土壤目标；停止不等于完成灌溉','同阶段配对；不需雨后重新灌溉'),
 ('M18','合并结构后重写','C4 生效后补偿','外部到达不算解锁服务；需身份检查和补偿','无人到达 / 到达前后；与 M20 共审'),
 ('M19','探索性重写','C4 意图撤回','分离睡眠意图、活动传感与窗帘效果','意图仍有效 / 撤回，避免事件满足目标'),
 ('M20','合并结构后重写','C4 布撤防补偿','与 M18 共性强；返回不算撤防服务','明确误报/保护时段与撤防回执'),
]


class FixedProposals(DryRunClient):
    """Author script, deliberately given answer templates; NOT an LLM baseline."""
    last_latency_ms = 300


def common(e, structure, condition):
    e['episode_id'] = 'REV-' + structure + '-' + condition
    e['base_episode_id'] = e.get('base_episode_id', e['episode_id'])
    e['review_status'] = STATUS
    e['tool_contract_version'] = 'strict-v1'
    e['variant'] = {'structure': structure, 'condition': condition, 'split': 'development'}
    e['simulation'] = {'command_latency_ms': 100}
    e['calibration'] = {'status': 'abstract_action_contract', 'physical_parameters_verified': False,
                        'source': 'author-defined synthetic duration, command and proposal latency'}
    e['task_card'] = {'information': 'observable_state is identical across paired conditions',
                      'tools': 'strict-v1 tool_catalog; exact permitted target/operation/parameters',
                      'resources': 'capacity nonbinding; not a C3 task',
                      'parameter_source': 'abstract author contract, not device measurements',
                      'success': 'completed service, disposition and process harm are separate',
                      'limitations': ['not independently reviewed', 'not physical validation',
                                      'fixed proposals use evaluation hints; no model evidence']}
    return e


def c1(kind, condition):
    light = kind == 'LIGHT'
    source = 'HC-M02' if light else 'HC-M03'
    e = load_candidate(source)
    e['base_episode_id'] = source
    common(e, 'C1-' + kind, condition)
    protection = 'study.reading_active' if light else 'bedroom.privacy_required'
    target = 'study_light' if light else 'bedroom_blinds'
    safe = 'reading' if light else 'closed'
    e['initial_state']['values']['devices'][target] = safe
    if light:
        e['initial_state']['values']['study'].pop('lux', None)
        for agent in e['agents']:
            agent['observable_state'] = [p for p in agent['observable_state'] if p != 'study.lux']
    e['conflict_rules'] = [r for r in e['conflict_rules'] if r['type'] == 'C1']
    e['exogenous_events'] = [{'at_ms': 6000, 'event': 'protected_request_expires',
                             'patch': {protection: False}}]
    high, low = e['task_stream']
    high['goal'] = 'Acknowledge and maintain the protected device state; this is not physical environment control.'
    low['release_at_ms'] = 1200 if condition == 'CONFLICT' else 6500
    low['goal'] = 'Execute the lower-priority request only when the protected request is inactive; otherwise reject it.'
    high['completion_deadline_ms'] = 1100
    low['completion_deadline_ms'] = 8000
    high['action_template']['requires'] = [{'path': protection, 'op': 'eq', 'value': True}]
    low['action_template']['requires'] = [{'path': protection, 'op': 'eq', 'value': False}]
    for task in (high, low):
        task['action_template']['duration_ms'] = 500
        agent = next(a for a in e['agents'] if a['agent_id'] == task['agent_id'])
        agent['observable_state'] = sorted(set(agent['observable_state'] + [protection, 'devices.' + target]))
    e['initial_state']['values']['service'] = {'protected': False, 'lower': False}
    e['goals'] = [{'path': 'service.protected', 'op': 'eq', 'value': True}]
    e['tool_catalog'] = []
    for idx, task in enumerate((high, low)):
        t = task['action_template']
        original = next(g for g in e['action_grounding'] if g['task_id'] == task['task_id'])
        original.pop('effects', None)
        original['start_effects'] = {}
        # Device-state abstractions only; do not use old instantaneous lux physics.
        original['completion_effects'] = {'devices.' + target: safe if idx == 0 else ('off' if light else 'open'),
                                          'service.' + ('protected' if idx == 0 else 'lower'): True}
        original['duration_ms'] = 500
        params = {name: {'type': 'number', 'minimum': 300, 'maximum': 800}
                  for name in t['parameters']}
        agent = next(a for a in e['agents'] if a['agent_id'] == task['agent_id'])
        e['tool_catalog'].append(_tool(agent['agent_id'], agent['tools'][0], task['goal'],
                                      target, t['operation'], params, t['requires']))
    e['task_card'].update({'request': 'Priority protects a state until time 6000, not merely during a command.',
                           'lifecycle': 'reject the invalid lower request; do not mark rejection as its action service',
                           'matching_factor': 'lower task release_at_ms only',
                           'resolution_contract': {'lower_task_id': low['task_id'],
                                                   'expected': 'rejected' if condition == 'CONFLICT' else 'completed'}})
    return e


def c4(kind, condition):
    cleaning = kind == 'CLEAN'
    source = 'HC-M16' if cleaning else 'HC-M17'
    e = load_candidate(source)
    e['base_episode_id'] = source
    common(e, 'C4-' + kind, condition)
    main, monitor = e['task_stream']
    main['goal'] = 'Complete an abstract cleaning service while vacant.' if cleaning else 'Complete an abstract irrigation service unless rain withdraws the request.'
    signal = 'bedroom.occupied' if cleaning else 'garden.raining'
    # Determine canonical rain path from the task rather than assume its room name.
    if not cleaning:
        signal = main['action_template']['requires'][0]['path']
    main.pop('recovery', None)
    main['action_template']['parameters'] = {}
    main['action_template']['requires'] = [{'path': signal, 'op': 'eq', 'value': False}]
    main['completion_deadline_ms'] = 10000
    monitor['release_at_ms'] = 0
    monitor['completion_deadline_ms'] = 2000
    e['initial_state']['values']['service'] = {'work_completed': False, 'monitor_completed': False}
    e['initial_state']['values']['diagnostic'] = {'heartbeat': 0}
    e['goals'] = [{'path': 'service.work_completed', 'op': 'eq', 'value': True},
                  {'path': 'service.monitor_completed', 'op': 'eq', 'value': True}]
    e['conflict_rules'] = [{'type': 'C4', 'task_id': main['task_id'],
                            'invalidating_conditions': main['action_template']['requires']}]
    e['exogenous_events'] = []
    at = {'PRESTART': 200, 'INFLIGHT': 1000, 'POSTCOMPLETE': 4000}.get(condition)
    if at is not None:
        e['exogenous_events'].append({'at_ms': at, 'event': 'resident_enters' if cleaning else 'rain_begins',
                                      'patch': {signal: True}})
        if cleaning:
            e['exogenous_events'].append({'at_ms': 5000, 'event': 'resident_leaves', 'patch': {signal: False}})
    elif condition == 'UNRELATED':
        e['exogenous_events'] = [{'at_ms': 1000, 'event': 'heartbeat', 'patch': {'diagnostic.heartbeat': 1}}]
    e['tool_catalog'] = []
    for idx, task in enumerate((main, monitor)):
        t = task['action_template']
        t['duration_ms'] = 3000 if idx == 0 else 100
        ground = next(g for g in e['action_grounding'] if g['task_id'] == task['task_id'])
        ground.pop('effects', None)
        ground['duration_ms'] = t['duration_ms']
        ground['start_effects'] = {'devices.' + t['target']: ('running' if cleaning else 'on')} if idx == 0 else {}
        ground['completion_effects'] = {'service.' + ('work_completed' if idx == 0 else 'monitor_completed'): True}
        if idx == 0:
            ground['completion_effects']['devices.' + t['target']] = 'idle' if cleaning else 'off'
        agent = next(a for a in e['agents'] if a['agent_id'] == task['agent_id'])
        agent['observable_state'] = sorted(set(agent['observable_state'] + [signal]))
        e['tool_catalog'].append(_tool(agent['agent_id'], agent['tools'][0], task['goal'],
                                      t['target'], t['operation'], {}, t.get('requires', [])))
    e['task_card'].update({'request': 'cleaning temporarily paused vs irrigation permanently withdrawn on rain',
                           'matching_factor': 'event timing / absence; UNRELATED changes irrelevant state only',
                           'lifecycle': {'expected_after_invalidation': 'stop then restart after vacancy' if cleaning else 'stop; withdraw irrigation request',
                                         'stop_ack_delay_ms': 200, 'restart_from_zero': cleaning,
                                         'runtime_support': 'start revalidation + in-flight detection only; stop/restart NOT implemented'},
                           'monitor_role': 'separate service receipt, not evidence of a coordinating agent',
                           'no_goal_leakage': 'external events do not write any service receipt'})
    return e


def drafts():
    return ([c1(k, c) for k in ('LIGHT', 'BLINDS') for c in ('CONFLICT', 'SAFE')]
            + [c4(k, c) for k in ('CLEAN', 'RAIN')
               for c in ('NOEVENT', 'PRESTART', 'INFLIGHT', 'POSTCOMPLETE', 'UNRELATED')])


def score(e, trace, result):
    """Completion ≠ resolution ≠ process-valid service; never replace missing with zero."""
    tasks = e['task_stream']
    completed = dict(result['task_correct_action_completed'])
    invalid = result['in_flight_precondition_invalidated_action_count']
    harm = result['state_constraint_violation_duration_ms']
    resolution = None
    contract = e['task_card'].get('resolution_contract')
    if contract:
        tid = contract['lower_task_id']
        rejections = [x for x in trace['events'] if x['type'] == 'action_rejected' and x['task_id'] == tid]
        # Other reasons (e.g. capacity/tool schema failure) do not fulfill the disposition.
        rejected = any(x.get('reason') in ('unsafe_precondition', 'stale_state') for x in rejections)
        resolution = rejected if contract['expected'] == 'rejected' else completed[tid]
    return {'action_completed': completed,
            'completion_latency_ms': result['task_completion_latency_ms'],
            'resolution_correct': resolution,
            'in_flight_invalidations': invalid, 'harm_duration_ms': harm,
            'work_process_valid_completed': completed[tasks[0]['task_id']] and invalid == 0 and harm == 0,
            'recovery_completed': None, 'recovery_status': 'not implemented / not measured'}


def audit_trace(e, trace, reported):
    """Independent state replay and completion/harm recount, without core metrics."""
    state = deepcopy(e['initial_state']['values'])
    active, completed, invalidated = {}, set(), set()
    clock, harm = 0, 0
    for event in trace['events']:
        now = event['timestamp_ms']
        assert now >= clock
        if not constraints_hold(state, e['constraints']):
            harm += now - clock
        clock = now
        kind = event['type']
        if kind == 'action_started':
            task = next(t for t in e['task_stream'] if t['task_id'] == event['task_id'])
            assert now >= task['release_at_ms']
            assert all(get_path(state, r['path']) == r['value'] for r in event['requires'])
            active[event['proposal_id']] = event
        if kind == 'action_completed':
            start = active.pop(event['proposal_id'])
            assert (event['task_id'], event['target'], event['operation']) == (start['task_id'], start['target'], start['operation'])
            ground = next(g for g in e['action_grounding'] if g['task_id'] == event['task_id'])
            assert now == start['timestamp_ms'] + ground['duration_ms']
            assert event['effects'] == ground['completion_effects']
            completed.add(event['task_id'])
        patch = event.get('patch', {}) if kind == 'state_update' else event.get('effects', {}) if kind == 'action_completed' else {}
        for path, value in patch.items():
            set_path(state, path, value)
        for proposal, action in active.items():
            if any(get_path(state, r['path']) != r['value'] for r in action['requires']):
                invalidated.add(proposal)
    assert state == trace['final_state']
    assert not active
    assert harm == reported['harm_duration_ms'], (harm, reported)
    assert len(invalidated) == reported['in_flight_invalidations']
    assert {t['task_id']: t['task_id'] in completed for t in e['task_stream']} == reported['action_completed']
    return {'state_replay': 'passed', 'completion_recount': 'passed', 'harm_integral_ms': harm,
            'invalidated_actions': len(invalidated)}


def verify(e):
    errors = validate_event_episode(e)
    if errors:
        raise AssertionError((e['episode_id'], errors))
    trace, result = run_event_simulation(e, FixedProposals(), 'IndependentMultiAgent', '', shared_safety_gate=True)
    s = score(e, trace, result)
    independent_audit = audit_trace(e, trace, s)
    c = e['variant']['condition']
    if e['variant']['structure'].startswith('C1'):
        assert s['resolution_correct'] and s['work_process_valid_completed'], (e['episode_id'], s)
        assert s['harm_duration_ms'] == 0
    elif c == 'PRESTART':
        assert not s['action_completed'][e['task_stream'][0]['task_id']]
        assert s['completion_latency_ms'][e['task_stream'][0]['task_id']] is None
        assert s['in_flight_invalidations'] == 0 and s['harm_duration_ms'] == 0
    elif c == 'INFLIGHT':
        # This is a regression trap, NOT a claim that today's runtime recovers safely.
        assert s['action_completed'][e['task_stream'][0]['task_id']]
        assert s['in_flight_invalidations'] == 1 and s['harm_duration_ms'] == 2400, s
        assert not s['work_process_valid_completed']
    else:
        assert s['work_process_valid_completed'] and s['in_flight_invalidations'] == 0
    return {'episode_id': e['episode_id'], 'score': s,
            'independent_audit': independent_audit,
            'trace': {k: trace[k] for k in ('episode_id', 'policy', 'events', 'final_state', 'final_state_version')},
            'runner': 'shared run_event_simulation + FixedProposals(300ms), no API',
            'verification': 'passed expected semantics; inflight cases intentionally expose missing cancellation'}


def inventory():
    rows, excluded = [], []
    # Do not open prospective files, even for static task-content inspection.
    for directory in ('data', 'revision_drafts'):
        for p in sorted((ROOT / directory).rglob('*.json')):
            rel = p.relative_to(ROOT).as_posix()
            if 'prospective_test' in p.parts:
                excluded.append(rel)
                continue
            if '20261001_task_semantics' in p.parts:
                continue  # new drafts are indexed separately, avoiding rerun feedback
            obj = json.loads(p.read_text(encoding='utf-8-sig'))
            if not isinstance(obj, dict) or not {'episode_id', 'task_stream', 'agents'} <= obj.keys():
                continue
            family = obj.get('task_family', obj.get('variant', {}).get('family'))
            if directory == 'data' and p.parent.name == 'candidates':
                category = 'canonical_pending_revision'
            elif '20260930_task_family_split' in p.parts:
                category = 'C3_development_author_contract'
            elif '20261001_architecture_comparison' in p.parts:
                category = 'frozen_architecture_input_snapshot_not_new_task'
            else:
                category = 'historical_or_derived_not_independent_structure'
            rows.append({'path': rel, 'episode_id': obj['episode_id'],
                         'base_episode_id': obj.get('base_episode_id'), 'family': family,
                         'decision': category, 'status': obj.get('review_status'),
                         'agents': len(obj['agents']), 'tasks': len(obj['task_stream']),
                         'strict_tools': obj.get('tool_contract_version') == 'strict-v1',
                         'explicit_deadlines': sum(t.get('completion_deadline_ms') is not None for t in obj['task_stream']),
                         'runner': 'event-schema input; compatibility NOT implied by indexing',
                         'sha256': hashlib.sha256(p.read_bytes()).hexdigest()})
    return {'scope': 'all episode-shaped JSON under data/ and revision_drafts/; independent probes indexed in report',
            'decision_counts': dict(Counter(r['decision'] for r in rows)),
            'artifact_count_not_structure_count': len(rows), 'artifacts': rows,
            'heldout_unopened_paths': excluded,
            'new_drafts_indexed_separately': 14,
            'canonical_decisions': [{'episode_id': 'HC-' + i, 'decision': d, 'structure': s,
                                     'gap': g, 'control': c} for i,d,s,g,c in DECISIONS]}


def bundle():
    episodes = drafts()
    inv = inventory()
    checks = [verify(e) for e in episodes]
    paths = {f'{OUT}/{e["episode_id"]}.json': e for e in episodes}
    paths['homecoord_bench/results/task_semantics_inventory_20261001.json'] = inv
    paths['homecoord_bench/results/task_semantics_verification_20261001.json'] = {
        'status': STATUS, 'api_calls': 0, 'scenario_templates': 4, 'mechanism_contracts': 3, 'configurations': 14,
        'heldout_executions': 0, 'checks': checks}
    paths[f'{OUT}/manifest.json'] = {'status': STATUS, 'scenario_templates': 4, 'mechanism_contracts': 3, 'configurations': 14,
        'diversity_note': 'LIGHT and BLINDS share the same persistent-protection control graph; not two independent mechanisms',
        'files': [{'path': p, 'episode_id': e['episode_id']} for p,e in paths.items() if p.startswith(OUT)],
        'no_canonical_overwrites': True, 'recovery_runtime_support': False}
    return paths


if __name__ == '__main__':
    data = bundle()
    if len(sys.argv) == 1:
        print(json.dumps({'artifacts': list(data), 'configurations': 14, 'checks_passed': 14}, ensure_ascii=True))
    else:
        serialized = json.dumps(data[sys.argv[1]], ensure_ascii=False, indent=2) + '\n'
        offset = int(sys.argv[2]) if len(sys.argv) > 2 else 0
        # Bounded transport chunks, not shell/file writes.
        print(json.dumps({'text': serialized[offset:offset + 18000],
                          'next_offset': offset + 18000 if len(serialized) > offset + 18000 else None}, ensure_ascii=True))
