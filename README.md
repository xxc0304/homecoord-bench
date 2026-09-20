# HomeCoord-Bench 最小验证原型

这个目录实现数据规范 v0.3 的验证闭环：4 条种子 episode、20 条参数化变体、20 条候选任务、人工正反轨迹、确定性评测器、四种架构和 DeepSeek API 适配。人工轨迹、dry-run 和真实 API 结果在文档中分别标注，不混为一类证据。

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
- `conflict_counts`：C1–C4 冲突次数；
- `first_effective_action_latency_ms`：从任务发布到第一个产生目标正向进展且不立即违规的物理动作；
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

第二模型对照可显式指定模型名；当前已用 `deepseek-v4-pro` 完成 8 个专业 Agent 决策的兼容性试跑和 C1–C4 关键边界各 5 次初筛：

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

生成候选任务机器预审矩阵：

```powershell
python homecoord_bench/review_candidates.py
```

结果写入 `docs/HOMECOORD_BENCH_REVIEW_MATRIX_v0.1.md` 和 `homecoord_bench/results/candidate_pre_review_20260920.json`。机器预审只检查结构、引用、冲突可判定性和确定性回放准备情况；物理参数仍需人工双审和设备／模拟器校准。

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

闭环会注入外部状态事件、执行动作、更新共享状态并把轨迹交给确定性评测器。`CentralSingleAgent` 使用一个具有全局可见性和全部工具的中央 Agent；其余三种架构使用具有不同状态与工具边界的专业 Agent。设备实际持续时间和功率由环境能力表确定，模型给出的估计只作为提案元数据保存。

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

原始请求和轨迹保存在被 Git 忽略的 `homecoord_bench/runs/`。不含密钥的聚合结果保存在 `homecoord_bench/results/`。C1–C4 的关键边界配置均已各重复 20 次，当前仍属于数据校准证据。
