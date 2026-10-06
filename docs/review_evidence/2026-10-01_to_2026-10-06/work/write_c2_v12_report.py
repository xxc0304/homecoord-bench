import json
from pathlib import Path
O=Path('outputs');R=Path(r'.');a=json.loads((O/'C2_V12_EVENT_AUDIT_20261003.json').read_text(encoding='utf-8'))
def link(label,p,line=None):return f'[{label}]({(R/p).as_posix()+(f":{line}" if line else "")})'
def out(label,p):return f'[{label}]({(O/p).resolve().as_posix()})'
E='homecoord_bench/task_revision/event_simulator_v12.py';C='homecoord_bench/task_revision/room_contract_v12.py';P='homecoord_bench/task_revision/room_environment.py';Q='homecoord_bench/task_revision/room_audit_v12.py'
assert len(a['details'])==32 and not any(d['errors'] for d in a['details'])
rows=[]
for d in a['details']:
    section=d['section'];n=d['episode_id'].removeprefix('C2R12-ROOM-');rule=n.split('-')[-1];r=d['request_recount'];m=d['command_recount'];air='bedroom_air';heat='bedroom_heat'
    if section=='main':
        if r['task_disposition'][air]=='satisfied_without_actuation':why='300ms合法保持关窗；air处置成功，但开窗命令false/null/按时false。'
        else:why='真实开窗回执2400ms才计命令完成；供暖等待与真实回执符合当前准入规则。'
    elif section=='unnecessary_open':why='低CO₂错误开窗被ventilation_not_needed拒绝；air准入/处置/命令均false，虽环境达标也不反推提议正确。'
    elif section=='unhandled_high_co2':why='高CO₂无动作不满足需求，air未决false/null；等待臂供暖准入true但无处置/命令终态。两臂环境未完成null。'
    elif section=='exact_threshold':why='900ppm包括在已满足范围；air合法无动作终态，命令false/null。'
    else:why='901ppm必须通风，真实开窗2400ms，3000ms请求闭窗、6000ms实际关闭。'
    g=d['first_environment_goal_ms'];late=d['environment_tardiness_ms']
    why+=f' 环境首次观察达标 {g if g is not None else "null"}ms，迟到 {late if late is not None else "null"}ms；heat命令自发布时延 {m["task_completion_latency_ms"][heat] if m["task_completion_latency_ms"][heat] is not None else "null"}ms。'
    refs='；'.join(f"e{x['index']} {x['type']}({x.get('task_id','controller')})@{x['timestamp_ms']}" for x in d['events'] if x['type'] in ('request_satisfied_without_actuation','request_disposition_unresolved','action_rejected','action_started','action_completed','environment_admission_waiting','automatic_window_close_requested') or x['type']=='state_update' and x.get('source')=='automatic_window_close')
    if g is not None:refs+=f"；环境首达e{d['first_environment_goal_event_index']}@{g}"
    label=n if section=='main' else section+'/'+rule
    rows.append(f"| `{label}` | 接受／符合设计 | {why} | 本次提交范围内无阻断性缺失。 | 已满足分层计分与共同成本；通过不代表环境按时。 | {link('保存材料',d['file'])}；{refs}；统一代码定位见下。 |")
main=[d for d in a['details'] if d['section']=='main'];late_count=sum(d['environment_tardiness_ms']>0 for d in main)
text=f'''# C2 v12 设计与实现复审

2026-10-03。审查者：本会话 Codex。先读设计卡及24主/8诊断输入，保存{out('设计结论','C2_V12_DESIGN_REVIEW_20261003.md')}，再查看实现包、代码与成绩。本轮不沿用其他任务族验收。

**设计：接受，限定为未校准合成环境任务。实现：24条主回放及8条诊断在提交范围内符合设计，未发现阻断性执行或计分错误。** 32条完整轨迹解码、真实调用复现与独立重算一致；其中{late_count}条主运行环境迟到、2条高CO₂无动作诊断环境未完成，均如实计分。本结论是单模型复审，不是独立双审或策略优劣评比。

## 设计与评分合同

空气请求允许CO₂≤900ppm且窗关闭时合法保持关窗；无未来等待时刻的defer或noop可成为satisfied_without_actuation，但不生成开窗命令完成。高CO₂需要通风；低CO₂错误开窗被拒绝，即使环境后来达标，该错误提议也不自动成为正确处置。供暖请求仍要求授权命令，不扩展已达温度跳过政策。

接受准入、处置终态、命令回执、环境首次观察联合达标四层指标。供暖合法等待可以准入true、终态/命令false；开窗命令完成可以处置true、环境仍未达标。新命令截止360000ms与环境期限同刻，不混淆两种完成时延。旧task_service等字段保留命令兼容含义，不作为需求或环境服务成功率。

12参数世界两臂的完整权限/成本合同只改变heat_admission；SyntheticResident委托闭窗和理想恒温是共同可信控制底座。3000ms闭窗确认真实计入交换与等待。额外闭窗/开关/规则计算费用为零，明确仅是合成假设；连续2kW供暖按等效开启时间积分，不按零能耗命令重复收费。开窗供暖允许，是软代价，不能直接叫硬违规或把其能量都称浪费。

参数未校准；本轮没有验证物理真实性或现实合理参数范围。统一360000ms期限与900000ms观察终点，首次观察达标后仍继续积分；不提供持续满足时长。完整设计参数及配对核验见{out('设计检查','C2_V12_DESIGN_CHECKS_20261003.json')}。

## 实现定位与关键证据

{link('需求与共同权限校验',C,10)}固定明确合同；{link('公共请求构造',C,23)}保留公开需求阈值和静态工具成本，隐藏配置身份/模板评估字段。32次运行逐调用按发布时间状态和版本重建完整请求，与trace和calls一致；12主世界及4诊断规则配对的完整calls共16对相同，32个私有字段扰动探针也一致。公开任务文本在全部输入中已逐项审过，不靠搜索某个时间数字判断泄露。

{link('拒绝不必要通风',E,598)}和{link('合法无动作终态',E,1065)}分开记录处置。合法skip不含预约、启动或完成；{link('处置指标',C,33)}与逐命令匹配真实开始/完成的重计保持分层。{link('环境tick和闭窗确认',E,913)}记录请求与3000ms后的真实关闭，供暖等待到CO₂达标且闭窗确认之后才开始。

例：850ppm默认参数air300ms处置成功，命令false/null/按时false；heat1500ms完成（自100ms发布时延1400ms），环境162000ms首次达标。1600ppm默认立即供暖环境340000ms达标，等待供暖572000ms达标、迟到212000ms；两种规则的命令均可在截止前完成，不把它们都记环境按时。

900ppm合法skip；901ppm必须开窗，2400ms命令完成、3000ms第一次tick观察CO₂达标请求关闭、6000ms实际关闭。高CO₂always_skip立即臂heat命令完成但环境null；等待臂heat只有合法准入等待，处置/命令/环境皆未完成。低CO₂always_open被拒绝而环境仍可达标，处置仍false。这些诊断未混入24主运行分母。

独立物理核对没有调用生产evolve或作者room_audit作为判据：从每段真实actuator状态求ODE温度端点，按目标到达时刻分段，以8小段Simpson积分温度，再由热平衡求等效供暖时长/能量；CO₂超额按线性面积重算。共28,972区间的端点、供暖能量、开窗供暖量、换热损失、温度/CO₂偏离积分与应用状态一致，最大数值绝对差约6.2×10⁻¹²。共同期限快照、终点总积分、闭窗确认、首次观察目标/迟到/null独立核对通过。

## 已填写逐配置复审表

全部仅ConstraintCoordinator＋公开确定性工具脚本，比较两种共享供暖准入规则。下标为解码完整trace.events的零基位置，可读导航没有另行重编号。统一代码位置：598/1065（需求准入与skip）、620（供暖等待）、913/924（闭窗请求/确认）、1461（处置计分）、room_environment（未校准动力学）。详细逐事件与积分证据见{out('独立审计','C2_V12_EVENT_AUDIT_20261003.json')}。

| 配置／诊断 | 设计／实现 | 理由 | 缺失证据 | 通过条件 | 事件／代码 |
|---|---|---|---|---|---|
{chr(10).join(rows)}

## 复现、负例与冻结

32个zlib/base64轨迹独立解码并验证原始文本SHA256、全部环境事件及导航事件一致；不是抽样审计。32条真实运行trace/result/calls/audit完整复现。24主运行environment报告与冻结v4执行逐字段一致，35个v12材料对象和旧v4包重新生成一致。{len(a['hash_checks'])}项指定文件/引用哈希核验无差异，含之前独立审计保留的Phase B、C4 v9/v10及依赖v11摘要及声明材料；不是无关全仓库文件的普遍冻结证明。

额外8个入口负例在任何调用前拒绝不一致权限费用、闭窗延迟、tick、混合生命周期、future hook、instructions、未支持策略和关闭安全门。4个伪造高CO₂skip/低CO₂命令成功负例被作者与本审核独立重建均拒绝。本审核另外实际执行4条noop／未来defer诊断：低CO₂noop合法终态；设置未来defer_until_ms不成为合法skip终态；均不伪造开窗完成。这4条是审核者补充探针，不冒称作者已提交诊断。

实际运行 `python -m unittest homecoord_bench.tests.test_room_v12 -v`，12专项全部通过；本轮未重跑作者声明全套500项。没有模型/API、保留实验、上传或修改研究仓库。审核脚本：{out('独立处置和物理重算','../work/audit_c2_v12.py')}。

范围仅限已提交合成单室合同、v12显式入口、ConstraintCoordinator和两种共同底座规则，不批准真实家庭、实机节能因果、参数校准、持续满足、四策略一般性或LLM/第二Agent必需。尚未提交的跨配置排名/汇总不在本轮验收中。本轮设计与实现可结束复审。
'''
(O/'C2_V12_REVIEW_20261003.md').write_text(text,encoding='utf-8')
print(json.dumps({'configurations':24,'diagnostics':8,'main_environment_late':late_count,'blocking_findings':0,'report':str((O/'C2_V12_REVIEW_20261003.md').resolve())},ensure_ascii=False))
