# HomeCoord-Bench 候选任务预审矩阵 v0.1

这是一份机器预审结果，不等同于人工双审或物理真实性认证。人工审核者需要分别确认动作语义、优先级、冲突规则和效果参数。

| Episode | 家族 | 结构/引用检查 | 冲突可判定 | 校准状态 | 机器预审 | 审核人 A | 审核人 B |
|---|---|---|---|---|---|---|---|
| HC-M01 | direct_device_conflict | 通过 | 通过 | synthetic_range | 通过 | 待填写 | 待填写 |
| HC-M02 | direct_device_conflict | 通过 | 通过 | synthetic_range | 通过 | 待填写 | 待填写 |
| HC-M03 | direct_device_conflict | 通过 | 通过 | synthetic_range | 通过 | 待填写 | 待填写 |
| HC-M04 | direct_device_conflict | 通过 | 通过 | synthetic_range | 通过 | 待填写 | 待填写 |
| HC-M05 | direct_device_conflict | 通过 | 通过 | synthetic_range | 通过 | 待填写 | 待填写 |
| HC-M06 | indirect_environment_conflict | 通过 | 通过 | synthetic_range | 通过 | 待填写 | 待填写 |
| HC-M07 | indirect_environment_conflict | 通过 | 通过 | synthetic_range | 通过 | 待填写 | 待填写 |
| HC-M08 | indirect_environment_conflict | 通过 | 通过 | synthetic_range | 通过 | 待填写 | 待填写 |
| HC-M09 | indirect_environment_conflict | 通过 | 通过 | synthetic_range | 通过 | 待填写 | 待填写 |
| HC-M10 | indirect_environment_conflict | 通过 | 通过 | synthetic_range | 通过 | 待填写 | 待填写 |
| HC-M11 | resource_capacity_conflict | 通过 | 通过 | synthetic_range | 通过 | 待填写 | 待填写 |
| HC-M12 | resource_capacity_conflict | 通过 | 通过 | synthetic_range | 通过 | 待填写 | 待填写 |
| HC-M13 | resource_capacity_conflict | 通过 | 通过 | synthetic_range | 通过 | 待填写 | 待填写 |
| HC-M14 | resource_capacity_conflict | 通过 | 通过 | synthetic_range | 通过 | 待填写 | 待填写 |
| HC-M15 | resource_capacity_conflict | 通过 | 通过 | synthetic_range | 通过 | 待填写 | 待填写 |
| HC-M16 | stale_state_action | 通过 | 通过 | synthetic_range | 通过 | 待填写 | 待填写 |
| HC-M17 | stale_state_action | 通过 | 通过 | synthetic_range | 通过 | 待填写 | 待填写 |
| HC-M18 | stale_state_action | 通过 | 通过 | synthetic_range | 通过 | 待填写 | 待填写 |
| HC-M19 | stale_state_action | 通过 | 通过 | synthetic_range | 通过 | 待填写 | 待填写 |
| HC-M20 | stale_state_action | 通过 | 通过 | synthetic_range | 通过 | 待填写 | 待填写 |

## 人工审核重点

1. 检查动作效果、持续时间和功耗是否有模拟器、设备日志或公开规格来源。
2. 检查冲突规则是否代表真实的安全、舒适或资源约束，而不是为了制造冲突而添加。
3. 检查拒绝、延迟或过期动作后的任务服务率是否符合任务语义。
4. 两名审核者独立填写后再讨论分歧；在此之前任务保持 `candidate_dry_run`。
