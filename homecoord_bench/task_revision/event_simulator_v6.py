"""C1 v6 public-identity boundary over the frozen v5 execution engine.

No module globals are patched. Private experiment IDs remain in the evaluator's
outer record; the engine and provider receive only a scene identity. Providers
with episode-level preparation hooks are rejected: those hooks bypass the
request-only information boundary and expose future arrivals.
"""
from copy import deepcopy
from homecoord_bench.task_revision.event_simulator_v5 import run_event_simulation as frozen_v5


def run_event_simulation(episode, decision_provider, *args, **kwargs):
    if not episode.get('simulation', {}).get('request_disposition_contracts'):
        return frozen_v5(episode, decision_provider, *args, **kwargs)
    if getattr(decision_provider, 'prepare_release_batch', None) is not None:
        raise ValueError('C1 v6 permits request-only providers, not episode preparation hooks')
    public = deepcopy(episode)
    # This is an explicit scene mapping, not a hash of a condition-dependent ID.
    target = public['user_delegations'][0]['target']
    scene = {'study_light': 'HC-M02', 'bedroom_blinds': 'HC-M03'}[target]
    public['episode_id'] = public['base_episode_id'] = scene
    for key in ('variant', 'review_status', 'task_card'):
        public.pop(key, None)
    trace, result = frozen_v5(public, decision_provider, *args, **kwargs)
    result['request_disposition_version'] = 'C1-v6-public-identity-separate-admission'
    return trace, result
