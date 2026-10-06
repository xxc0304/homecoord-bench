"""Static DAG validation. Only actual successful completion fulfills an edge."""
def validate_dependencies(e,policy):
    tasks = {t['task_id']:t for t in e['task_stream']}
    graph = {tid:t.get('depends_on',[]) for tid,t in tasks.items()}
    for tid,deps in graph.items():
        if not isinstance(deps,list) or any(not isinstance(d,str) or d not in tasks or d==tid for d in deps) or len(set(deps))!=len(deps):
            raise ValueError('depends_on must name unique existing predecessor tasks, never self')
    if not any(graph.values()): return {}
    if policy not in {'IndependentMultiAgent','ConstraintCoordinator','DeadlineAwareCoordinator','GateRetryRule'}:
        raise ValueError('dependency v3 policy not supported')
    if e.get('tool_contract_version')!='strict-v1':
        raise ValueError('dependencies require strict-v1 tools')
    if any(k in e.get('simulation',{}) for k in ('released_batch_plan','coordination_compute_profile','released_batch_compute_ms')):
        raise ValueError('dependencies with timed batch/compute plans not yet supported')
    for tid,deps in graph.items():
        if (deps or any(tid in ds for ds in graph.values())) and not tasks[tid].get('required_action'):
            raise ValueError('dependencies currently require a single explicit action')
    visiting,done = set(),set()
    def visit(tid):
        if tid in visiting: raise ValueError('dependency cycle')
        if tid in done: return
        visiting.add(tid)
        for dep in graph[tid]: visit(dep)
        visiting.remove(tid)
        done.add(tid)
    for tid in graph: visit(tid)
    return {tid:list(deps) for tid,deps in graph.items() if deps}
