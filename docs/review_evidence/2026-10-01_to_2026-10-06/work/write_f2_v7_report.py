import json
from pathlib import Path
O=Path('outputs');a=json.loads((O/'F2_V7_EVENT_AUDIT_20261002.json').read_text(encoding='utf-8'));p=json.loads((O/'F2_V7_RUNTIME_PROBES_20261002.json').read_text(encoding='utf-8'));R='.';B='homecoord_bench/task_revision/fixtures/f2_v7';eng='homecoord_bench/task_revision/event_simulator_v7.py';info='homecoord_bench/task_revision/f2_information.py'
def link(label,path,line=None):return f'[{label}]({R}/{path}'+(f':{line}' if line else '')+')'
def local(label,name):return f'[{label}]('+str((O/name).resolve()).replace('\\','/')+')'
text='''# F2 v7 设计／实现复审表（2026-10-02）

总体结论：**设计接受；8配置实现均“符合设计”**。本轮未发现提交范围内的未来信息泄露、提前执行、容量违规、伪完成或服务计分错误。所有未完成和迟到仍按原服务合同保留。

审查者：本聊天 Codex 单模型；另于作者 audit 独立重建状态、资源区间和服务指标。不是人类审查，未完成独立双审。第一阶段仅读取设计说明、8输入、8份离线证书及白名单源码，设计结论保存后才读取运行成绩；第二阶段看结果用于事件/评分核验，不评方法优劣。

范围：两个原开发实例的8配置，32主回放及48反事实回放；接受显式 v7 入口及其四策略白名单。不重新验收其他任务族。所有 JSON 数组下标从0开始；主文件 runs[0..3] 固定为 P0=IndependentMultiAgent、P1=ConstraintCoordinator、P2=DeadlineAwareCoordinator、P3=GateRetryRule。eN 表示该 run 的 trace.events[N]，qN 表示 calls[N].request，同时核对 trace.agent_requests[N]。

## 设计判断与代码定位

'''
text+=f'''设计独立记录：{local('先于成绩保存的设计结论','F2_V7_DESIGN_REVIEW_20261002.md')}，{local('逐参数/配对/离线证书核对','F2_V7_DESIGN_CHECKS_20261002.json')}。

静态设备清单允许知道 water 设备及成本，不宣称本次 water 请求一定出现。只把已到发布时间的任务列入请求/目标，且同刻发布按原子批次公开。四方法获得同类信息；动作分歧后不要求自身设备状态相同。任务规范化仍保留服务、deadline、权限及完整非抢占周期。

SyntheticResident 的不可取消/抢占/改模式委托明示；off仅在idle有效且不提供服务。接受为合成抽象合同。晚到由预设外源时刻产生，未声明经验到达概率；不能以设备存在推断未来请求必然出现。容量配对保留同一服务成本；晚到配对同时平移water发布和deadline，保持自发布服务时限。

8份构造排程逐项验证任务覆盖、成本、完整时长、release+2100ms、截止及半开容量区间，均成立。它只证明合同至少可行，不是在线最优基线，也不证明本次某个超期本可避免。

- A：{link('f2_information.py',info,7)} 限定四在线策略、共同安全门、空 instructions、无准备hook及额外simulation/constraints；第24–42行限制静态字段与实际成本一致。
- B：{link('规范化任务',info,45)} 与 {link('完整白名单 builder',info,52)} 重新构建输入；第58行按 release<=now 生成请求，第75–88行重建公开身份、自身状态、公共context、已发布goals和空pending。不使用原自由文本或原context。
- C：{link('执行前校验',eng,321)}；{link('真实发布与调用',eng,791)} 第799行使用builder、第813行保存请求并实际调用provider。调用对象不是事后清洗的trace。
- D：{link('EDF仅等待已发布提案',eng,596)}；第622–630行仅对pending中的已发布返回提案排序。{link('oracle分支',eng,665)} 仅可由被A拒绝的策略调用；预置批次计划也被A拒绝。
- E：{link('启动复核与共同容量门',eng,909)}，第931行安全门，{link('真实完成回执',eng,1039)}。成本/效果来自本次已发布任务的授权grounding。
- F：{link('生产服务响应指标','homecoord_bench/runtime/task_response_metrics.py',10)} 按匹配启动/完成和自身发布时间计算等待、时延及迟到；{link('评分整合',eng,1153)}；作者recount另见 {link('f2_revision.py','homecoord_bench/task_revision/f2_revision.py',59)}，本轮未以其通过标记作为验收依据。

## 逐配置填写

下表每行覆盖该主文件的全部 runs[0..3]；准确事件位置另列于后表。当前声明范围内无待补实现证据，设计通过条件及实现通过条件均已满足。

| 配置后缀（统一F2R1-D-F2-前缀） | 设计：结论／理由／缺失证据／通过条件 | 实现：结论／理由／缺失证据／通过条件 | 请求与代码位置 |
| --- | --- | --- | --- |
'''
for group in range(8):
    d=a['details'][group*4];suffix=d['episode_id'].replace('F2R1-D-F2-','');late=suffix.endswith('-late');cap=d['capacity'];filename=d['file']
    design='接受；静态能力与未来需求分开，非抢占委托、原子发布和配对时限明确。无本次设计待补项；参数及可行证书条件满足。'
    impl=f'符合设计；四策略输入逐字段满足白名单，运行峰值≤{cap}，真实回执与独立评分相符。无本次实现待补项；通过条件满足。'
    if late:where='q0–q2仅早期3请求，q3才为water；12项反事实前缀一致（A–F）。'
    else:where='q0–q3均在0ms，四次均看见完整4请求原子批次（A–F）。'
    text+=f'| `{suffix}` | {design} | {impl} | {link("主文件",filename)} runs[0..3]；{where} |\n'
text+='''
## 32 主回放逐条事件与计分

本表是评分证据定位，不是方法优劣排序。启动→完成列同时给出事件下标和真实毫秒区间；每个区间均持续完整声明时长。未完成任务的完成=false、时延/迟到=null、按时=false；迟到完成的完成=true、时延为自身发布后真实耗时、按时=false。容量拒绝保持为服务未完成，不能算作服务成功。排队且按时完成仍算成功。

| 配置／run策略 | 实际请求／发布位置 | 启动→完成事件与区间ms；拒绝证据 | 资源峰值；未完成与迟到重算 | 结论 |
| --- | --- | --- | --- | --- |
'''
for d in a['details'][:32]:
    suffix=d['episode_id'].replace('F2R1-D-F2-','');i=d['run_index'];release=', '.join(f'{tid}:q{j}/e{d["release_event_indices"][tid]}' for j,tid in enumerate(d['call_task_ids']))
    intervals='；'.join(f'{x["task_id"]}:e{x["start_event"]}→e{x["end_event"]} [{x["start_ms"]},{x["end_ms"]})' for x in d['intervals'])
    rej=[x for x in d['events'] if x['type']=='action_rejected']
    if rej:intervals+='；拒绝 '+', '.join(f'{x["task_id"]} e{x["index"]}/{x["time_ms"]}({x["reason"]})' for x in rej)
    m=d['computed'];unfinished=[tid for tid,v in m['task_correct_action_completed'].items() if not v];late={tid:v for tid,v in m['task_completion_tardiness_ms'].items() if v};res=f'{d["peak_units"]}/{d["capacity"]}；未完成 '+(','.join(unfinished) if unfinished else '无')+'；迟到 '+(', '.join(f'{tid}={v}ms' for tid,v in late.items()) if late else '无')
    text+=f'| {suffix} / P{i} | {release} | {intervals} | {res} | 符合设计（C–F） |\n'
text+='''
全部32条均无发布前调用/启动、运行超容量、周期截断或无匹配启动的完成。半开区间使同刻完成释放资源后可合法启动下一负载；状态更新和真实完成回执的版本逐次核对。主体、目标、操作与实际provider提案匹配，成本/效果与工具、模板和grounding一致。

例：01-competition-simultaneous/P2 的 cleaning 在 e22/120400ms 才启动、e26/480400ms 完成，合法排队且按时；01-competition-late/P0 的 water 在 e22/60400ms 被容量门拒绝，未记完成；02-competition-late/P3 的 water 在 e32/420500ms 完成，相对420000ms截止迟到500ms，未被抹成按时。这些差异均按合同计分，不据此判断任何损失不可避免或某方法更好。

## 全部48对反事实

每个晚到配置×三个未来变化×四策略。从主文件与诊断原始文件重建完整calls（含request和decision）及events，不只检查摘要hash；在原首次未来发布前，48对均逐字段相等。01截点为60000ms，02为120000ms；使用严格 `<before_ms`，首次到达时刻及以后允许分歧。

原始canary涵盖私有episode/base ID、全局goal/context、任务成本上界、工具描述、agent私有字段；未来变化分别为延后到达、更改未来deadline/priority/goal和移除未来请求。静态设备清单不变；future移除不是新服务设计。比较完整对象同时检查前缀行为，不以搜索一个数字或标签替代信息审查。

| 诊断文件／对应主配置 | case／截点ms | runs[0..3]各自前缀事件下标；calls下标 | 结果 |
| --- | --- | --- | --- |
'''
for filename in dict.fromkeys(x['file'] for x in a['prefix_checks']):
    rows=[x for x in a['prefix_checks'] if x['file']==filename];r=rows[0]
    ranges='；'.join(f'P{x["run_index"]}:e{x["event_indices"][0]}–e{x["event_indices"][-1]}' for x in rows)
    name=Path(filename).stem.replace('F2R1-D-F2-','')
    text+=f'| {link(name,filename)} | {r["case"]} / {r["before_ms"]} | {ranges}；各自q0–q2 | 全4策略完整calls/events一致 |\n'
text+='''
同时发布与晚到在0ms已公开需求不同；容量紧/足的容量也合法不同，均不要求错误的全输入相等。每一实际请求还独立按发布时快照和合同白名单重建，80条共304次调用均匹配：自身设备状态、静态成本、已发布列表/目标、空约束/pending和规范身份；不存在模板答案、任意原文、来源路径或未来请求进入实际输入。

## 实际调用、旁路、回归与冻结

另以捕获provider重新运行8配置×4策略：32条输出与保存run完整对象一致，provider与trace请求一致，instructions为空。将v7模块的 ideal_schedule 替换为直接抛异常的探针，全部32条仍执行成功，证明这些在线路径没有调用该oracle。源码复核也确认排序只使用已发布提案；可信执行器持有未来世界任务不等于策略可据此选动作。

16项负探针全部在首次provider调用前拒绝：episode hook、外部instructions、中央主体、未来保留/事后可行性/容量感知/固定等待策略、未来保留元数据、批次计划、compute计划、额外constraints、静态私有字段、成本不一致、缺失授权、按私有ID合成时延和外部协调延迟。hook没有执行。这些探针不构成对任意第三方provider自带信息的保证。

补充四策略NoAction轨迹均保留所有任务完成=false、时延=null、按时=false，原始补充轨迹已保存。完成审查需要实际事件证据，测试文件存在本身不算边界轨迹证据。

F2专项13项作者测试在审核中重跑全部通过；全套433项未重跑。专项包括同刻发布、真实排队、无动作、成本/计划拒绝、oracle禁止、基础引擎32对核心指标回归及源码复制差异检查。独立事件重算和原始反事实比较是本次主要验收证据。

新manifest所列源码、原开发输入及23份JSON哈希全部一致；确定性生成器再生成的24份对象与提交文件全部相等。旧Phase B manifest与先前审查保存哈希一致，其源码、附件及历史结果，以及C1 v5/v6输入/回放合计39项冻结哈希核验无差异。本轮没有改写这些材料，也没有追认旧F2信息边界。

缺失证据与范围：当前8配置、显式v7入口、四策略和提交轨迹没有待补验收项。未完成独立双审；跨运行有记忆provider、真实家庭物理/用户授权、经验到达分布、模型性能、全部损失的不可避免性/反事实因果归因及其他任务族均不在通过范围内。32主+48反事实不计成80种独立结构。request_id唯一性限于单次隔离回放。

无需为本次验收修代码。后续研究结论仍需保持上述限域，不把离线可行排程当在线基线、不把脚本数字一致当旧信息输入正确、不把任务验收写成LLM优势。未调用API或保留实验，未上传GitHub；审查结果仅保存到独立工作区，没有填写作者的reviewer_acceptance。

'''
text+=f'详细重算：{local("F2_V7_EVENT_AUDIT_20261002.json","F2_V7_EVENT_AUDIT_20261002.json")}；实际调用/负测试/补充轨迹：{local("F2_V7_RUNTIME_PROBES_20261002.json","F2_V7_RUNTIME_PROBES_20261002.json")}。\n'
(O/'F2_V7_REVIEW_20261002.md').write_text(text,encoding='utf-8')
print('written',len(text.encode('utf-8')),'bytes')
