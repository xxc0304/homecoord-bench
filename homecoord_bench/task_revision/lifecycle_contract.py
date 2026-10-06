"""Explicit trusted-actuator lifecycle contracts, not LLM stopping decisions."""
from copy import deepcopy
from runtime.episode_validation import validate_event_episode


def validate_contracts(episode, policy):
    contracts = episode.get('simulation', {}).get('lifecycle_contracts', {})
    if not isinstance(contracts, dict):
        raise ValueError('lifecycle_contracts must be an object')
    if not contracts:
        return contracts
    if episode.get('tool_contract_version') != 'strict-v1':
        raise ValueError('lifecycle v2 requires strict-v1 tool contracts')
    if policy not in {'IndependentMultiAgent', 'ConstraintCoordinator', 'DeadlineAwareCoordinator', 'GateRetryRule'}:
        raise ValueError('lifecycle v2 policy not yet supported')
    simulation = episode['simulation']
    if any(k in simulation for k in ('released_batch_plan', 'coordination_compute_profile', 'released_batch_compute_ms')):
        raise ValueError('lifecycle v2 does not yet support timed compute/planned batches')
    errors = validate_event_episode(episode)
    if errors:
        raise ValueError(str(errors))
    tasks = {t['task_id']: t for t in episode['task_stream']}
    agents = {a['agent_id']: a for a in episode['agents']}
    for tid, c in contracts.items():
        if tid not in tasks or not isinstance(c, dict):
            raise ValueError('lifecycle contract must reference a task')
        if set(c) != {'mode', 'valid_when', 'stop_ack_delay_ms', 'restart_delay_ms', 'stop_effects'}:
            raise ValueError('lifecycle contract requires exact documented fields')
        if c['mode'] not in {'restart_from_zero', 'withdraw'}:
            raise ValueError('unknown lifecycle mode')
        for k in ('stop_ack_delay_ms', 'restart_delay_ms'):
            if isinstance(c[k], bool) or not isinstance(c[k], int) or c[k] < 0:
                raise ValueError(k + ' must be a nonnegative integer')
        t = tasks[tid]
        valid = c['valid_when']
        if not isinstance(valid, list) or not valid or any(not isinstance(r, dict) or set(r) != {'path','op','value'} or r['op'] != 'eq' for r in valid):
            raise ValueError('v2 lifecycle valid_when requires explicit eq conditions')
        if any(r['path'] not in agents[t['agent_id']]['observable_state'] for r in valid):
            raise ValueError('lifecycle validity must be observable to the task owner')
        spec = t.get('required_action')
        if not spec:
            raise ValueError('v2 lifecycle requires one declared required action')
        ground = [g for g in episode['action_grounding'] if g['task_id'] == tid
                  and g['agent_id'] == t['agent_id'] and g['target'] == spec['target'] and g['operation'] == spec['operation']]
        if len(ground) != 1:
            raise ValueError('lifecycle requires one unambiguous grounding')
        tools = [tool for tool in episode.get('tool_catalog', []) if tool['agent_id'] == t['agent_id']
                 and tool['target'] == spec['target'] and tool['operation'] == spec['operation']]
        if len(tools) != 1 or tools[0]['preconditions'] != valid:
            raise ValueError('lifecycle validity must match the strict tool preconditions')
        device = 'devices.' + spec['target']
        if device not in agents[t['agent_id']]['writable_resources']:
            raise ValueError('task owner cannot stop this device')
        effects = c['stop_effects']
        if not isinstance(effects, dict) or set(effects) != {device}:
            raise ValueError('stop effects may only affect the authorized device, never service receipts')
        if effects != {device: ground[0]['completion_effects'].get(device)}:
            raise ValueError('stop state must match the declared quiescent completion state')
    return deepcopy(contracts)
