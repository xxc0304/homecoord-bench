import json
from pathlib import Path
R=Path('.');O=Path('outputs');B=R/'docs/f2_reservation_ablation_v1_20261005'
A=O/'F2_RESERVATION_ABLATION_V1_AUDIT_20261005.json';a=json.loads(A.read_text(encoding='utf8'))
def link(p,label,line=None):return f'[{label}]({p.as_posix()}'+(f':{line}' if line else '')+')'
code=R/'homecoord_bench/task_revision/f2_reservation_ablation_v1.py';engine=R/'homecoord_bench/task_revision/event_simulator_reservation_v1.py'
def line(p,text):return next(i for i,x in enumerate(p.read_text(encoding='utf8').splitlines(),1) if text in x)
text='''# F2预约机制 v1：限定独立复审

审查完成日期：2026-10-06；材料为2026-10-05版、implementation_revision=3。

**结论：设计合同接受；8配置的16条正式运行、8对比较及24条信息诊断符合设计。本批新引擎、预约代次与已提交统计通过限定实现审查，无须修正项。** 这是读取新合同、代码差异和原始轨迹后的结论，不继承旧v7验收，不将作者交叉核对作为独立验收。

合同此前没有独立运行前接受；本次在已见结果的阶段接受其受控范围与实现，不能改称“独立审阅者事前批准”。现有文件哈希能确认提交内容一致及历史版本保留，不能独立证明真实墙钟上的预登记/执行先后。

## 设计合同与实现对照

| 对象 | 结论 | 理由及证据 |
|---|---|---|
| 范围与干预 | 接受／符合设计 | 全部4个旧late源×共同审议0/100ms×retain/replan；固定同一DeadlineAwareCoordinator。原输入只改变私有episode身份，权限、到达、截止、提议能力、300ms返回、100ms命令及服务周期保持。不是40份性能样本。 |
| 相同调度器 | 符合设计 | 比较新引擎与v7全部代码差异，容量派发及EDF函数不变；独立按绝对截止、priority、原返回时刻、task_id重建所有预约批次顺序，并独立搜索最早安全容量起点，均匹配。 |
| 真正未启动的预约 | 符合设计 | 提交快照按实际active动作集合重建；只使尚未启动的预约代次失效。正在运行的服务开始、结束、回执及设备效果两臂一致。 |
| 身份和代次 | 符合设计 | 每proposal预约代次递增；失效回调在原计划时刻仅suppressed一次；新代次真实开始/完成唯一且身份匹配，旧回调不更改设备、状态版本或服务完成。 |
| 信息与前缀 | 符合设计 | 逐发布状态独立构造完整request白名单、公开能力decision；两臂完整calls及提交快照为止的事件前缀一致。24份完整反事实输入独立重建，严格小于原发布时刻的calls含decision及events一致。 |
| 真实服务、容量与计分 | 符合设计 | 16条逐事件重建状态版本、授权前提、实际开始、周期和效果匹配回执。实际半开区间容量积分为0；完整轨迹闭合；固定E=4/early=3/water=1、自身R及共同K重计一致。 |
| 新retain基线 | 符合设计 | 4条新主retain与门禁run完全相同，只计一次。仅投影新增观察事件、事件顶层代次及明确外层身份后，完整旧calls/trace/result精确复现；不递归删除字段。 |
| 锁与失败版本 | 符合设计 | revision3及835项保护SHA匹配；两个失败记录、原入口及revision2快照匹配锁链。三个锁的引擎/合同/网格SHA相同。入口差异只有前提协议语义/序列化审计修正及版本门禁绑定。 |
| 成对统计 | 符合设计 | 独立生成两臂全字段audit、8份pair、逐任务差值、共同K及early/water子集均一致；保存完整statistics在禁用模拟器后重现。主4对和敏感性4对分开，不加权池化或排名。 |

'''
text+='关键代码：'+link(engine,'共同触发与按实际运行重审',line(engine,'def apply_reservation_review'))+'；'+link(engine,'旧回调代次抑制',line(engine,'if live_reservation_generation.get'))+'；'+link(code,'事件与代次审计',line(code,'def audit('))+'；'+link(code,'两臂前缀及E/K计分',line(code,'def pair_audit('))+'；'+link(code,'基线门重核',line(code,'def verify_baseline_gate('))+'。\n\n'
text+='''## 逐配置结论

每行覆盖/runs/0=retain、/runs/1=replan。事件下标为原始完整trace.events的0基下标。理由来自独立重计；各行缺失证据与通过条件另列在表后。

| 配置／完整轨迹 | 容量／共同延迟 | 设计 | 实现两臂 | 提交下标 | water开始/完成 retain → replan | 核查理由 |
|---|---|---|---|---|---|---|
'''
for i,c in enumerate(a['configurations']):
    p=c['independent_pair'];event=[]
    for r in p['audits']:
        z=r['tasks']['water']['event_indices'];event.append(f"e{z['start']}/e{z['completion']}")
    tight=c['capacity_arm']=='competition';reason=('仅重排'+','.join(p['unstarted_task_ids'])+'；运行中服务不变，water仍迟到' if tight else '无未启动预约；两臂真实服务指标一致，负对照保留')
    text+=f"| {link(B/f'config_{i:02d}.json',c['config_id'])} | {'紧' if tight else '足'}／{c['review_delay_ms']}ms | 接受 | 符合设计／符合设计 | {p['commit_event_indices']} | {' → '.join(event)} | {reason} |\n"
text+='''
各配置的缺失证据：本批不提供真实部署审议成本、更多任务/家庭、模型重复实验，以及补充边界测试的完整保存轨迹。它们不阻断当前16条轨迹的限定通过；若扩展上述结论，须另交合同、输入与轨迹。

通过条件：当前提交输入、身份、revision3源锁及原始事件/统计保持本审计SHA；范围仅限这8配置。若修改预约语义、阶段或计分，应建立新版本并另审，不能沿用此结论。

紧容量主例定位：RA1-00 replan e20提交、e21失效laundry、e27旧回调抑制；water e29开始/e31完成，新laundry e33开始/e34完成。RA1-04 replan e20提交、e21失效cleaning、e27抑制；water e29开始/e30完成，新cleaning e32开始/e34完成。失效的是预约代次，不是已开始的物理服务。

## 可采用的研究发现

| 主配置 | water完成/响应差 | 其他任务代价 | 固定4任务平均响应差 | 全户完工差 | 按时服务 |
|---|---:|---|---:|---:|---|
| 模板01、紧 | −480秒 | laundry +120秒 | −90秒 | 0 | 3/4→3/4 |
| 模板02、紧 | −360秒 | cleaning +240秒 | −30秒 | 0 | 3/4→3/4 |
| 模板01、足 | 0 | 无 | 0 | 0 | 4/4→4/4 |
| 模板02、足 | 0 | 无 | 0 | 0 | 4/4→4/4 |

独立证据支持：**在这些固定前缀、同一调度器配置中，晚到任务的额外等待不全来自正在实际运行的非抢占服务；未启动预约的处理规则确实会改变时延分布。** 所有服务完成、过程安全、按时服务、平均自身响应、个体响应和全户完工仍须分别判断。

模板01 replan water真实F=420400ms，D=300000ms，迟到120400ms；模板02真实F=420400ms，D=420000ms，迟到400ms。两臂各自的water均不按时；没有提前算完成或把迟到缩短记作按时成功。

这不是所有任务受益：洗涤/清洁付出明确延后代价。均值改善也不是简单等量转移：固定4项中等待减少的总量分别360/120秒，因串并行安排改变，不能由全户完工不变推断响应总量不变。

共同100ms敏感性：紧容量的绝对S/F均不变；足容量仅两臂water S/F同时增加100ms，所有臂间差值和全户完工/按时率不变。只能称这两个预定合成成本水平下结论一致，不能当作实测重排成本或任意延迟稳健性。

事后条件界限独立重算：固定提交快照中正在运行的服务及共同命令下界，忽略未启动预约，water最早可在300400/180400ms开始、420400ms完成；主replan达到这一条件界限。这是固定当前执行前缀的物理可行下界，不能说在线最优或全局不可避免迟到，也不是预登记主指标。

正向证据属于“释放未启动预约、重新合并就绪提议并以同EDF重排”这套整体规则干预。未分别识别释放、EDF或身份机制的独立贡献；未证明创新性、真实家庭/LLM性能提升或普遍优越。可以推进F1批等待与排序的**新合同及对照设计**，该实验并不由本报告直接验收。

## 验证范围

1611项独立检查零失败；独立重建16运行、8对全部audit/pair字段、24诊断输入及前缀。835项旧保护哈希一致，此前小规模验证的独立接受锁也保持。

实际重跑67项通过：新预约审查相关19项、旧F2适配器26项、小规模验证入口22项。没有将作者87项报告当作本次实际重跑数量。跳过6项会生成新预约仿真的测试及1项会生成小规模仿真的测试；另未重跑旧F2 v7的13项（多项会批量重仿真）。没有新增仿真、模型/API、保留集或上传。

同刻提交/启动、审议期间已开始、旧回调晚于新完成、无动作等边界主要是作者测试代码和代码审查证据；本次没有重跑其新仿真，也没有独立验收这些边界的全部保存轨迹。当前主运行K=E；空K与失败分母的保证来自代码/负测试，不冒称自然失败样本已覆盖。当前结果验收不扩展到所有引擎可接受参数。

本次由单一独立审阅者完成，未建立双人独立审查，也未回写作者的独立接受字段。

'''
text+=link(A.resolve(),'独立机器审计')+' · '+link(Path('work/audit_f2_reservation_ablation_v1.py').resolve(),'独立重计脚本')+' · '+link((O/'F2_RESERVATION_ABLATION_V1_TESTS_20261005.json').resolve(),'实际测试范围')+'\n'
(O/'F2_RESERVATION_ABLATION_V1_REVIEW_20261006.md').write_text(text,encoding='utf8')
print('report saved')
