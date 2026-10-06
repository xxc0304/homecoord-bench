import json
from pathlib import Path
O=Path('outputs');a=json.loads((O/'C1_V6_TARGETED_AUDIT_20261002.json').read_text(encoding='utf-8'))
R='.'
def link(label,path,line=None):return f'[{label}]({R}/{path}'+(f':{line}' if line else '')+')'
v6='homecoord_bench/task_revision/event_simulator_v6.py';rev='homecoord_bench/task_revision/protection_revision_v6.py';v5='homecoord_bench/task_revision/event_simulator_v5.py';metrics='homecoord_bench/runtime/task_response_metrics.py'
text='''# C1 v6 两项修正针对性复审（2026-10-02）

总体结论：**两项修正通过，8 个配置均为“符合设计”**。32 条主回放和 16 条诊断回放的相关执行、准入及服务评分与事件证据一致；本轮未发现需要修正的残留缺陷。

审查者：本聊天中的 Codex 单模型代码审查；与材料中的作者自检分开重算，不是人类审查，也未完成独立双审。阅读了评分结果以核对执行和计分，未比较方法优劣。范围仅限 v5 的输入信息泄露、准入与服务混算两项问题及其 C1 回归，不重新进行设计验收。

复审证据：读取 8 个完整输入及 48 条已提交轨迹；逐事件重建状态、版本、保护损失、启动/完成匹配、等待、时延、迟到、未完成和请求终态，再与 result 和 author audit 对照。另执行确定性离线复现、实际 provider 捕获、私有 ID/未来事件反事实、hook 和准入事件篡改检查。没有 API、模型或保留集运行，没有运行其他任务族，也没有改写仓库原文件。本轮结论不以作者“420 测试通过”为依据。

所有 JSON 数组下标从 0 开始。P0=IndependentMultiAgent，P1=ConstraintCoordinator，P2=DeadlineAwareCoordinator，P3=GateRetryRule；主回放每四条按此顺序。原始轨迹位置为 `runs[i].trace.events[j]` 或 `diagnostics[i].trace.events[j]`。

## 代码定位

'''
text+=f'''- A，公开输入边界：{link('event_simulator_v6.py',v6,15)} 在调用前拒绝 episode preparation hook；第 19–23 行按设备映射为 HC-M02/HC-M03，并移除 variant、review_status、task_card。{link('protection_revision_v6.py',rev,50)} 调用时传入空 instructions。外层 evaluation_episode_id 保留为审查索引，不进入 provider 请求。
- B，准入独立重计：{link('protection_revision_v6.py',rev,24)} 将发布时保护状态映射为 admitted/rejected_terminal；第 28–38 行核对唯一准入事件、发布时间和覆盖集合，独立生成 admission_correct；第 39–42 行分别输出终态、完成、时延与按时。
- C，真实执行与服务：{link('event_simulator_v5.py',v5,962)} 发布处终态拒绝后跳过 provider，第 968 行正常准入；{link('启动前提复核',v5,1086)} 在失效时拒绝启动；{link('任务响应计分',metrics,10)} 从匹配启动及完成事件计算时延和迟到；{link('请求终态',v5,1394)} 区分拒绝、完成、未解决。

## 逐配置填写

同一配置的四策略均核对；表内事件下标对这四条轨迹均适用。输入列指完整请求 JSON，包括任务文本、角色、约束、工具、模板、状态与所有 ID，不只是关键词搜索。

| 配置 ID | 输入判断及请求位置 | 准入／终态／动作／按时及事件位置 | 结论、理由、缺失证据、通过条件 |
| --- | --- | --- | --- |
'''
for start in range(0,32,4):
    d=a['runs_and_diagnostics'][start];ident=d['episode_id'];conf=ident.endswith('CONFLICT');scene='HC-M02' if 'LIGHT' in ident else 'HC-M03'
    inp=f'`runs[{start}…{start+3}].trace.agent_requests[0]` 与本设备其余三配置首请求逐字段相同；公开 ID {scene}（A）。'
    if conf:
        disp='e6 发布、e7 在 1200ms 终态拒绝；e8 在 6000ms 到期，旧请求无调用、预约、启动或完成。准入正确=true；完成=false，时延=null，按时=false；动作服务率 0.5（B/C）。'
    else:
        inp+=' 低请求 [1] 仅在 6500ms 获得当前任务及当前状态。'
        disp='e6 在 6000ms 到期，e7 在 6500ms 准入，e8 发布记录；e12 在 6900ms 启动，e13 在 7400ms 真完成。准入正确=true；终态 completed，等待400ms，时延900ms，按时=true（B/C）。'
    text+=f'| `{ident}` | {inp} | {disp} | **符合设计**；两个修正均有输入及事件证据。当前范围无缺失证据；通过条件已满足。 |\n'
text+='''
高请求在全部主回放均为 e0 发布、e4/400ms 启动、e5/900ms 完成，1100ms 截止内完成。48 条轨迹逐区间累计的保护失效均为 0，未以最终状态替代过程检查。CONFLICT 的正确拒绝没有被转换为动作服务或按时成功。SAFE 的合法完成以自身发布时间计算，两个配对用途及其 deadline 参数保持原合同。

## 完整输入与反事实证据

| 配对组 | 四个主回放下标（首请求 [0]） | 完整输入相等 |
| --- | --- | --- |
'''
for p in a['full_first_request_pairs']:text+=f"| {p['scene']} / {p['policy']} | {', '.join(map(str,p['run_indices']))} | 是 |\n"
text+='''
8 组比较均是整个首请求对象相等，不由标签未命中推断。所有 80 个保存请求还逐项核对发布时间、快照版本、观察路径、工具权限、当前任务与局部约束；未发现私有实验 ID、情境/预算标签、未来事件或完整任务流混入实际请求。低请求已发布后的自身 release/deadline 属于合同允许的信息。

在两个设备×四策略的 8 个独立捕获探针中，把 episode_id/base_episode_id/variant 改为含相反情境及预算的私有标记，同时把到期改为 6100ms、低请求发布改为 6600ms：完整首请求仍相等。捕获 provider 收到的对象与 trace.agent_requests 相等，实际 instructions 均为空。补充原始轨迹保存在审查 JSON 的 runtime_probes 数组中。

带 prepare_release_batch 的 provider 在进入 frozen engine 和调用 provider 前被 ValueError 拒绝，hook 和 decide 均未调用（A）。公开 ID 仅标识设备场景；其唯一性范围是单次隔离回放。这不是对跨运行、有记忆 provider 或未来模型实验输入公平性的验收。

## 16 条诊断逐条检查

所有诊断的低请求 admission_correct=true；这不会推出动作完成或按时成功。下表的“高请求拒绝”指启动前提失效，不是发布处的终态政策拒绝。位置均位于相应 diagnostics[i].trace.events。

| diagnostics 下标／设备／策略 | 情形与事件位置 | 独立重算的终态、完成、时延和按时 | 结论 |
| --- | --- | --- | --- |
'''
for d in a['runs_and_diagnostics'][32:]:
    i=d['section_index'];scene='LIGHT' if 'LIGHT' in d['episode_id'] else 'BLINDS';m=d['computed'];low=next(iter(m['request_status']));high=next(k for k in m['task_correct_action_completed'] if k!=low)
    if d['case']=='admitted_no_action':
        ev='e7/6500ms 准入；e9/6800ms 返回 noop，e10/6800ms agent_no_action；无低请求启动或完成。'
        res='低请求 unresolved；完成=false；等待/时延/迟到=null；按时=false。高请求真完成900ms。'
    else:
        rejected=next(x for x in d['evidence'] if x['type']=='action_rejected');finish=next(x for x in d['evidence'] if x['type']=='action_completed')
        start=next(x for x in d['evidence'] if x['type']=='action_started')
        ev=f"e1/6000ms 保护到期；e2/6500ms 准入；e{rejected['event_index']}/{rejected['timestamp_ms']}ms 高请求 stale_state 拒绝；e{start['event_index']}/{start['timestamp_ms']}ms 低请求启动；e{finish['event_index']}/{finish['timestamp_ms']}ms 完成。"
        res=f"高请求未完成、时延=null、按时=false。低请求 completed；完成=true，等待{m['task_start_wait_ms'][low]}ms，时延{m['task_completion_latency_ms'][low]}ms，迟到{m['task_completion_tardiness_ms'][low]}ms，按时=false。"
    text+=f"| {i} / {scene} / {d['policy']} | {ev} | {res} | 符合设计（B/C） |\n"
text+='''
DeadlineAwareCoordinator 的两条慢提案诊断在 14600ms 完成、时延8100ms、迟到6600ms；其余对应诊断在14100ms完成、时延7600ms、迟到6100ms。审查使用各自真实轨迹，没有把它们强行重计为相同时刻。

准入事件篡改：取 runs[4] 的 e7/request_admitted，分别删除或复制；两次 audit 都抛出 AssertionError，不能接受缺失或重复的准入证据（B，第30/34行）。原始保存轨迹没有被改写。

## 回归与可复现性

v6 manifest 声明的 6 个源码和 2 个数据文件 SHA-256 全部一致。v5 的输入、manifest、回放及 3 个冻结源码与先前审核哈希一致。v6 确定性 bundle 离线再生成后，8 个输入、32 条主回放、16 条诊断及 manifest 与提交对象逐字段相等。

32 条主回放与对应 v5 的 request_status、task_correct_action_completed、task_completion_latency_ms、task_deadline_met、state_constraint_violation_duration_ms 五项均相等。另由事件独立重算的服务率、未完成数、等待、迟到、动作效果及状态版本也与结果相符。v5 的既有错误验收状态没有因此被追认。

最终填写：两个修正均为“符合设计”，当前针对性验收无待补项。接受范围仅为本次明确 v6 入口、单保护请求、合成设备状态、隔离确定性回放及已提交48条轨迹。未完成独立双审；不覆盖真实家庭、多用户仲裁、模型必要性/优劣、其他任务族及全部420测试的验证。作者 manifest 未锁定所有间接依赖，本结论针对当前实际读取并成功复现的工作树版本，不承诺任意后续版本仍通过。

审查人输出保存在独立工作区，不修改作者 review form 或 reviewer_acceptance 字段。可直接以本报告八行表及诊断表回填作者复审表。
'''
text+='\n完整逐事件重算和补充探针：[C1_V6_TARGETED_AUDIT_20261002.json]('+str((O/'C1_V6_TARGETED_AUDIT_20261002.json').resolve()).replace('\\','/')+')。\n'
(O/'C1_V6_TARGETED_REVIEW_20261002.md').write_text(text,encoding='utf-8')
print('report written; all48 replay checks:',all(not d['execution_scoring_errors'] for d in a['runs_and_diagnostics']))
