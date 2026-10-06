"""Release-time, failure-preserving providers for the architecture pilot."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from threading import Lock
from time import perf_counter_ns

from .central_batch import build_batch_request, assert_batch_decision
from .protocol import assert_agent_decision
from .tool_contract import validate_tool_call

ARMS = ('central_batch', 'functional_local', 'functional_pooled')
POLICY = 'DeadlineAwareCoordinator'
INSTRUCTIONS = (
    'Provide the currently requested service using the public cost contracts. '
    'All services and deadlines come first; then prefer earlier completion of all requests. '
    'Choose at most one action for each task you are assigned. Use only its own allowed tools '
    'and the current state version. Other task views, if supplied, are read-only context. '
    'Do not predict future requests or output execution start times. '
    'Return an explicit defer/noop if you cannot propose a service. '
    'Use response_type, native value, and range_min/range_max (null except for between).'
)


def failure_defer():
    """Local executor placeholder, explicitly distinct from a model response."""
    return {'response_type': 'defer', 'actions': [], 'accepted_proposal_ids': [],
            'rejected_proposal_ids': [], 'defer_until_ms': None, 'reason_code': 'awaiting_state'}


class RequestBudget:
    """Append a reservation before a call; never refund failed/interrupted calls."""
    def __init__(self, limit, logger, prior_request_ids=()):
        self.limit, self.logger = limit, logger
        self.reserved = set(prior_request_ids)
        self.lock = Lock()

    def reserve(self, request):
        with self.lock:
            request_id = request['request_id']
            if request_id in self.reserved:
                raise RuntimeError('request already reserved; refusing duplicate API attempt')
            if len(self.reserved) >= self.limit:
                raise RuntimeError('preregistered API request limit reached')
            self.logger.emit('architecture_call_reserved', request_id=request_id,
                             architecture=request['architecture'])
            self.reserved.add(request_id)


class BudgetedClient:
    def __init__(self, provider, budget):
        if provider.max_attempts != 1:
            raise ValueError('architecture pilot forbids automatic retries')
        self.provider, self.budget = provider, budget
        self.scripted_latency_ms = getattr(provider, 'scripted_latency_ms', None)

    def decide(self, request, instructions=''):
        self.budget.reserve(request)
        return self.provider.decide(request, instructions)

    def decide_batch(self, request, instructions=''):
        return self.decide(request, instructions)


def valid_task_decision(decision, child, episode):
    assert_agent_decision(decision)
    ids = set()
    for action in decision['actions']:
        pid = action['proposal_id']
        if not isinstance(pid, str) or not pid or pid in ids:
            raise ValueError('invalid or duplicate proposal identity')
        ids.add(pid)
        if action['based_on_state_version'] != child['state_version']:
            raise ValueError('action does not use request state version')
        allowed = [t for t in child['available_actions'] if t['tool_name'] in child['allowed_tools']
                   and t['target'] == action['target'] and t['operation'] == action['operation']]
        if len(allowed) != 1:
            raise ValueError('action not authorized for assigned task')
        error = validate_tool_call(episode, child['agent']['agent_id'], child['task']['task_id'], action)
        if error:
            raise ValueError(error)


class ComparisonReleaseProvider:
    """Collect a fresh batch at each release; replay measured per-task offsets.

    A central failure invalidates its whole response. Functional failures only
    invalidate the affected task. Both enter execution as labelled local defers.
    Functional requests run concurrently; late groups are constructed in the
    simulator's current state. Wall-clock collection then becomes virtual events.
    """
    include_evaluation_hints = False
    allowed_execution_policies = {POLICY}

    def __init__(self, arm, provider, unit_id):
        if arm not in ARMS:
            raise ValueError('unknown architecture arm')
        self.arm, self.provider, self.unit_id = arm, provider, unit_id
        self.proposal_architecture = arm
        self.records, self.batches, self.consumed, self.proposal_ids = {}, [], set(), set()
        self.last_latency_ms = 0

    def _run_call(self, request, method, started):
        call_start = perf_counter_ns()
        decision = None
        error = None
        try:
            decision = method(request, INSTRUCTIONS)
        except Exception as exc:
            error = {'phase': 'provider_or_protocol', 'type': type(exc).__name__, 'message': str(exc)[:1000]}
        finished = perf_counter_ns()
        scripted = getattr(self.provider, 'scripted_latency_ms', None)
        return {'request': deepcopy(request), 'raw_decision': decision, 'error': error,
                'call_duration_ms': max(1, round((finished - call_start) / 1e6)),
                'logical_latency_ms': scripted if scripted is not None else max(1, round((finished - started) / 1e6))}

    def _finish_task(self, call, child, episode, proposed):
        record = deepcopy(call)
        error = record['error']
        if error is None:
            try:
                valid_task_decision(proposed, child, episode)
                ids = {a['proposal_id'] for a in proposed['actions']}
                if ids & self.proposal_ids:
                    raise ValueError('proposal identity reused across tasks or batches')
                self.proposal_ids.update(ids)
            except Exception as exc:
                error = {'phase': 'authorization_or_identity', 'type': type(exc).__name__, 'message': str(exc)[:1000]}
        record.update(error=error, decision=deepcopy(proposed) if error is None else failure_defer(),
                      local_failure_placeholder=error is not None)
        self.records[child['task']['task_id']] = record

    def prepare_release_batch(self, episode, at_ms, state, version, instructions=''):
        if any(b['at_ms'] == at_ms for b in self.batches):
            return
        batch = build_batch_request(episode, at_ms, state, version)
        batch['architecture'] = self.arm
        batch['request_id'] = f'{self.unit_id}:{at_ms}:batch'
        children = batch['task_requests']
        for child in children:
            child['architecture'] = 'ScopedServiceProposal'
            child['request_id'] = f'{self.unit_id}:{at_ms}:{child["task"]["task_id"]}'
        # The same exact list is supplied centrally and in every pooled call.
        pooled_views = deepcopy(children)
        started = perf_counter_ns()
        calls = []
        if self.arm == 'central_batch':
            call = self._run_call(batch, self.provider.decide_batch, started)
            if call['error'] is None:
                try:
                    assert_batch_decision(call['raw_decision'], batch, episode)
                    ids = {a['proposal_id'] for e in call['raw_decision']['task_decisions'] for a in e['decision']['actions']}
                    if ids & self.proposal_ids:
                        raise ValueError('proposal identity reused across release batches')
                except Exception as exc:
                    call['error'] = {'phase': 'batch_authorization_or_identity', 'type': type(exc).__name__,
                                     'message': str(exc)[:1000]}
            proposed = {e['task_id']: e['decision'] for e in call['raw_decision']['task_decisions']} if call['error'] is None else {}
            for child in children:
                self._finish_task(call, child, episode, proposed.get(child['task']['task_id']))
            calls.append(call)
        else:
            requests = []
            for child in children:
                request = deepcopy(child)
                if self.arm == 'functional_pooled':
                    request['release_group_views'] = deepcopy(pooled_views)
                request['architecture'] = self.arm
                requests.append(request)
            with ThreadPoolExecutor(max_workers=len(requests)) as pool:
                futures = {pool.submit(self._run_call, r, self.provider.decide, started): child
                           for r, child in zip(requests, children)}
                for future in as_completed(futures):
                    child = futures[future]
                    call = future.result()
                    self._finish_task(call, child, episode, call['raw_decision'])
                    calls.append(call)
        self.batches.append({'at_ms': at_ms, 'state_version': version,
                             'release_group_views': pooled_views, 'calls': calls,
                             'wall_ms': max(1, round((perf_counter_ns() - started) / 1e6))})

    def decide(self, request, instructions=''):
        task_id = request['task']['task_id']
        if task_id not in self.records or task_id in self.consumed:
            raise ValueError('missing or duplicated comparison decision')
        self.consumed.add(task_id)
        self.last_latency_ms = self.records[task_id]['logical_latency_ms']
        return deepcopy(self.records[task_id]['decision'])

    def assert_consumed(self):
        if set(self.records) != self.consumed:
            raise ValueError('unused task records')


class SavedComparisonProvider(ComparisonReleaseProvider):
    """Independent no-API replay and release-state request verification."""
    def __init__(self, row):
        super().__init__(row['arm'], None, row['unit_id'])
        self.records = deepcopy(row['records'])
        self.saved_batches = row['batches']

    def prepare_release_batch(self, episode, at_ms, state, version, instructions=''):
        if any(b['at_ms'] == at_ms for b in self.batches):
            return
        saved = next(b for b in self.saved_batches if b['at_ms'] == at_ms)
        rebuilt = build_batch_request(episode, at_ms, state, version)['task_requests']
        fields = ('episode_id', 'base_episode_id', 'current_time_ms', 'state_version',
                  'state', 'agent', 'task', 'goals', 'constraints', 'allowed_tools',
                  'available_actions', 'pending_proposals')
        if len(rebuilt) != len(saved['release_group_views']):
            raise ValueError('release group changed in independent replay')
        for current, original in zip(rebuilt, saved['release_group_views']):
            if any(current[k] != original[k] for k in fields):
                raise ValueError('saved request did not match replay release state')
        self.batches.append(saved)
