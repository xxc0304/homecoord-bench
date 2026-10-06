"""Independent completion-DAG recount plus existing lifecycle state replay."""
from copy import deepcopy
from homecoord_bench.task_revision.lifecycle_audit import audit as lifecycle_audit, metrics as lifecycle_metrics


def receipt_events(e,trace):
    withdrawn=set()
    receipt={}
    tasks={t['task_id']:t for t in e['task_stream']}
    for x in trace['events']:
        if x['type']=='task_withdrawn': withdrawn.add(x['task_id'])
        if x['type']=='action_completed':
            spec=tasks[x['task_id']]['required_action']
            if x['task_id'] not in withdrawn and (x['target'],x['operation'])==(spec['target'],spec['operation']):
                receipt.setdefault(x['task_id'],x['timestamp_ms'])
    return receipt


def metrics(e,trace,result):
    receipts=receipt_events(e,trace)
    starts=[x for x in trace['events'] if x['type']=='action_started' and x['task_id']=='dry']
    return {'completed':deepcopy(result['task_correct_action_completed']),
            'completion_latency_ms':result['task_completion_latency_ms'],
            'completion_tardiness_ms':result['task_completion_tardiness_ms'],
            'request_released_at_ms':{t['task_id']:t['release_at_ms'] for t in e['task_stream']},
            'predecessor_completion_receipts_ms':receipts,
            'dry_started_without_wash_receipt':sum('wash' not in receipts or x['timestamp_ms']<receipts['wash'] for x in starts),
            'waiting_tasks':result.get('dependency_waiting_task_ids',[]),
            'blocked_tasks':result.get('dependency_blocked_task_ids',[]),
            'dependency_dispatch_ready_at_ms':result.get('dependency_dispatch_ready_at_ms',{}),
            'lifecycle':lifecycle_metrics(e,trace,result)}


def audit(e,trace,reported,enforce_dependencies=True):
    physical=lifecycle_audit(e,trace,reported['lifecycle'])
    receipts=receipt_events(e,trace)
    assert receipts==reported['predecessor_completion_receipts_ms']
    tasks={t['task_id']:t for t in e['task_stream']}
    done,withdrawn,waiting,blocked=set(),set(),set(),set()
    bad=0
    for x in trace['events']:
        if x['type']=='task_withdrawn': withdrawn.add(x['task_id'])
        if x['type']=='action_completed' and x['task_id'] not in withdrawn:
            spec=tasks[x['task_id']]['required_action']
            if (x['target'],x['operation'])==(spec['target'],spec['operation']): done.add(x['task_id'])
        if x['type']=='dependency_waiting':waiting.add(x['task_id'])
        if x['type']=='dependency_blocked':
            waiting.discard(x['task_id']);blocked.add(x['task_id'])
            assert any(d in withdrawn or d in blocked for d in tasks[x['task_id']]['depends_on']) or x['task_id'] in withdrawn
        if x['type']=='dependency_ready':waiting.discard(x['task_id'])
        if x['type'] in ('dependency_ready','action_started'):
            tid=x['task_id']
            satisfied=all(d in done and d not in withdrawn for d in tasks[tid].get('depends_on',[]))
            if enforce_dependencies: assert satisfied, (tid,x)
            if x['type']=='action_started' and tid=='dry' and not satisfied: bad+=1
        if x['type']=='dependency_ready': assert x['predecessors']==tasks[x['task_id']]['depends_on']
    assert bad==reported['dry_started_without_wash_receipt']
    assert reported['completed']==reported['lifecycle']['action_completed']
    assert waiting==set(reported['waiting_tasks'])
    assert blocked==set(reported['blocked_tasks'])
    return {'physical_replay':physical,'completion_dag':'passed' if enforce_dependencies else 'diagnostic_feature_off',
            'dependency_violation_recount':bad}
