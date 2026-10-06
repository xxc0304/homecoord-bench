"""F3-only frozen-event aggregation. No simulation, API, or legacy delta reuse."""
import hashlib
import json
from pathlib import Path
from homecoord_bench.task_revision.aggregation_contract_v2 import ROOT, OUT, service_rate_boundary

FREEZE=OUT+'/freeze_20261004.json'
PREFIX='homecoord_bench/task_revision/fixtures/f3_v8/'

class EvidenceError(ValueError):
    pass

def require(condition, message):
    if not condition: raise EvidenceError(message)

def load(path, root=ROOT):
    try: return json.loads((root/path).read_text(encoding='utf-8'))
    except (OSError, ValueError) as e: raise EvidenceError(str(e)) from e

def verify_hash(path, expected, root=ROOT):
    try: actual=hashlib.sha256((root/path).read_bytes()).hexdigest()
    except OSError as e: raise EvidenceError(str(e)) from e
    require(actual==expected, 'hash mismatch: '+path)

def value(v, status='ok', **coverage):
    return {'value':v,'status':status,**coverage}

def recount(episode, run):
    """Required set comes from contract, never from an admission or result field."""
    tasks={t['task_id']:t for t in episode['task_stream']}
    require(len(tasks)==len(episode['task_stream']), 'duplicate task')
    allowed=episode['mode_capability']['authorized_modes_by_task']
    events=run['trace']['events']; active={}; commitments={}; starts={}; done={}; modes={}; intervals=[]
    released=set(); last=-1
    for i,x in enumerate(events):
        now=x['timestamp_ms']; tid=x.get('task_id'); kind=x['type']
        require(type(now) is int and now>=last, 'nonmonotonic event'); last=now
        if kind=='task_released':
            require(tid in tasks and tid not in released and now==tasks[tid]['release_at_ms'],'release mismatch')
            released.add(tid)
        if kind=='mode_selection_committed':
            require(tid in tasks and tid not in commitments and x['operation'] in allowed[tid], 'invalid commitment')
            commitments[tid]=x
        if kind=='action_started':
            require(tid in released and now>=tasks[tid]['release_at_ms'], 'unreleased start')
            pid=x['proposal_id']; operation=x['operation']
            require(pid not in active, 'duplicate start')
            matches=[g for g in episode['action_grounding'] if g['task_id']==tid and g['operation']==operation]
            require(len(matches)==1,'unknown action'); g=matches[0]
            require(all(x[k]==g[k] for k in ('target','duration_ms','power_kw','start_effects','completion_effects')), 'grounding mismatch')
            require(sum(a['power_kw'] for a,_ in active.values())+x['power_kw']<=episode['home']['resources']['max_power_kw'], 'over capacity')
            if operation!='off':
                require(operation in allowed[tid] and tid not in starts, 'unauthorized or repeated service')
                c=commitments.get(tid)
                require(c is not None and c['proposal_id']==pid and c['operation']==operation and c['timestamp_ms']<now,'missing commitment')
                starts[tid]={'at_ms':now,'event_index':i}; modes[tid]=operation
            active[pid]=(x,i)
        if kind=='action_completed':
            pid=x['proposal_id']; require(pid in active,'unmatched completion'); s,si=active.pop(pid)
            require(all(x[k]==s[k] for k in ('task_id','target','operation')), 'receipt identity mismatch')
            require(now==s['timestamp_ms']+s['duration_ms'] and x['effects']==s['completion_effects'],'receipt effects/time mismatch')
            intervals.append({'task_id':tid,'operation':s['operation'],'start_event_index':si,'end_event_index':i,
                              'start_ms':s['timestamp_ms'],'end_ms':now,'units':s['power_kw']})
            if x['operation']!='off':
                require(tid not in done,'duplicate completion'); done[tid]={'at_ms':now,'event_index':i}
    require(released==set(tasks) and not active,'missing release or incomplete physical trace')
    on_time={tid for tid,d in done.items() if d['at_ms']<=tasks[tid]['completion_deadline_ms']}
    metrics={}; reported={k:{} for k in ('task_correct_action_completed','task_start_wait_ms','task_completion_latency_ms','task_completion_tardiness_ms','task_deadline_met')}
    for tid,t in tasks.items():
        wait=starts[tid]['at_ms']-t['release_at_ms'] if tid in starts else None
        latency=done[tid]['at_ms']-t['release_at_ms'] if tid in done else None
        tardy=max(0,done[tid]['at_ms']-t['completion_deadline_ms']) if tid in done else None
        coverage={'required':1,'started':int(tid in starts),'completed':int(tid in done)}
        metrics[tid]={'wait_ms':value(wait,'ok' if wait is not None else 'not_started',**coverage),
                      'latency_ms':value(latency,'ok' if latency is not None else 'not_completed',**coverage),
                      'tardiness_ms':value(tardy,'ok' if tardy is not None else 'not_completed',**coverage)}
        for k,v in zip(reported,(tid in done,wait,latency,tardy,tid in on_time)):reported[k][tid]=v
    require(all(run['result'][k]==v for k,v in reported.items()),'stored result differs from events')
    coverage={'required':len(tasks),'started':len(starts),'completed':len(done),'on_time':len(on_time)}
    rates=service_rate_boundary(len(tasks),len(done),len(on_time))
    for r in rates.values():r['started']=len(starts)
    return {'required_ids':list(tasks),'started':starts,'completed':done,'on_time_ids':sorted(on_time),
            'coverage':coverage,'rates':rates,'tasks':metrics,'actual_modes':modes,'resource_intervals':intervals,
            'cost':value(sum(x['units']*(x['end_ms']-x['start_ms']) for x in intervals),**coverage),
            'all_service_completion_ms':value(max((x['at_ms'] for x in done.values()),default=None) if len(done)==len(tasks) and tasks else None,
                'ok' if tasks and len(done)==len(tasks) else ('not_completed' if tasks else 'no_eligible_requests'),**coverage)}

def delta(a,b, missing_status):
    return value(a['value']-b['value']) if a['value'] is not None and b['value'] is not None else value(None,missing_status)

def compare(plan,a,b):
    require(set(a['required_ids'])==set(b['required_ids']),'pair E mismatch')
    complete_vector=len(a['actual_modes'])==len(a['required_ids']) and len(b['actual_modes'])==len(b['required_ids'])
    mechanism=plan['contrast_type']=='mode_matched_control'
    qualified=not mechanism or (complete_vector and a['actual_modes']==b['actual_modes'])
    status='ok' if qualified else 'incomplete_actual_vector'
    require(not mechanism or not complete_vector or a['actual_modes']==b['actual_modes'],'mode control mismatch')
    rates={k:delta(a['rates'][k],b['rates'][k],'no_completed_requests') for k in a['rates']}
    if not qualified: rates={k:value(None,status) for k in rates}
    both_complete=a['coverage']['completed']==a['coverage']['required'] and b['coverage']['completed']==b['coverage']['required']
    result={'contrast_type':plan['contrast_type'],'candidate':plan['candidate'],'control':plan['control'],
            'world':plan['world'],'qualification':status,'candidate_coverage':a['coverage'],'control_coverage':b['coverage'],
            'rate_deltas':rates,'all_service_completion_delta':delta(a['all_service_completion_ms'],b['all_service_completion_ms'],'not_completed'),
            'observed_cost_delta':delta(a['cost'],b['cost'],'evidence_error'),
            'matched_service_cost_saving':value(b['cost']['value']-a['cost']['value']) if both_complete else value(None,'unequal_service_coverage'),
            'directions':{'default':'candidate_minus_control','matched_service_cost_saving':'control_minus_candidate'},
            'task_deltas':{tid:{k:delta(a['tasks'][tid][k],b['tasks'][tid][k],'not_started' if k=='wait_ms' else 'not_completed') for k in a['tasks'][tid]} for tid in a['required_ids']}}
    if not qualified:
        for key in ('all_service_completion_delta','observed_cost_delta','matched_service_cost_saving'):result[key]=value(None,status)
        for fields in result['task_deltas'].values():
            for k in fields:fields[k]=value(None,status)
    return result

def four_cell(fields):
    require(set(fields)=={'Y00','Y10','Y01','Y11'},'missing factorial cell')
    if any(x['value'] is None for x in fields.values()):return {k:value(None,'not_completed') for k in ('S','M','I','T')}
    a,b,c,d=(fields[k]['value'] for k in ('Y00','Y10','Y01','Y11'))
    return {k:value(v) for k,v in zip(('S','M','I','T'),(b-a,c-a,d-b-c+a,d-a))}

def aggregate(root=ROOT):
    root=Path(root); freeze=load(FREEZE,root)
    for p,h in freeze['sha256'].items():verify_hash(p,h,root)
    manifest=load(PREFIX+'manifest.json',root)
    for field in ('source_sha256','artifact_sha256'):
        for p,h in manifest[field].items():verify_hash(p,h,root)
    inventory=load(OUT+'/run_inventory.json',root)['slots']; plan=load(OUT+'/pair_plan.json',root)
    episodes={e['episode_id']:e for e in load(PREFIX+'inputs.json',root)['episodes']}
    cache={}; runs={}; identities={}
    for slot in inventory:
        sid=slot['canonical_slot_id'];require(sid not in runs,'duplicate slot')
        p=slot['source_path'];verify_hash(p,slot['source_sha256'],root)
        if p not in cache:cache[p]=load(p,root)
        bits=slot['source_row_pointer'].split('/');require(bits[:2]==['','runs'],'bad row pointer')
        try:r=cache[p]['runs'][int(bits[2])]
        except (KeyError,IndexError,ValueError) as e:raise EvidenceError('missing row') from e
        require((r['evaluation_episode_id'],r['policy'],r['selector'],r['diagnostic'])==(slot['config_id'],slot['policy'],slot['selector'],slot['diagnostic_id']),'identity mismatch')
        e=episodes[slot['config_id']]
        require(slot['requests']==[{'task_id':t['task_id'],'release_at_ms':t['release_at_ms'],'deadline_ms':t['completion_deadline_ms']} for t in e['task_stream']], 'request contract mismatch')
        require(slot['authorized_modes_by_task']==e['mode_capability']['authorized_modes_by_task'],'permission mismatch')
        runs[sid]={'identity':slot,**recount(e,r)};identities[sid]=slot
    pairs=[]
    for i,p in enumerate(plan['pairs']):
        require(p['candidate'] in runs and p['control'] in runs,'missing pair arm')
        a,b=(runs[p[k]] for k in ('candidate','control'))
        require(a['identity']['role']==b['identity']['role']=='primary','diagnostic in main pair')
        require(a['identity']['base_world_id']==b['identity']['base_world_id']==p['world'],'world mismatch')
        if p['contrast_type']=='fixed_mode_scheduling':require(a['identity']['authorized_modes_by_task']==b['identity']['authorized_modes_by_task'],'fixed authorization mismatch')
        if p['contrast_type']=='selectable_selector':require(a['identity']['policy']==b['identity']['policy'] and a['identity']['authorized_modes_by_task']==b['identity']['authorized_modes_by_task'],'selector contract mismatch')
        pairs.append({'pair_index':i,**compare(p,a,b)})
    factors=[]
    for f in plan['factorial_cells']:
        require(all(f[k] in runs for k in ('Y00','Y10','Y01','Y11')),'missing factorial run')
        cells={k:runs[f[k]] for k in ('Y00','Y10','Y01','Y11')}
        require(all(r['identity']['role']=='primary' and r['identity']['base_world_id']==f['world'] for r in cells.values()),'factor identity mismatch')
        fields={metric:{k:(r['rates'][metric] if metric in r['rates'] else r[metric]) for k,r in cells.items()} for metric in ('timely_service_rate','service_completion_rate','all_service_completion_ms','cost')}
        factors.append({'plan':f,'cells':fields,'decomposition':{metric:four_cell(v) for metric,v in fields.items()},'cost_interpretation':'observed_cost_algebra_not_savings'})
    # One predefined vector per world, one policy arm. Selectors are not extra worlds.
    primary=[f for f in factors if f['plan']['role']=='primary']; require(len(primary)==8,'world count mismatch')
    summary={}
    for metric in ('timely_service_rate','service_completion_rate','all_service_completion_ms','cost'):
        summary[metric]={}
        for component in ('S','M','I','T'):
            vals=[f['decomposition'][metric][component]['value'] for f in primary]
            n=sum(v is not None for v in vals)
            summary[metric][component]=value(sum(vals)/8 if n==8 else None,'ok' if n==8 else 'not_completed',valid_worlds=n,required_worlds=8,weight_per_world=1/8)
    cell_rate_summary={}
    for cell in ('Y00','Y10','Y01','Y11'):
        rows=[runs[f['plan'][cell]] for f in primary]
        denominator=sum(r['coverage']['required'] for r in rows)
        cell_rate_summary[cell]={}
        for metric,count in (('service_completion_rate','completed'),('timely_service_rate','on_time')):
            numerator=sum(r['coverage'][count] for r in rows)
            vals=[r['rates'][metric]['value'] for r in rows]
            cell_rate_summary[cell][metric]={'pooled_request_rate':value(numerator/denominator if denominator else None,'ok' if denominator else 'no_eligible_requests',numerator=numerator,denominator=denominator),
                'equal_world_mean_rate':value(sum(vals)/8 if all(v is not None for v in vals) else None,'ok' if all(v is not None for v in vals) else 'no_eligible_requests',required_worlds=8,weight_per_world=1/8)}
    return {'status':'author_implementation_pending_review','scope':'F3_v8_only','adapter_acceptance':None,
            'runs':runs,'pairs':pairs,'factorial':factors,'equal_world_factorial_summary':summary,
            'predefined_primary_four_cell_rate_summary':cell_rate_summary,
            'diagnostics_in_primary_denominator':False,'api_calls':0,'holdout_runs':0,'rankings':None}

def artifacts():
    data=aggregate(); base='docs/f3_aggregation_v1_20261004/'
    result={base+'summary.json':{k:v for k,v in data.items() if k not in ('runs','pairs','factorial')}}
    worlds=sorted({r['identity']['base_world_id'] for r in data['runs'].values()})
    for world in worlds:
        result[base+world+'.json']={'world':world,'status':data['status'],
            'runs':{k:r for k,r in data['runs'].items() if r['identity']['base_world_id']==world},
            'pairs':[p for p in data['pairs'] if p['world']==world],
            'factorial':[f for f in data['factorial'] if f['plan']['world']==world]}
    return result

if __name__=='__main__':
    import sys
    data=aggregate()
    if len(sys.argv)>1:data=data[sys.argv[1]]
    print(json.dumps(data,ensure_ascii=False,indent=2))
