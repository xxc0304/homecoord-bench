"""Limited synthetic user delegation: terminal admission, not retry/wait."""
from copy import deepcopy
from evaluate import get_path


def validate(e,policy,gate):
    contracts=e.get('simulation',{}).get('request_disposition_contracts',{})
    if not isinstance(contracts,dict):raise ValueError('invalid disposition contracts')
    if not contracts:return {}
    if policy not in ('IndependentMultiAgent','GateRetryRule','ConstraintCoordinator','DeadlineAwareCoordinator') or not gate:
        raise ValueError('disposition requires ordinary supported policy and shared gate')
    sim=e['simulation']
    if set(sim)-{'command_latency_ms','request_disposition_contracts'} or any(t.get('depends_on') for t in e['task_stream']):
        raise ValueError('disposition mixed environment/lifecycle/DAG/compute not supported')
    if e.get('tool_contract_version')!='strict-v1':raise ValueError('strict tools required')
    tasks={t['task_id']:t for t in e['task_stream']}
    policies={p['policy_id']:p for p in e.get('user_delegations',[])}
    if len(policies)!=len(e.get('user_delegations',[])):raise ValueError('duplicate delegation policy')
    for tid,c in contracts.items():
        if tid not in tasks or set(c)!={'policy_id','admit_when','rejection_terminal'} or c['rejection_terminal'] is not True:
            raise ValueError('unknown task or nonterminal contract')
        p=policies.get(c['policy_id']);t=tasks[tid]
        if not p or p.get('authority')!='explicit_synthetic_user_delegation' or not p.get('principal'):
            raise ValueError('missing explicit user authority')
        if p.get('request_semantics')!='reject_terminal_at_release_no_wait' or p.get('expiry_visibility')!='current_boolean_only':
            raise ValueError('ambiguous request semantics or future visibility')
        if type(get_path(e['initial_state']['values'],p['protected_path'])) is not bool:
            raise ValueError('admission state must be an explicit boolean')
        expected=[{'path':p['protected_path'],'op':'eq','value':False}]
        if c['admit_when']!=expected or t['action_template']['requires']!=expected or t.get('request_contract')!=c:
            raise ValueError('admission and request preconditions inconsistent')
        owner=next(a for a in e['agents'] if a['agent_id']==t['agent_id'])
        if p['protected_path'] not in owner['observable_state']:raise ValueError('hidden admission state')
        ground=[g for g in e['action_grounding'] if g['task_id']==tid]
        if len(ground)!=1 or ground[0]['target']!=p['target']:raise ValueError('delegation does not cover target')
    return deepcopy(contracts)
