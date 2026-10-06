import json,copy
from pathlib import Path
R=Path(r'.');B=R/'homecoord_bench/task_revision/fixtures/room_v12';O=Path('outputs')
j=json.loads((B/'inputs.json').read_text(encoding='utf-8'));errors=[];pairs=[]
def ck(x,s):
    if not x:errors.append(s)
for e in j['episodes']+[x['episode'] for x in j['diagnostics']]:
    n=e['episode_id'];p=e['simulation']['environment'];ts=e['task_stream'];gs=e['action_grounding'];s=e['initial_state']['values'];a=e['controller_authority']
    ck(e['c2_revision']=='v12-demand-disposition' and e['simulation']['command_latency_ms']==100,n+' version/command')
    ck(s['bedroom']['temperature_c']==17 and s['devices']=={'window':'closed','heater':'off'},n+' initial')
    ck(ts[0]['release_at_ms']==0 and ts[1]['release_at_ms']==100 and all(t['completion_deadline_ms']==360000 for t in ts),n+' releases/deadlines')
    ck(ts[0]['demand_rule']=={'path':'bedroom.co2_ppm','threshold_ppm':900,'satisfied_action':'keep_window_closed','unsatisfied_action':'ventilate_then_trusted_close'},n+' demand')
    ck(a['principal']=='SyntheticResident' and a['automatic_window_close']=={'sensor_tick_ms':1000,'co2_threshold_ppm':900,'confirmation_delay_ms':3000,'command_energy_wh':0} and a['thermostat']=={'kind':'ideal_target_clamp','heater_power_kw':2,'target_temp_c':21,'switching_cost_wh':0} and a['heating_admission']=={'owner':'shared_trusted_controller','rules':['immediate','after_ventilation'],'extra_compute_ms':0},n+' common authority')
    ck(all(p[k]==v for k,v in {'tick_ms':1000,'deadline_ms':360000,'horizon_ms':900000,'close_delay_ms':3000,'outdoor_temp_c':8,'target_temp_c':21,'target_co2_ppm':900,'co2_floor_ppm':420,'exchange_per_s':0.0015,'heater_power_kw':2}.items()),n+' environment')
    ck(p['ventilation_rate_ppm_s'] in (2.5,5) and p['heat_rate_c_per_s'] in (0.015,0.025,0.035) and not e['exogenous_events'],n+' rates/no future event')
    ck(gs[0]['duration_ms']==2000 and gs[1]['duration_ms']==1000 and all(g['power_kw']==0 for g in gs),n+' grounded costs')
    for t in ts:
        agent=next(z for z in e['agents'] if z['agent_id']==t['agent_id']);tool=next(z for z in e['tool_catalog'] if z['agent_id']==t['agent_id']);g=next(z for z in gs if z['task_id']==t['task_id'])
        ck(tool['tool_name'] in agent['tools'] and 'devices.'+g['target'] in agent['writable_resources'] and tool['cost_contract']=={'duration_ms':g['duration_ms'],'resource_units':0},n+t['task_id']+' permissions/cost')
    ck(e['tool_catalog'][0]['preconditions']==[{'path':'bedroom.co2_ppm','op':'gt','value':900}],n+' opening needed threshold')
for x,y in zip(j['episodes'][::2],j['episodes'][1::2]):
    x=copy.deepcopy(x);y=copy.deepcopy(y);id=x['episode_id'];x.pop('episode_id');y.pop('episode_id');x['simulation']['environment'].pop('heat_admission');y['simulation']['environment'].pop('heat_admission');pairs.append({'world':id.rsplit('-',1)[0],'only_heat_admission_differs':x==y});ck(x==y,id+' paired contract')
out={'main':24,'diagnostics':8,'errors':errors,'pairs':pairs,'design':'接受' if not errors else '修改'}
(O/'C2_V12_DESIGN_CHECKS_20261003.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
assert not errors,errors
(O/'C2_V12_DESIGN_REVIEW_20261003.md').write_text('''# C2 v12 设计复审（先于成绩）

2026-10-03。本阶段仅读取设计卡与全部输入，未读保存策略成绩。设计：接受，作为未校准合成环境任务。

需求明确：CO₂≤900且窗关闭可合法保持关窗，处置终态成功而开窗命令false/null；高CO₂需实际通风。准入、处置、命令、环境首次观察达标和积分分开，不能用环境最终达标洗掉错误提议，也不能用命令回执冒充环境服务。

两供暖规则具相同合成住户委托、闭窗/理想恒温能力及成本，输入参数配对只改变heat_admission。接受命令能量与闭窗/开关额外成本0、规则计算时间0为显式合成假设；供暖按等效开启时间积分，不重复按命令计能耗。开窗供暖允许，属于代价/时延权衡，不是硬违规。

24主输入和8诊断的完整初态、需求、权限、成本、期限、共同900000ms终点与12世界配对核验通过。诊断单列；迟到和未完成保留。未批准真实物理范围、真实节能因果、持续满足时长或LLM/多Agent必要。实现尚待真实轨迹、数值积分和评分核查；通过条件为符合本合同。缺失证据为本阶段尚未审的实现。
''',encoding='utf-8')
print(json.dumps(out,ensure_ascii=False,indent=2))
