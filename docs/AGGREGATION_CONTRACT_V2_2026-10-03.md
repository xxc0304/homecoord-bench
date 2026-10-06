# 汇总合同 v2：固定资格、分层对照与交互项

2026-10-03。针对CROSS_FAMILY_AGGREGATION_REVIEW_20261003.md及AGGREGATION_CONTRACT_V2_REVIEW_20261003.md修订。**身份与对照计划核验通过；两项合同修正已提交，待针对性复审、未冻结，统计适配器未实现。** 台账作为范围记录已经接受，但不等于本合同或汇总实现通过。旧草案历史内容保留、允许追加状态说明；台账机器材料、任务源码/成绩不改写。

## 1. 本版范围及运行身份

首先拟冻结的可执行统计范围为F3 v8：8世界、192主运行、32诊断，明确不输出跨族总分。其他族以下规则是扩展约束，未枚举其全部运行前默认out_of_scope，不能自动进入本版汇总。C4只提供四行替换映射，不在本版计算C4统计。

机器材料在aggregation_contract_v2_20261003：
- run_inventory.json：224行规范运行身份、世界、能力、selector、请求发布/截止、源路径/零基JSON pointer/哈希；192primary固定资格，32diagnostic仅正确性检查。
- pair_plan.json：72固定模式政策对照、64同权限selector对照、96相同模式候选控制、192选择/能力干预；24组四单元分解计划。这里只生成身份计划，不读取旧差值作为新结果。
- c4_replacement_map.json：四个原槽位与有效来源的一对一映射。原96槽位含主/诊断，不是常规成功率分母；v10其余24验证另记validation_only，不新增到原队列。

canonical_slot_id不因替换改变。source_version/path/row_pointer/hash记录真实有效来源；family、base_world_id、config_id、policy、selector、return_order_id、role、capability、授权模式、发布/截止、观察终点合同、成本单位必须齐备。实际完整模式向量、started/completed集合、task/attempt_id只能由后续真实事件适配产生，不把计划授权向量或提案向量冒充实际执行向量。

诊断还必须有diagnostic_id，反事实必须有counterfactual_id与原槽位，前缀验证必须标注自己的观察終点；未来新增的诊断或运行未列入受审清单时默认不可统计，不可猜测身份。源清单内任何重复/缺失/哈希错误是证据错误。

## 2. eligibility独立于方法结果

对每个运行和指标先生成固定请求键集合E，之后才读取准入、启动、完成等方法结果。拒绝、没启动、没完成、迟到都不能从E删除。当前F3每个primary的E就是该配置task_stream中所有声明的必需服务task_id；同世界同任务需求的对照两臂E相同，固定/选择能力差异不改变服务分母。诊断E不进入主成功率。

C为有效尝试真实完成的请求集合，O为其中按各自发布/截止按时完成的集合：
- service_completion_rate=|E∩C|/|E|。
- timely_service_rate=|E∩O|/|E|。
- timely_among_completed=|E∩O|/|E∩C|，单独命名并同时展示completion_rate，不能替代按时服务率。
- 空E时三个率均返回null/status=no_eligible_requests。E非空且零有效完成时，service_completion_rate和timely_service_rate均为0/status=ok；timely_among_completed为null/status=no_completed_requests，展示required>0、completed=0、on_time=0。有效完成非零但全部迟到时，timely_among_completed为0/status=ok，不能与零完成混同。
- completed条件均值只作带覆盖数的附表；默认不删未完成后报告“平均服务时延更低”。

其他族扩展时的静态资格：
| 族 | 固定资格／分层 |
|---|---|
| C1 | 请求处置E包含全部声明请求；动作服务E按发布时合同授权与保护状态预定，从配置初态及外生规则推导，不按实际request_admitted/预约筛选。无保护的合法请求即使被方法拒绝仍留在E；受保护相反请求从动作E排除但保留在处置E。 |
| F1/F2 | 各可行主配置所有声明服务；返回条件/策略不删请求。反事实不入主分母。 |
| C4 | 共同请求队列固定；完成/撤回/待恢复/未决为竞争状态分别计数，物理终止另列。若撤回终态取决于方法完成时刻，不计算按各方法撤回结果缩小后的动作成功率；只可用事前指定子集或状态计数。 |
| 依赖 | 常规六配置EARLY、LATE、FEASIBLE_8500、RESTART_RESTORE、CAPACITY_TIGHT/SAFE的全部声明请求。FORGED_STATE/STALE_NATURAL_RACE另一个固定可行对抗队列；8000、取消两项、无恢复、非法提议独立诊断。不得按是否实际完成决定子集。 |
| C2 | 处置E为每条主运行全部请求；必要开窗命令E按发布时预定空气需求，合法skip不在必要开窗E；供暖命令E仍含供暖请求。环境E为12世界×两臂固定24槽位，未完成仍计未按时。全请求命令兼容率若保留必须另名。 |

这些族的静态请求资格表和运行清单仍需在扩展前逐行生成及审查，不能用上述文字跳过验收；当前机器计划仅F3。

## 3. F3四类对照，不强行统一匹配条件

差值方向统一candidate−control；负值只表示数值更低，不自动叫收益。

各对计划已列fixed_fields、allowed_differences与primary_metric：主指标为按静态必需请求分母计算的timely_service_rate；服务完成率、整体完成、个体等待/迟到、观测成本差及同等服务节省为并列次指标。固定输入指观察/工具/延迟合同相同，不要求不同政策导致分歧后的当前设备状态逐字段相等。

| 类型 | 固定 | 允许变化／解释 |
|---|---|---|
| fixed_mode_scheduling | 世界、事前唯一授权模式向量、服务/输入/成本/期限/终点合同；所有实际启动动作均须符合授权 | 政策与architecture身份；主服务率与按时率不要求完整实际模式，未启动失败仍留在E与配对中 |
| selectable_selector | 世界、政策、相同selectable权限、服务/输入/成本/期限/终点 | selector与其模式选择；选择规则差，包含对资源与排队的影响 |
| mode_matched_control | 世界、政策、完整实际模式、真实服务效果与成本/期限/终点 | fixed/selectable能力及选择机会不同，显式标注；仅确定性机制核对，不当同权限普遍因果识别 |
| capability_and_selection_intervention | 世界、政策、服务及成本参数等共同条件 | selectable/fixed能力和选择干预，保留权限差异；对应旧192项，不命名纯选择或协调收益 |

本版预定s0=IndependentMultiAgent，主候选s1=ConstraintCoordinator；DeadlineAwareCoordinator/GateRetryRule为分开报告的敏感性臂，不与主臂合成一个胜率。同权限selector比较以low_resource作control、short_duration及capacity_pressure分别作candidate，共64对。72固定模式对照各向量均以s0作control；这是新冻结方向，不盲抄旧差值正负号。

固定模式72对的主服务比较以事前唯一授权向量匹配，资格按指标独立判定：证据完整但未启动不是缺证据，不删除配对、不令主率或主差值为null，不虚构未启动任务的执行模式。本次复审发现36对至少一臂未启动全部任务；这些失败必须保留。完成时延、同等服务节省与实际模式机制解释仍分别适用自己的资格门槛。

96相同模式计划沿用已审v8控制身份但必须重新核对所有声明任务的实际启动模式完整向量。只有部分任务可观察到模式时status=incomplete_actual_vector；不匹配最近向量、不从缺失任务补默认模式，也不临时改权限。复审指出其中12对向量不完整，不能称96对全部具备机制解释资格；其原始运行与E仍保留。已有96控制的计分验收不自动等于本统计机制解释通过。

## 4. 联合变化必须保留交互项

m0为所有可选任务eco，其余prepare；m1为所有可选任务fast，其余prepare，对应预定low_resource/short_duration规则，不依据已看成绩挑向量。使用同世界固定模式网格的四单元：
Y00=Y(s0,m0)，Y10=Y(s1,m0)，Y01=Y(s0,m1)，Y11=Y(s1,m1)。
S=Y10−Y00；M=Y01−Y00；I=Y11−Y10−Y01+Y00；T=Y11−Y00=S+M+I。

每个标量单独计算，注明单位、越大/越小含义和四单元服务集合。8主世界各一个Constraint四单元，另16敏感性四单元。不是唯一因果归因、不能归LLM能力。时间分解要求四单元该时间指标均有合法值且同等服务；任何未完成则S/M/I/T均null并保留四单元状态。缺单元是evidence_error，不能插值或填0。原始成本有值但服务不同，可展示观测代价代数差，不命名节省或优势。

## 5. 服务与成本比较资格

固定请求集合E不能变化。每臂展示required/started/valid_completed请求集合；少服务导致低成本照实保留，但：
- observed_cost_delta总是candidate_cost−control_cost，仅在两臂证据完整、单位/窗口可比时有值。
- matched_service_cost_saving=control_cost−candidate_cost，要求两臂都完整有效完成同一E、相同服务质量合同、单位与窗口可比；否则null/status=unequal_service_coverage，不宣称节省。
- C2若扩展节能指标，还须两臂满足预定同等环境服务条件，单纯命令完成不够；仍限合成环境。
- task_start_wait_delta只要求双方该任务实际启动；某臂未完成并不抹去已观察的等待差。
- task_completion_latency_delta/task_tardiness_delta要求双方该任务有效完成。
- all_service_completion_delta要求双方所有E服务有效完成，部分任务latest_observed不可替代整体完工。
- 原始观测成本更低且少服务时，优势字段null，逐任务等待/迟到仍并列，不能用总计划更快掩盖个体损失。

准入、最终处置、命令完成、环境达标继续分别报告；无动作、撤回、失效物理结束不进有效服务C。0额外暴露不是0实际暴露。

## 6. 缺失和null的状态码

每个可能无值的字段必须携带value、status、required/started/completed覆盖；不用一个null吞掉所有情况。
- ok：合法观测值。
- not_started：证据完整，合同请求未真实启动。
- not_completed：证据完整，无有效完成回执。
- no_eligible_requests：预定E为空。
- no_completed_requests：E非空但有效完成集合为空，条件按时率为null；不影响以E为分母的两个主服务率为0。
- unequal_service_coverage：两臂未满足同等完整服务，节省/优势不可解释。
- incomplete_actual_vector：模式机制控制资格不足。
- out_of_scope：没有列入本版统计合同。
- evidence_error：文件/字段/事件缺失、解码或哈希错误、身份冲突、重复替换、配对缺臂/错误，硬失败，不产汇总结果。

处理顺序先证据与身份检查，再合同资格，再合法观测null。缺文件不能伪装未完成；对照缺臂不能生成收益或回退旧成绩。C4四替换的源行/政策必须一对一，旧ID仍在规范槽位中；未替换的旧错误不能进入任何有效数值。

## 7. 权重及统计单位

默认逐世界配对。主摘要若合同获准，以8世界等权1/8，先在各世界按同一固定对照算值，再按相同指标做描述性摘要；不得把24固定向量、三个selector、四政策或诊断重复当更多世界。缺有效差值时不在剩余世界重新归一化“平均收益”；完整八世界摘要null并列有效覆盖，可另标条件子集描述，但不称总体结果。

请求比例的合并计数和逐世界等权均值必须分名：pooled_request_rate与equal_world_mean_rate，分别列分子/分母/权重；空E世界不擅自重新配权。不同世界任务数不同会造成两者不同，不能互换。敏感性臂、模式向量分层各成表，不统一平均。纯开发网格描述，不按回放数给置信区间、显著性或普遍优势。

## 8. 冻结与实现门槛

本版224行身份、424对计划、24四单元和C4四映射均是元数据合同提案，未计算指标；本合同尚待复审。冻结时还须核对授权/实际向量检查、source哈希及pair固定字段执行规范；新增任何族要先枚举自己的完整运行和E，再扩scope。旧台账107行不是运行清单，旧acceptance=null不回写。

下一步适配器必须从真实事件重算并比对报告，覆盖以下负例：合法请求被一臂拒绝E不变；固定授权相同、一臂未启动一项时主率及主差值仍有值，而对应完成时延与同等服务节省无值；零完成、空E与完成但全迟到分别处理；已启动未完成等待差仍可算；少服务低成本无节省；缺文件硬错；仅实际模式机制对照受不完整向量限制；四单元少一格或时间无值；替换重复；诊断/反事实/前缀串入主队列；selector不增加世界权重。当前计数边界参考函数及合成测试不替代真实事件适配器验收。

本轮只做文档与身份计划自检，不构成指标适配器验收，不调用模型/保留集，不计算排名或跨族总分。旧草案作为历史保留。
