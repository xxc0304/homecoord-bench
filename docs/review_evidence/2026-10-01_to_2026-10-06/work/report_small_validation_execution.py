import json
from pathlib import Path
R=Path('.');O=Path('outputs')
p=O/'SMALL_VALIDATION_V1_EXECUTION_AUDIT_20261005.json';a=json.loads(p.read_text(encoding='utf8'))
a['actual_tests']={'passed':75,'failed':0,'excluded':'test_zero_and_500_command_fresh_execution (would generate six new simulations)','modules':['test_small_validation_execution_v1 (22/23)','test_small_validation_plan_v1 (9)','test_small_validation_design_audit_20261005 (8)','test_f2_aggregation_v1 (26)','test_f2_statistical_contract_v1 (10)']}
p.write_text(json.dumps(a,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
code=R/'homecoord_bench/task_revision/small_validation_execution_v1.py';core=R/'homecoord_bench/task_revision/f2_aggregation_v1.py';engine=R/'homecoord_bench/task_revision/event_simulator_v7.py'
def loc(path,name):return next(i for i,line in enumerate(path.read_text(encoding='utf8').splitlines(),1) if line.startswith('def '+name+'('))
def link(path,label,line=None):return f'[{label}]({path.as_posix()}'+(f':{line}' if line else '')+')'
text='''# 小规模验证 v1：独立实现审查

2026-10-05。结论：**28配置、84条主运行及72对统计均符合已冻结设计；本批新入口、已提交轨迹和统计结果通过限定实现审查。** 未发现须修正项。作者的测试通过及旧适配器验收未被用作本次验收替代品。

本审查仅覆盖两个F2晚到模板、容量3/6、三种既有确定性政策及预定单因素扰动。不能据此宣布策略普遍更优、LLM必要、真实家庭有效、跨执行阶段稳健或预约机制因果作用。

## 核查结果与证据

| 对象 | 结论 | 独立证据与实现位置 |
|---|---|---|
'''
rows=[('冻结与物化输入','11份获准材料与此前独立设计审计相同；冻结各锁匹配。28份输入从旧源独立重建，仅发生获准变化，核对派生及最终SHA',code,'verify_freeze'),('12条新基线','完整calls含request/decision、全部trace字段及顺序逐一与旧同政策比较，仅去除两个外层身份字段；未递归掩码',code,'exact_baseline'),('扰动前门禁','每次扰动重新build_gate，读取四份基线并校验完整复现和代码/冻结绑定；不是信任passed标志',code,'verify_gate'),('公开输入与能力','84条逐发布状态重建，完整request逐字段核对独立白名单；336条decision从公开工具能力独立构造一致，无因素标签或未来请求通道',core,'recount'),('真实执行与回执','每次启动核对授权、前提、状态版本、成本及提案；完成匹配task/agent/proposal/target/operation、周期和效果，最终状态与版本一致',core,'recount'),('命令、拒绝与重试','每次启动/拒绝有唯一匹配预约，S≥预约创建+C；重试关联此前拒绝、唯一排队与retry_scheduled；拒绝时实际负载、状态版本正确',code,'clock_evidence'),('容量与观察终点','实际开始至完成半开区间独立积分，无超容量；预约不算实际负载；物理周期均闭合，没有在截止处截断',core,'recount'),('固定分母与自身时钟','逐任务R/P/S/F与下标保存；E=4、early=3、water=1；84行全部字段独立重计一致，时延F−自身R',core,'recount'),('72对与共同K','预列身份、白名单、分层固定分母、共同K和各任务值全部独立重算一致；当前K=E，失败/空K规则另由负测试核查',core,'compare'),('结果重现','禁用新模拟器后完整statistics产物复现；先完成独立重计再作作者实现复现，无原result作为统计答案',code,'statistics')]
for title,detail,path,name in rows:text+=f'| {title} | 符合设计 | {detail}。{link(path,name,loc(path,name))} |\n'
text+='''
0ms同刻证据：`config_19.json` /runs/0（F2-02紧容量、GateRetryRule、command=0），300ms的e3/e6/e9先返回提案，e5/e8/e11预约；e13/e15实际开始，e16因实际负载3加清洁需求2超过容量3拒绝，e17排队。零命令延迟允许同刻开始，不允许在返回或预约之前开始。引擎队列优先级为状态/完成0、发布1、响应3、启动4；同阶段保持插入顺序。全部0ms轨迹的状态版本、实际容量及重试对应通过独立事件核查。

## 逐配置结论

下面每行覆盖三条策略轨迹，均为“符合设计”。简写G=GateRetryRule、C=ConstraintCoordinator、D=DeadlineAwareCoordinator。water事件写作发布/返回/开始/完成的**0起始事件下标**，顺序G、C、D。完整预约/拒绝/重试事件证据与逐任务下标见机器审计的configurations数组；每行绑定文件及/run索引0/1/2，不只用配置级总分判定。

| 文件（配置ID见完整输入） | 配置 ID | G/C/D结论 | water事件下标 G；C；D |
|---|---|---|---|
'''
for c in a['configurations']:
    ev=[]
    for r in c['runs']:
        z=r['events']['water'];ev.append('/'.join(str(z[k]) for k in ('release','return','start','completion')))
    text+=f"| {link(R/c['file'],Path(c['file']).name)} | `{c['config_id']}` | 符合设计／符合设计／符合设计 | {'；'.join(ev)} |\n"
text+='''
## 初步发现能否采用

可采用为本批局部研究发现，措辞已与轨迹对应：

- 84条均完成四服务、超容量为0。紧容量42条中只有2条四服务全部按时；容量足42条全部按时。这是网格清单计数，不是池化成绩、策略排名或独立随机样本。
- 全部24对预算扰动的四任务绝对开始和完成时刻不变。预算放宽可改变期限判定，不应称执行加速。
- 全部12对紧容量发布扰动中，四任务绝对执行时刻不变；water自身响应随R变化反向移动30秒。容量足的12对中，water绝对执行平移30秒、自身响应不变。自身响应改善不等于资源调度改善。
- 全部24对命令扰动按时主率差为0，但真实执行时刻会改变；重试路径可累积命令成本，不能把每份等待都当作单次命令延迟。

F2-02紧容量GateRetryRule的定位例：config_14基线、config_16预算+30000、config_18发布+30000、config_19命令0、config_20命令500，均/runs/0，water发布e19、返回e20、启动e31、完成e32。完成分别420500、420500、420500、420300、421300ms；自身响应分别300500、300500、270500、300300、301300ms；迟到分别500、0、0、300、1300ms。预算或发布修改使期限达标但绝对完成不变；0ms命令仍迟到300ms。

## 验证范围与限制

独立脚本完成2637条检查，零失败；逐事件重建84运行、完整独立重计72对及findings_evidence全部配对字段。新材料manifest与作者保护锁均核对，217项原设计保护材料未变。

实际重跑75项测试通过：新入口22、静态计划9、设计检查8、F2适配器26、F2统计合同10。作者报告的76项中，有一项会新增六次仿真，本次明确跳过；0/500ms合同直接审已保存轨迹。因此本次未调用模型/API、未运行新仿真或保留实验、未改冻结材料、未上传。

当前84条全部完成，空K、未完成分母及缺值拒绝未在本批主轨迹自然出现；这些边界覆盖来自代码审查和负测试，不能称本批已经提供全部失败场景轨迹。同样，保存材料与代码门禁能证明输入/结果一致及预定执行规则，不能独立重建每次生成的真实墙钟执行历史。

本次确认的是已提交新入口和统计正确，以及局部发现的证据边界。后续“未启动预约保留/重排”须另行设计合同及对照，本次不包含该机制消融。未建立双人独立审查，也未回写作者验收标志。

'''
text+=link(p.resolve(),'独立机器审计')+' · '+link(Path('work/audit_small_validation_execution.py').resolve(),'独立复核脚本')+'\n'
(O/'SMALL_VALIDATION_V1_EXECUTION_REVIEW_20261005.md').write_text(text,encoding='utf8')
print('report saved')
