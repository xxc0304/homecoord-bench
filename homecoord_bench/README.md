# HomeCoord-Bench 最小验证原型

新的 C1/C3 来源可追溯数据试点见 [`docs/C1_C3_DATA_PROVENANCE_PILOT_2026-09-28.md`](../docs/C1_C3_DATA_PROVENANCE_PILOT_2026-09-28.md)；它与旧盲审草稿隔离，尚未进入正式 benchmark 计分。

这个目录实现数据规范 v0.4 的验证闭环：4 条种子 episode、20 条参数化变体、20 条候选任务、人工正反轨迹、确定性评测器、四种架构和 DeepSeek API 适配。事件模拟器另含透明的 DeadlineAwareCoordinator 对照基线；它不是新算法。人工轨迹、dry-run 和真实 API 结果在文档中分别标注，不混为一类证据。

## C1–C4 代表性任务草稿审核

`revision_drafts/20260927/` 中的 9 条 C1／C3／C4 任务仍是隔离的待审草稿，未进入正式评分数据。C2 的 HC-M06 连续换气／制热场景另存为 `HC-PAIR-C2-VENT-HEAT-REVIEW.json`，由独立物理探针运行，尚未接入通用事件矩阵。以下命令重建事件草稿、检查配对字段和工具契约，并运行五种策略的固定提案回放：

```powershell
python homecoord_bench/make_representative_revision_drafts.py
python homecoord_bench/audit_representative_revision_drafts.py
python homecoord_bench/probe_representative_revision_matrix.py
```

草稿采用 `strict-v1` 工具契约。Agent 可见的操作必须能映射到已授权工具、参数约束和对应的动作效果；事件运行时会在设备动作前拒绝越权或不完整的提案。旧 episode 不会被悄然改写为这一新契约。C1／C3 参数未校准，C4 无取消／恢复语义；C2 参数与方程也未校准，且独立模拟器的三格截止任务被乐观下界判为不可行。C1／C3／C4 九条事件草稿不含完成截止时间。C1–C4 审核材料和证据边界见 `docs/C2_SHORT_TERM_INTEGRATION_AUDIT_2026-09-27.md` 与 `docs/REPRESENTATIVE_DRAFT_REVIEW_PACKET_2026-09-27.md`。

导出 C2 冲突与匹配对照的五策略代表性时间序列，并核对状态趋势和能耗积分：

```powershell
python homecoord_bench/export_c2_trace_packet.py
```

输出 `homecoord_bench/results/c2_representative_trace_packet_20260927.json`；轨迹全部通过实现内部一致性检查仍不代表热交换／换气方程经过真实设备验证。复现完整 C2 网格用 `python homecoord_bench/probe_ventilation_heating_tradeoff.py`，参数误差探针用 `python homecoord_bench/probe_ventilation_heating_model_error.py`。

## 候选任务取舍筛查

```powershell
python homecoord_bench/audit_candidate_tradeoffs.py
python homecoord_bench/probe_capacity_deadline.py
```

第一项对 20 条候选任务及 C2/C3 的 10 条匹配安全对照运行四种架构，检查强规则基线是否已饱和、是否存在安全基线之间的非平凡取舍。第二项用一条独立的合成容量与截止时间样例检验现有评测遗漏的按时完成问题。两项均不调用模型 API，不属于人工审核或物理校准结果；设计结论和局限见 docs/CANDIDATE_TRADEOFF_AUDIT_2026-09-24.md。

运行验证：

```powershell
python -m unittest discover -s homecoord_bench/tests -v
python homecoord_bench/evaluate.py --all
python homecoord_bench/run_scripted_baselines.py
python homecoord_bench/run_protocol_pilot.py --provider dry-run
```

评测器输出：

- `final_goal_success`：结束状态是否满足目标；
- `process_valid_success`：目标满足且过程未违反硬约束；
- conflict_counts：C1–C4 冲突次数；
- `first_action_start_latency_ms`：从任务发布到第一个被接受并实际启动的设备动作，衡量命令响应；
- `first_goal_progress_latency_ms`：从任务发布到首个安全且使目标取得可测量进展的状态变化，可能包含物理工作时长；旧字段 `first_effective_action_latency_ms` 保留为它的兼容别名；
- `task_completion_time_ms`：第一次满足全部目标的时间；
- `coordination_decision_latency_ms`：首次协调决策时间，单独报告，不冒充物理响应。
- `task_service_rate`：实际完成了多少声明 `required_action` 的局部任务，用于识别安全但不执行任务的策略。

`run_scripted_baselines.py` 是人工轨迹上的架构冒烟试验，用来检查 4 条种子任务是否有区分度。它不调用 LLM，也不能被当成论文中的模型实验。

## 模型协议试跑

`run_protocol_pilot.py` 默认使用确定性假模型，验证 4 条 episode 中 8 个专业 Agent 的统一请求、结构化动作提案和 JSONL 事件记录。动作参数和前置条件使用原生 JSON `value` 字段，不在字符串中再次编码 JSON。指定供应商才会发出真实请求。

DeepSeek 首轮使用 `deepseek-flash` 和非思考模式：

```powershell
$env:DEEPSEEK_API_KEY = "在本机设置，不要写入仓库"
python homecoord_bench/run_protocol_pilot.py --provider deepseek
```

第二模型对照可显式指定模型名；当前已用 deepseek-v4-pro 完成 8 个专业 Agent 决策的兼容性试跑和 C1–C4 关键边界各 5 次初筛：

```powershell
python homecoord_bench/run_protocol_pilot.py --provider deepseek --model deepseek-v4-pro
python homecoord_bench/run_targeted_repetitions.py --provider deepseek --model deepseek-v4-pro --repetitions 5
```

OpenAI 对照仍可使用 `--provider openai`。两种适配器都使用严格 JSON Schema；DeepSeek Responses API 固定不存储响应，OpenAI 请求显式设置 `store=false`。运行日志写到已被 Git 忽略的 `homecoord_bench/runs/`，不记录 API Key。

## 最小执行闭环

四种架构的离线闭环验证：

```powershell
python homecoord_bench/run_closed_loop.py --provider dry-run
```

已实现候选任务（HC-M02、HC-M03、HC-M07、HC-M08、HC-M12、HC-M13、HC-M17、HC-M20）的四架构确定性回放：

```powershell
python homecoord_bench/run_candidate_dry_run.py
```

候选任务用 episode 内的 `action_grounding` 能力表描述动作效果，用任务内的 `action_template` 驱动确定性客户端；新增设备类型不需要修改种子任务的硬编码分派表。当前候选仍是待双审的校准样本，不能与正式金标准或真实模型结果混合报告。

容量与截止时间的受控设计实验（5 个 33 模板 × 3 种条件）：

```powershell
python homecoord_bench/run_capacity_deadline_matrix.py
```

结果写入 homecoord_bench/results/capacity_deadline_matrix_20260924.json，解释与局限见 docs/CANDIDATE_TRADEOFF_AUDIT_2026-09-24.md。这是未审核的合成设计实验；其中优先排程使用完整提案，只是可行性见证，并非在线协调基线。

针对同一矩阵运行真正按提案返回时间决策的简单在线规则：

```powershell
python homecoord_bench/run_online_deadline_baselines.py
```

结果写入 `homecoord_bench/results/online_deadline_baselines_20260924.json`。这些规则仅用于 33 容量任务；等待已发布紧急任务的优先级与 EDF 规则都解决了当前五组临界样例，因此这些样例目前不能证明需要新协调算法。另有容量感知优先级规则利用静态设备功率上界，避免在容量充足时白等。评测器另外提供动作结束时间和截止时间结果；旧完成时间仍表示目标首次满足。

首批四组冲突／无冲突配对任务及真实模型提案探索见 docs/PAIRED_TASK_BATCH_V1_2026-09-26.md。保存的充电／热水提案又经四种简单在线规则复核；任务级时延取舍与物理参数审查见 docs/RECORDED_POLICY_AND_PHYSICS_AUDIT_2026-09-26.md，运行入口是 homecoord_bench/probe_recorded_online_policies_v1.py。当前任务仍是合成调度单元测试，不能把即时写入的温度／电量目标视作实测设备完成。

独立的 v2 试验按电池容量、热水量、输入功率与效率计算工作持续时间，并在工作结束时才记为物理目标完成。任务与结果分别在 homecoord_bench/data/pilot_physical_v2/、homecoord_bench/results/physical_capacity_v2.json；说明见 docs/PHYSICAL_COMPLETION_PILOT_V2_2026-09-26.md。它解决了 v1 秒级工作量的量纲问题，但参数仍是假设而非设备校准。

### 离散事件虚拟环境原型

`runtime/event_simulator.py` 把任务发布、异步提案返回、外部状态变化、设备启动和物理完成放到一条虚拟时间线上。它用记录的模型调用时延安排提案返回顺序；API 决策接口本身仍同步执行，因此这能重放逻辑并发，不能证明真实并发调用速度。对于持续动作，环境支持在 `action_grounding` 中分别声明 `start_effects` 和 `completion_effects`；没有拆分标注的旧候选仍按旧语义解释，不能用作设备中间状态证据。

运行当前 34 条种子、配对、物理假设与候选 episode 的五策略冒烟矩阵：

```powershell
python homecoord_bench/run_event_simulation_matrix.py
```

结果写入 `homecoord_bench/results/event_simulation_matrix_20260926.json`，原型说明、结果边界和已知问题见 `docs/EVENT_SIMULATION_RUNTIME_PILOT_2026-09-26.md`。事件排序与评测映射审查见 `docs/EVENT_SIMULATOR_SEMANTICS_AUDIT_2026-09-27.md`。该矩阵使用 DryRunClient，不调用 API；候选仍未双审，物理参数仍未校准。运行期间外部变化导致硬约束失效时，当前原型会统计违规区间，但不会自动中断设备动作。

把工作区中已有的 DeepSeek 提案与实测调用时延离线重放到同一事件环境：

```powershell
python homecoord_bench/run_recorded_event_replay.py
```

脚本不发出网络请求或新增 API 费用，固定同一组提案，只重放不同协调策略和成对环境条件。结果位于 homecoord_bench/results/recorded_event_replay_20260926.json；这不是每种架构各自重新询问模型的端到端比较，也不含真实设备时延。详细口径见 docs/RECORDED_EVENT_REPLAY_PILOT_2026-09-26.md。

检查各 episode 是否明确区分动作启动与完成效果：

```powershell
python homecoord_bench/audit_event_grounding.py
```

该检查输出 `homecoord_bench/results/event_grounding_audit_20260926.json`，用于列出仍需人工核对的长动作语义；它只检查标注完整性，不自动证明设备具有相应物理状态。

一条命令运行全套离线事件环境回归测试，并刷新事件矩阵、DeepSeek 提案回放、截止时间扫描、提案顺序反事实和生命周期审计：

```powershell
python homecoord_bench/run_event_pilot_suite.py
```

当前 HomeCoord 离线套件运行 107 项测试和 674 次确定性仿真／离线回放，不调用模型 API。另有 21 条 SimuHome HVAC A–E 本地适配试点，其中 21 条通过轨迹结构检查、7 个重复组完全一致；该试点也不调用模型 API。HomeCoord 固定提案回放到 SimuHome 的两批试验各含 12 条轨迹，结构审计均 12/12 有效，但只有 1/4 个重复组逐状态完全一致，详情见 docs/HOMECOORD_HVAC_PAIR_SIMUHOME_REPLAY_2026-09-27.md。候选 episode 审计、外部事件目标审计、期限和基线覆盖结果分别写入 homecoord_bench/results/event_episode_validation_20260926.json、homecoord_bench/results/external_goal_credit_audit_20260927.json、homecoord_bench/results/deadline_feasibility_audit_20260926.json、homecoord_bench/results/baseline_coverage_audit_20260926.json，离线套件汇总写入 homecoord_bench/results/event_pilot_suite_20260926.json。SimuHome 试点报告见 docs/SIMUHOME_HVAC_RUNTIME_PILOT_2026-09-27.md。

检查未来家庭模拟器适配产生的逐运行 JSONL 轨迹（每个运行一个文件）：

```powershell
python homecoord_bench/audit_simulator_adapter_trace.py run1.jsonl run2.jsonl --output adapter_trace_audit.json
```

审计器检查时钟单调性、proposal—command 关联、可观察执行顺序和固定配置重复运行的一致性；通过只说明轨迹可复核，不证明物理真实性或许可证适用。SimuHome HVAC 的预注册试验卡见 docs/SIMUHOME_HVAC_MINIMAL_TRIAL_SPEC_2026-09-26.md，运行结果见 docs/SIMUHOME_HVAC_RUNTIME_PILOT_2026-09-27.md。

当前环境是可控的协调事件实验台，不是完整家庭模拟器。是否复用 SimuHome 或其他环境，以及 3–5 条代表 episode 的接口／动力学验收标准，见 [`docs/SIMULATOR_ADAPTER_SPIKE_PLAN_2026-09-26.md`](../docs/SIMULATOR_ADAPTER_SPIKE_PLAN_2026-09-26.md)。

M01–M20 候选任务的首轮逐条语义复核见 docs/CANDIDATE_TASK_FIRST_PASS_REVIEW_2026-09-27.md。该文档只是单轮研究助理审阅，不替代两位独立审核者；候选 JSON 均保持 candidate_dry_run。特别是 M06–M10 的 environment_effects 尚未进入执行器，不应把这些任务的 C2 标签作为已验证物理冲突。

HC-M06 的开窗换气／制热隔离探针补入连续 CO₂ 与温度变化、关窗动作和用电指标，并与无须换气的任务配对。该探针显示合成参数下有完成时间—用电取舍，但准确动力学已知时简单选择即可处理；它不属于正式事件运行时或方法创新证据。设计、结果和局限见 docs/VENTILATION_HEATING_TRADEOFF_PROBE_2026-09-27.md。

后续参数误差交叉试验发现：在未校准的合成网格中，简单预测选择也会因估计偏差错过截止时间或多耗电；现有 SimuHome 制冷轨迹不能校准开窗、CO₂ 与制热联动。结果及所需观测见 docs/VENTILATION_HEATING_MODEL_ERROR_PROBE_2026-09-27.md。

为接入后续外部模拟或设备轨迹，已增加独立的物理轨迹输入契约和配对评测器。`python homecoord_bench/score_physical_traces.py INPUT.json --output AUDIT.json` 会检查来源、采样、初态与冲突／对照配对，并从轨迹重算首次达标时间和加热用电。数据设计与证据门槛见 docs/HC_M06_PHYSICAL_DATA_AND_EVALUATION_SPEC_V0.1.md；现有 8 条输入只是未校准的合成契约样例。

当前主线优先级与 C1/C3/C4、物理后端、模型调用之间的先后关系见 docs/NEXT_MILESTONE_DECISION_2026-09-27.md。HC-M06 的后续物理验证保持探索分支，不替代代表性任务的独立复核。

生成三个代表性候选的隔离复核草稿（C1 HVAC 冲突／安全配对、C3 低／高容量配对、C4 清洁任务的四个事件时序臂）：

```powershell
python homecoord_bench/make_representative_revision_drafts.py
```

草稿写入 homecoord_bench/revision_drafts/20260927/，该目录位于正式数据 data/ 之外，不进入 benchmark 评分。当前草稿的确定性回归测试验证任务结构与指标区分，不验证现实设备参数或领域双审结论。设计和初轮结果见 docs/REPRESENTATIVE_TASK_REVISION_SPEC_2026-09-27.md。

对 9 条隔离草稿运行五种策略、每个配置三次重复的机制矩阵：

```powershell
python homecoord_bench/probe_representative_revision_matrix.py
```

逐次结果写入 `homecoord_bench/results/representative_revision_baseline_matrix_20260927.json`，发现与合成证据边界见 `docs/REPRESENTATIVE_REVISION_BASELINE_MATRIX_2026-09-27.md`。135 次 DryRun 中 45/45 配置重复一致；这只检查固定提案、合成时延下的基线行为，不是模型/API、设备校准或领域审核结果。

检查另一 Agent 的动作开始／完成效果是否使在途动作的显式前提失效：

```powershell
python homecoord_bench/probe_agent_caused_inflight_invalidation.py
```

探针读取 C1 冲突／安全配对草稿，在内存中给制冷动作增加持续运行前提，不改源文件。两种动作效果时点 × 两个条件 × 五策略 × 三重复，共 60 次 DryRun；独立执行在冲突臂各出现一次跨 Agent 在途失效，Constraint 和安全配对均为零。逐次结果与局限见 `homecoord_bench/results/agent_caused_inflight_probe_20260927.json` 和 `docs/AGENT_CAUSED_INFLIGHT_PROBE_2026-09-27.md`。这是指标校验；简单协调已解决该例。

M16–M20 的 34 状态变化与动作开始边界离线探针：

```powershell
python homecoord_bench/probe_c4_timing_boundary_20260927.py
```

180 次运行、60 个配置单元、每单元 3 次重复；注入 300/400/600 ms 的测试延迟，不访问模型 API。结果见 homecoord_bench/results/c4_timing_boundary_probe_20260927.json，解释边界见 docs/C4_TIMING_BOUNDARY_PILOT_2026-09-27.md。运行时分开报告启动前过期拒绝、在途前置条件失效和在途动作期间安全状态转坏；这些都不是模型／设备延迟实验，也不改变候选双审状态。

自动找出初态或外部事件在没有 Agent 动作时即可满足全部目标的 episode：

```powershell
python homecoord_bench/audit_external_goal_credit.py
```

当前 34 条 episode 中有 4 条由外部事件满足全部目标；报告保存在 `homecoord_bench/results/external_goal_credit_audit_20260927.json`。该审计用于提醒研究者把“环境本身达到目标”和“Agent 服务了任务”分开计分。

重放已保存的 EV／热水器模型提案，扫描五档离家截止时间、低／高功率容量和四种在线策略：

```powershell
python homecoord_bench/probe_event_deadline_sensitivity.py
```

结果写入 `homecoord_bench/results/event_deadline_sensitivity_20260926.json`；设计与解释边界见 `docs/EVENT_DEADLINE_SENSITIVITY_PILOT_2026-09-26.md`。该分析重复使用 5 组保存的 DeepSeek 提案，不发送 API 请求；截止时间和功率仍为合成设定，不能作设备性能或新算法效果结论。

单独测试异步返回顺序是否改变调度结果：

```powershell
python homecoord_bench/probe_proposal_order_sensitivity.py
```

该反事实探针固定原模型决策，只交换两名 Agent 的已记录调用延迟，对低／高容量和四种策略运行 80 次。它检查“哪个提案先返回”本身的作用，不是新模型采样。

DeadlineAwareCoordinator 是强基线：它只等待当前已发布任务的提案全部返回，按最早截止时间、再按任务优先级排序，并复用约束协调器的安全／容量检查；收集阶段的额外等待也计入事件时间。它用于检验简单规则能否解释或消除一个表面上的安全—截止时间取舍，不代表论文提出的方法，也不读取未来未发布任务。

设备命令回执、物理执行和状态上报分离的合成试验：

```powershell
python homecoord_bench/probe_execution_uncertainty.py
```

逐事件结果见 homecoord_bench/results/execution_uncertainty_pilot_20260924.json，设计判断见 docs/EXECUTION_UNCERTAINTY_PILOT_2026-09-24.md。主动查询真实设备状态的简单规则已解决全部物理上可行的参数格点，因此本试验只确认评测缺口，不证明需要新算法。

HC-M07 的持续状态与多步通风／制冷试验（不改动旧候选任务）：

```powershell
python homecoord_bench/probe_persistent_state.py
```

逐事件结果见 `homecoord_bench/results/persistent_state_pilot_20260924.json`，设计与局限见 `docs/PERSISTENT_STATE_PILOT_2026-09-24.md`。原 32 只检查动作区间重叠，会把窗户仍开着时启动空调的轨迹判为零冲突；独立新环境加入了渐进 3O₂ 变化和关窗动作。简单的持续状态检查已解决其中全部可行格点，因此尚无新算法证据。

中途下雨造成通风计划失效的动态修复小试验：

```powershell
python homecoord_bench/probe_dynamic_repair.py
```

结果见 homecoord_bench/results/dynamic_repair_pilot_20260924.json 和 docs/DYNAMIC_REPAIR_PILOT_2026-09-24.md。脚本同时比较状态门控、任务特定反应规则和两种理想化重规划模板；后两者不是真实模型或通用规划器，不能据此报告局部修复的时延优势。

生成候选任务机器预审矩阵：

```powershell
python homecoord_bench/review_candidates.py
```

结果写入 docs/HOMECOORD_BENCH_REVIEW_MATRIX_v0.1.md 和 homecoord_bench/results/candidate_pre_review_20260920.json。机器预审只检查结构、引用、冲突可判定性和确定性回放准备情况；物理参数仍需人工双审和设备／模拟器校准。

没有真实设备时运行合成参数敏感性分析：

```powershell
python homecoord_bench/annotate_synthetic_calibration.py
python homecoord_bench/run_calibration_sweep.py --replicates 10
```

该 sweep 只改变动作持续时间和功耗的声明范围，用于检查结论是否依赖固定占位值；输出明确标记为 `sensitivity_only`，不能作为真实设备性能结果。

真实 DeepSeek 小样本闭环：

```powershell
python homecoord_bench/run_closed_loop.py --provider deepseek
```

闭环会注入外部状态事件、执行动作、更新共享状态并把轨迹交给确定性评测器。CentralSingleAgent 使用一个具有全局可见性和全部工具的中央 Agent；其余三种架构使用具有不同状态与工具边界的专业 Agent。设备实际持续时间和功率由环境能力表确定，模型给出的估计只作为提案元数据保存。

## 参数扫描与重复校准

运行 20 条信息可见性、事件时机和冲突边界变体：

```powershell
python homecoord_bench/run_variant_sweep.py --provider dry-run
python homecoord_bench/run_variant_sweep.py --provider deepseek
```

只重复能够区分机制的关键临界配置：

```powershell
python homecoord_bench/run_targeted_repetitions.py --provider deepseek --suite core --repetitions 20
python homecoord_bench/run_targeted_repetitions.py --provider deepseek --suite c2c3 --repetitions 20
```

聚合原始轨迹、模型时延、格式重试、Token、费用、冲突和任务服务率：

```powershell
python homecoord_bench/analyze_variant_sweep.py <run_dir> <result.json>
```

C2/C3 边界和强约束规则基线：

```powershell
python homecoord_bench/run_conflict_family_sweep.py --provider dry-run
python homecoord_bench/run_conflict_family_sweep.py --provider deepseek
```

同一批专业 Agent 提案的反事实架构回放：

```powershell
python homecoord_bench/run_counterfactual_replay.py <run_dir> <result.json> --family direct_device_conflict --target-architecture RuleCoordinator
python homecoord_bench/run_counterfactual_replay.py <run_dir> <result.json> --family indirect_environment_conflict --target-architecture ConstraintCoordinator
```

原始请求和轨迹保存在 homecoord_bench/runs/。不含密钥的聚合结果保存在 homecoord_bench/results/。C1–C4 的关键边界配置均已各重复 20 次，当前仍属于数据校准证据。
