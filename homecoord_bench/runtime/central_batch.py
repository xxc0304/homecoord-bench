"""Opt-in central proposals per release batch; common physical executor."""
import hashlib
from copy import deepcopy
from time import perf_counter_ns
from .protocol import AGENT_DECISION_SCHEMA, build_agent_request, assert_agent_decision
from .tool_contract import validate_tool_call
from .deepseek_client import DeepSeekResponsesClient

BATCH_SCHEMA = {'type': 'object', 'properties': {'task_decisions': {'type': 'array', 'items': {
    'type': 'object', 'properties': {'task_id': {'type': 'string'}, 'decision': deepcopy(AGENT_DECISION_SCHEMA)},
    'required': ['task_id', 'decision'], 'additionalProperties': False}}},
    'required': ['task_decisions'], 'additionalProperties': False}

def build_batch_request(episode, at_ms, state, state_version):
    tasks = [t for t in episode['task_stream'] if t['release_at_ms'] == at_ms]
    if not tasks:
        raise ValueError('no newly released tasks for batch')
    public = deepcopy(episode)
    public_id = 'HC-BATCH-' + hashlib.sha256(episode['base_episode_id'].encode()).hexdigest()[:12]
    public['episode_id'] = public['base_episode_id'] = public_id
    requests = []
    released = {t['task_id'] for t in episode['task_stream'] if t['release_at_ms'] <= at_ms}
    for task in tasks:
        agent = next(a for a in episode['agents'] if a['agent_id'] == task['agent_id'])
        requests.append(build_agent_request(public, agent, task, architecture='FunctionalSpecialistView',
            current_time_ms=at_ms, current_state=state, state_version=state_version, released_task_ids=released,
            request_id=f'{public_id}:{at_ms}:{task["task_id"]}'))
    return {'request_id': f'{public_id}:{at_ms}:batch', 'episode_id': public_id,
        'architecture': 'CentralBatchProposer', 'current_time_ms': at_ms, 'state_version': state_version,
        'task': {'task_id': 'release_batch'}, 'agent': {'agent_id': 'CentralBatchAgent'},
        'task_requests': requests, 'information_contract': 'union of current release-group specialist views; no raw global state or cross-batch memory'}

def assert_batch_decision(decision, request, episode=None):
    if not isinstance(decision, dict) or set(decision) != {'task_decisions'} or not isinstance(decision['task_decisions'], list):
        raise ValueError('batch must contain exactly task_decisions list')
    children = {r['task']['task_id']: r for r in request['task_requests']}
    seen, proposals = set(), set()
    for entry in decision['task_decisions']:
        if not isinstance(entry, dict) or set(entry) != {'task_id', 'decision'}:
            raise ValueError('invalid batch entry')
        task_id = entry['task_id']
        if not isinstance(task_id, str) or task_id not in children or task_id in seen:
            raise ValueError('unknown, future, or duplicate batch task')
        seen.add(task_id)
        if not isinstance(entry['decision'], dict):
            raise ValueError('task decision must be an object')
        assert_agent_decision(entry['decision'])
        child = children[task_id]
        for action in entry['decision']['actions']:
            for field in ('proposal_id', 'target', 'operation'):
                if not isinstance(action.get(field), str) or not action[field]:
                    raise ValueError('batch action identifiers must be nonempty strings')
            if action['proposal_id'] in proposals:
                raise ValueError('duplicate proposal_id across batch')
            proposals.add(action['proposal_id'])
            if action['based_on_state_version'] != child['state_version']:
                raise ValueError('batch action does not use request state version')
            allowed = [t for t in child['available_actions'] if t['tool_name'] in child['allowed_tools']
                       and t['target'] == action['target'] and t['operation'] == action['operation']]
            if len(allowed) != 1:
                raise ValueError('batch action not authorized for this task')
            if episode is not None:
                error = validate_tool_call(episode, child['agent']['agent_id'], task_id, action)
                if error:
                    raise ValueError(error)
    if seen != set(children):
        raise ValueError('batch omitted a released task; return explicit defer/noop instead')

class CentralBatchDeepSeekClient(DeepSeekResponsesClient):
    """Same transport/logger; separate response schema and validation hook."""
    def __init__(self, **kwargs):
        kwargs.setdefault('max_attempts', 1)
        super().__init__(**kwargs)
    def build_payload(self, agent_request, instructions):
        payload = super().build_payload(agent_request, instructions)
        payload['text']['format'].update(name='homecoord_release_batch', schema=deepcopy(BATCH_SCHEMA))
        payload['max_output_tokens'] = 1200 * len(agent_request['task_requests'])
        payload['instructions'] = ('Return task_decisions covering each newly released task exactly once. '
            'Use its scoped tools and state. Do not propose for future/previous tasks. '
            'Choose at most one action per task, or an explicit defer/noop. ' + instructions)
        return payload
    def validate_decision(self, decision, agent_request):
        assert_batch_decision(decision, agent_request)
    def decide_batch(self, request, instructions=''):
        return self.decide(request, instructions)

class ReleaseBatchAdapter:
    include_evaluation_hints = False
    proposal_architecture = 'CentralBatchProposer'
    allowed_execution_policies = {'GateRetryRule', 'ConstraintCoordinator', 'DeadlineAwareCoordinator'}
    def __init__(self, provider):
        self.provider = provider
        self.records, self.batches, self.consumed = {}, [], set()
        self.proposal_ids = set()
        self.last_latency_ms = 0
    def prepare_release_batch(self, episode, at_ms, state, version, instructions=''):
        if any(b['request']['current_time_ms'] == at_ms for b in self.batches):
            return
        request = build_batch_request(episode, at_ms, state, version)
        started = perf_counter_ns()
        decision = self.provider.decide_batch(request, instructions)
        latency = max(1, round((perf_counter_ns() - started) / 1e6))
        # Only explicit script/replay providers override measurement. Real API
        # clients use actual elapsed time for the single shared batch call.
        override = getattr(self.provider, 'scripted_batch_latency_ms', None)
        if override is not None:
            if isinstance(override, bool) or not isinstance(override, int) or override < 1:
                raise ValueError('scripted batch latency must be a positive integer')
            latency = override
        assert_batch_decision(decision, request, episode)
        ids = {a['proposal_id'] for entry in decision['task_decisions'] for a in entry['decision']['actions']}
        if ids & self.proposal_ids:
            raise ValueError('duplicate proposal_id across release batches')
        self.proposal_ids.update(ids)
        self.batches.append({'request': request, 'decision': deepcopy(decision), 'logical_latency_ms': latency})
        for entry in decision['task_decisions']:
            tid = entry['task_id']
            if tid in self.records:
                raise ValueError('task proposed twice across release batches')
            self.records[tid] = {'decision': deepcopy(entry['decision']), 'logical_latency_ms': latency}
    def decide(self, request, instructions=''):
        tid = request['task']['task_id']
        if tid not in self.records or tid in self.consumed:
            raise ValueError('missing or duplicated batch decision consumption')
        self.consumed.add(tid)
        self.last_latency_ms = self.records[tid]['logical_latency_ms']
        return deepcopy(self.records[tid]['decision'])
    def assert_consumed(self):
        if self.consumed != set(self.records):
            raise ValueError('batch decisions left unused')
