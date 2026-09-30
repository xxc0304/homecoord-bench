# 代表性任务修订草稿：全基线机制审计

日期：2026-09-27
状态：隔离草稿的离线固定时延行为检查；不是物理性能实验、独立领域双审或算法收益评估。

## 设计与复现

读取 9 条 HC-M01／M11／M16 修订草稿，先逐条核对落盘 JSON 与生成器对象完全一致，再对每条草稿运行 IndependentMultiAgent、RuleCoordinator、ConstraintCoordinator、DeadlineAwareCoordinator 和 CentralSingleAgent。每个 episode／策略组合重复 3 次，共 135 次确定性 DryRun。全部条件使用 300 ms 固定提案延迟；C4 提交前事件设在 350 ms，在途事件设在 500 ms。没有模型 API 或真实设备。报告中的时延、功率与事件时点均为合成设定。

输入完整性：9/9 个落盘草稿与生成器逐字段相同；所有 45 个 episode／策略配置的三次轨迹与结果均完全一致。原始 HC-M01、HC-M11、HC-M16 候选文件没有被此脚本修改。

## 主要结果

| 配对 | Independent | Constraint | 解释 |
|---|---|---|---|
| C1 HVAC 冲突／安全 | 冲突臂 C1=1；能源动作完成 1100 ms | 冲突臂 C1=0；能源动作完成 6900 ms | 冲突臂协调将能源动作延后 5,800 ms；安全配对两者 C1 均为 0，Constraint 未增加能源动作完成时间。 |
| C3 容量低／高配对 | 低容量 C3=1；高容量 C3=0 | 低容量 C3=0；高容量 C3=0 | 低容量下 RuleCoordinator 也保留 C3 冲突，Constraint 将其消除并使完成时间增加 900 ms；高容量安全对照没有额外串行等待。 |
| C4 提交前／在途／安全对照 | 提交前 stale 拒绝=1；在途安全违规时长=2900 ms | 提交前 stale 拒绝=1；在途安全违规时长=2900 ms | 提交前条件下策略均拒绝必要清洁动作；在途条件下 Constraint 未取消已启动动作，出现 2,900 ms 违规；无事件对照没有违规。DeadlineAware 在在途条件避免违规，但必要清洁任务未服务。 |

## 全部策略明细

| Episode | 策略 | 过程有效 | 冲突 C1/C3/C4 | 首动作启动 ms | 任务服务 | 安全违规时长 ms |
|---|---|---:|---:|---:|---|---:|
| HC-PAIR-C1-HVAC-CONFLICT | IndependentMultiAgent | 0 | 1/0/0 | 400 | comfort_cool:1, peak_off:1 | 5800 |
| HC-PAIR-C1-HVAC-CONFLICT | RuleCoordinator | 1 | 0/0/0 | 400 | comfort_cool:1, peak_off:1 | 0 |
| HC-PAIR-C1-HVAC-CONFLICT | ConstraintCoordinator | 1 | 0/0/0 | 400 | comfort_cool:1, peak_off:1 | 0 |
| HC-PAIR-C1-HVAC-CONFLICT | DeadlineAwareCoordinator | 1 | 0/0/0 | 600 | comfort_cool:1, peak_off:1 | 0 |
| HC-PAIR-C1-HVAC-CONFLICT | CentralSingleAgent | 1 | 0/0/0 | 400 | comfort_cool:1, peak_off:1 | 0 |
| HC-PAIR-C1-HVAC-SAFE | IndependentMultiAgent | 1 | 0/0/0 | 400 | comfort_cool:1, peak_off:1 | 0 |
| HC-PAIR-C1-HVAC-SAFE | RuleCoordinator | 1 | 0/0/0 | 400 | comfort_cool:1, peak_off:1 | 0 |
| HC-PAIR-C1-HVAC-SAFE | ConstraintCoordinator | 1 | 0/0/0 | 400 | comfort_cool:1, peak_off:1 | 0 |
| HC-PAIR-C1-HVAC-SAFE | DeadlineAwareCoordinator | 1 | 0/0/0 | 400 | comfort_cool:1, peak_off:1 | 0 |
| HC-PAIR-C1-HVAC-SAFE | CentralSingleAgent | 1 | 0/0/0 | 400 | comfort_cool:1, peak_off:1 | 0 |
| HC-PAIR-C3-HOME-POWER-EXACT-CAPACITY-LIMIT | IndependentMultiAgent | 1 | 0/0/0 | 400 | bedroom_cool:1, study_light:1 | 0 |
| HC-PAIR-C3-HOME-POWER-EXACT-CAPACITY-LIMIT | RuleCoordinator | 1 | 0/0/0 | 400 | bedroom_cool:1, study_light:1 | 0 |
| HC-PAIR-C3-HOME-POWER-EXACT-CAPACITY-LIMIT | ConstraintCoordinator | 1 | 0/0/0 | 400 | bedroom_cool:1, study_light:1 | 0 |
| HC-PAIR-C3-HOME-POWER-EXACT-CAPACITY-LIMIT | DeadlineAwareCoordinator | 1 | 0/0/0 | 500 | bedroom_cool:1, study_light:1 | 0 |
| HC-PAIR-C3-HOME-POWER-EXACT-CAPACITY-LIMIT | CentralSingleAgent | 1 | 0/0/0 | 400 | bedroom_cool:1, study_light:1 | 0 |
| HC-PAIR-C3-HOME-POWER-OVER-CAPACITY | IndependentMultiAgent | 0 | 0/1/0 | 400 | bedroom_cool:1, study_light:1 | 0 |
| HC-PAIR-C3-HOME-POWER-OVER-CAPACITY | RuleCoordinator | 0 | 0/1/0 | 400 | bedroom_cool:1, study_light:1 | 0 |
| HC-PAIR-C3-HOME-POWER-OVER-CAPACITY | ConstraintCoordinator | 1 | 0/0/0 | 400 | bedroom_cool:1, study_light:1 | 0 |
| HC-PAIR-C3-HOME-POWER-OVER-CAPACITY | DeadlineAwareCoordinator | 1 | 0/0/0 | 500 | bedroom_cool:1, study_light:1 | 0 |
| HC-PAIR-C3-HOME-POWER-OVER-CAPACITY | CentralSingleAgent | 1 | 0/0/0 | 400 | bedroom_cool:1, study_light:1 | 0 |
| HC-PAIR-C3-HOME-POWER-SAFE-PARALLEL-CONTROL | IndependentMultiAgent | 1 | 0/0/0 | 400 | bedroom_cool:1, study_light:1 | 0 |
| HC-PAIR-C3-HOME-POWER-SAFE-PARALLEL-CONTROL | RuleCoordinator | 1 | 0/0/0 | 400 | bedroom_cool:1, study_light:1 | 0 |
| HC-PAIR-C3-HOME-POWER-SAFE-PARALLEL-CONTROL | ConstraintCoordinator | 1 | 0/0/0 | 400 | bedroom_cool:1, study_light:1 | 0 |
| HC-PAIR-C3-HOME-POWER-SAFE-PARALLEL-CONTROL | DeadlineAwareCoordinator | 1 | 0/0/0 | 500 | bedroom_cool:1, study_light:1 | 0 |
| HC-PAIR-C3-HOME-POWER-SAFE-PARALLEL-CONTROL | CentralSingleAgent | 1 | 0/0/0 | 400 | bedroom_cool:1, study_light:1 | 0 |
| HC-PAIR-C4-CLEAN-INFLIGHT | IndependentMultiAgent | 0 | 0/0/0 | 400 | bedroom_clean:1, bedroom_occupancy:1 | 2900 |
| HC-PAIR-C4-CLEAN-INFLIGHT | RuleCoordinator | 0 | 0/0/0 | 400 | bedroom_clean:1, bedroom_occupancy:0 | 2900 |
| HC-PAIR-C4-CLEAN-INFLIGHT | ConstraintCoordinator | 0 | 0/0/0 | 400 | bedroom_clean:1, bedroom_occupancy:0 | 2900 |
| HC-PAIR-C4-CLEAN-INFLIGHT | DeadlineAwareCoordinator | 0 | 0/0/0 | 700 | bedroom_clean:0, bedroom_occupancy:1 | 0 |
| HC-PAIR-C4-CLEAN-INFLIGHT | CentralSingleAgent | 0 | 0/0/0 | 400 | bedroom_clean:1, bedroom_occupancy:1 | 2900 |
| HC-PAIR-C4-CLEAN-NO-EVENT | IndependentMultiAgent | 1 | 0/0/0 | 400 | bedroom_clean:1, bedroom_occupancy:1 | 0 |
| HC-PAIR-C4-CLEAN-NO-EVENT | RuleCoordinator | 1 | 0/0/0 | 400 | bedroom_clean:1, bedroom_occupancy:1 | 0 |
| HC-PAIR-C4-CLEAN-NO-EVENT | ConstraintCoordinator | 1 | 0/0/0 | 400 | bedroom_clean:1, bedroom_occupancy:1 | 0 |
| HC-PAIR-C4-CLEAN-NO-EVENT | DeadlineAwareCoordinator | 1 | 0/0/0 | 700 | bedroom_clean:1, bedroom_occupancy:1 | 0 |
| HC-PAIR-C4-CLEAN-NO-EVENT | CentralSingleAgent | 1 | 0/0/0 | 400 | bedroom_clean:1, bedroom_occupancy:1 | 0 |
| HC-PAIR-C4-CLEAN-POSTCOMPLETE | IndependentMultiAgent | 1 | 0/0/0 | 400 | bedroom_clean:1, bedroom_occupancy:1 | 0 |
| HC-PAIR-C4-CLEAN-POSTCOMPLETE | RuleCoordinator | 1 | 0/0/0 | 400 | bedroom_clean:1, bedroom_occupancy:1 | 0 |
| HC-PAIR-C4-CLEAN-POSTCOMPLETE | ConstraintCoordinator | 1 | 0/0/0 | 400 | bedroom_clean:1, bedroom_occupancy:1 | 0 |
| HC-PAIR-C4-CLEAN-POSTCOMPLETE | DeadlineAwareCoordinator | 1 | 0/0/0 | 700 | bedroom_clean:1, bedroom_occupancy:1 | 0 |
| HC-PAIR-C4-CLEAN-POSTCOMPLETE | CentralSingleAgent | 1 | 0/0/0 | 400 | bedroom_clean:1, bedroom_occupancy:1 | 0 |
| HC-PAIR-C4-CLEAN-PRECOMMIT | IndependentMultiAgent | 0 | 0/0/0 | 700 | bedroom_clean:0, bedroom_occupancy:1 | 0 |
| HC-PAIR-C4-CLEAN-PRECOMMIT | RuleCoordinator | 0 | 0/0/0 | 700 | bedroom_clean:0, bedroom_occupancy:1 | 0 |
| HC-PAIR-C4-CLEAN-PRECOMMIT | ConstraintCoordinator | 0 | 0/0/0 | 700 | bedroom_clean:0, bedroom_occupancy:1 | 0 |
| HC-PAIR-C4-CLEAN-PRECOMMIT | DeadlineAwareCoordinator | 0 | 0/0/0 | 700 | bedroom_clean:0, bedroom_occupancy:1 | 0 |
| HC-PAIR-C4-CLEAN-PRECOMMIT | CentralSingleAgent | 0 | 0/0/0 | 700 | bedroom_clean:0, bedroom_occupancy:1 | 0 |

## 结论边界

这批运行说明所定义的冲突与安全对照在固定提案和所设合成时间线上可被当前评测器区分，并展示了三种不同结果：Constraint 可用串行化消除 C1/C3 冲突；DeadlineAware 的等待能避开部分 C4 在途违规，但可能牺牲任务服务；设备启动前的动作前提检查会安全拒绝过期清洁提案。C4 草稿不支持中断、停止延迟、补偿或恢复，因此不能据此声称完成了动态局部修复评估。

当前结果仍不证明现实设备参数、模型响应分布、一般家庭场景泛化或新算法必要性。草稿未进入正式评分，尚未领域双审；下一步需人工核实动作效果／时长／功率来源、工具权限和用户目标，再冻结版本进行独立复核。

完整逐次结果与输入哈希：homecoord_bench/results/representative_revision_baseline_matrix_20260927.json。复跑：python homecoord_bench/probe_representative_revision_matrix.py。
