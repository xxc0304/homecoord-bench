"""F2 request-only whitelist v1. Static capabilities are not future demand."""
from copy import deepcopy

POLICIES = ('IndependentMultiAgent', 'ConstraintCoordinator', 'DeadlineAwareCoordinator', 'GateRetryRule')


def validate_f2(e, provider, policy, instructions, shared_gate, synthetic_latency, coordination_delay):
    if e.get('f2_information_contract') != 'request-only-whitelist-v1':
        raise ValueError('explicit F2 information contract required')
    if policy not in POLICIES or not shared_gate or synthetic_latency or coordination_delay:
        raise ValueError('F2 v7 supports four online policies, shared gate and measured-script latency only')
    if instructions or getattr(provider, 'prepare_release_batch', None) is not None:
        raise ValueError('no external instructions or episode-level preparation side channel')
    if set(e.get('simulation', {})) != {'command_latency_ms'} or e.get('constraints'):
        raise ValueError('no extra simulation plans, potential arrivals or unsupported constraints')
    if e.get('conflict_rules') != [{'type': 'C3', 'capacity': e['home']['resources']['max_power_kw']}]:
        raise ValueError('only the shared public capacity rule is supported')
    if e.get('nonpreemptive_delegation', {}).get('authority') != 'explicit_synthetic_service_contract':
        raise ValueError('explicit synthetic nonpreemptive delegation required')
    devices = {d['agent_id']: d for d in e['public_devices']}
    if len(devices) != len(e['public_devices']):
        raise ValueError('duplicate static device identity')
    for d in devices.values():
        if set(d) != {'agent_id', 'role', 'target', 'service', 'duration_ms', 'resource_units'}:
            raise ValueError('static capabilities use an exact whitelist, no free-form metadata')
        if (d['role'] not in {'laundry', 'dishes', 'cleaning', 'water', 'meal'}
                or d['agent_id'] != d['role'].title() + 'Agent'
                or d['target'] != d['role'] + '_device' or d['service'] != d['role'] + '_completed'):
            raise ValueError('noncanonical static device identity')
    for t in e['task_stream']:
        d = devices[t['agent_id']]
        template = t['action_template']
        if (template['target'] != d['target'] or template['operation'] != 'prepare'
                or template['duration_ms'] != d['duration_ms'] or template['power_kw'] != d['resource_units']):
            raise ValueError('execution cost must match independently declared static capability')
        if t['completion_deadline_ms'] <= t['release_at_ms']:
            raise ValueError('deadline must follow own release')
        tool = next(c for c in e['tool_catalog'] if c['agent_id'] == d['agent_id'] and c['operation'] == 'prepare')
        ground = next(g for g in e['action_grounding'] if g['task_id'] == t['task_id'] and g['operation'] == 'prepare')
        if (tool['cost_contract'] != {'duration_ms': d['duration_ms'], 'resource_units': d['resource_units']}
                or ground['duration_ms'] != d['duration_ms'] or ground['power_kw'] != d['resource_units']):
            raise ValueError('public costs and actual service execution must agree')


def public_task(t, d):
    return {'task_id': t['task_id'], 'agent_id': d['agent_id'],
            'release_at_ms': t['release_at_ms'], 'completion_deadline_ms': t['completion_deadline_ms'],
            'priority': t['priority'], 'requested_service': d['service'],
            'goal': 'Complete the requested service using the authorized prepare operation before its deadline; once started, finish the nonpreemptive cycle.'}


def build_agent_request(episode, agent, task, *, architecture, current_time_ms,
                        current_state=None, state_version=None, **ignored):
    devices = {d['agent_id']: d for d in episode['public_devices']}
    own = devices[task['agent_id']]
    # Publication is atomic at a timestamp: all requests released at that time
    # are visible, independent of event insertion order or method.
    released = [t for t in episode['task_stream'] if t['release_at_ms'] <= current_time_ms]
    public = [public_task(t, devices[t['agent_id']]) for t in released]
    state = current_state or episode['initial_state']['values']
    path = 'devices.' + own['target']
    catalog = []
    for op, duration, units in [('prepare', own['duration_ms'], own['resource_units']), ('off', 100, 0)]:
        catalog.append({'agent_id': own['agent_id'], 'tool_name': own['role'] + '_' + op,
                        'target': own['target'], 'operation': op, 'parameters': [],
                        'preconditions': [{'path': path, 'op': 'eq', 'value': 'idle'}],
                        'provides_service': own['service'] if op == 'prepare' else 'none',
                        'cost_contract': {'duration_ms': duration, 'resource_units': units},
                        'description': 'Static authorized operation; availability does not imply a request exists.'})
    canonical_agent = {'agent_id': own['agent_id'], 'role': own['role'],
                       'tools': [x['tool_name'] for x in catalog],
                       'observable_state': [path, 'coordination_context'],
                       'writable_resources': [path], 'goal_visibility': 'released',
                       'constraint_visibility': 'public'}
    return {'request_id': f"F2-public-home:{architecture}:{task['task_id']}",
            'episode_id': 'F2-public-home', 'base_episode_id': 'F2-public-home',
            'architecture': architecture, 'current_time_ms': current_time_ms,
            'state_version': state_version if state_version is not None else episode['initial_state']['version'],
            'agent': canonical_agent, 'task': public_task(task, own),
            'state': {'devices': {own['target']: state['devices'][own['target']]},
                      'coordination_context': {
                          'resource_capacity_units': episode['home']['resources']['max_power_kw'],
                          'objective': 'complete released services within their own deadlines',
                          'requests': public,
                          'static_devices': deepcopy(episode['public_devices'])}},
            'goals': [{'path': 'devices.' + devices[t['agent_id']]['target'], 'op': 'eq', 'value': 'complete'} for t in released],
            'constraints': [], 'allowed_tools': canonical_agent['tools'],
            'available_actions': catalog, 'pending_proposals': []}
