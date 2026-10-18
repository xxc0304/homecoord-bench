# HomeCoord-Bench 本地版本差异审计

日期：2026-09-28。状态：先完成只读差异审计，随后按 SHA256 清单迁入 HomeCoord 源码、数据契约、测试及 11 份限定存档结果；未迁移运行日志或配置密钥。

## 仓库边界

- 独立研究仓库：`C:\Users\QVQ\Documents\ChatGPT\homecoord-bench`，远端 `xxc0304/homecoord-bench`，最后提交 `0dda633`（2026-09-20）。写本清单之前工作树为空；本次新增的路线图和设计文档保持本地未提交。
- 后续试点所在旧工作目录：`C:\Users\QVQ\Documents\ChatGPT\agent-research`，远端是另一项目 `xxc0304/smart-home-multi-agent-research`。该目录有大量尚未提交的修改和新文件。它是本次事实核对的来源，不等于独立仓库已经具备相同功能。
- 用户要求两项目隔离；不得把旧目录的全部修改直接复制或推送至独立仓库。

## 已核实、但独立仓库缺失的关键试点

| 主题 | 旧目录的主要入口／记录 | 当前可用结论 | 迁移前必须检查 |
|---|---|---|---|
| 事件运行时与强基线 | `homecoord_bench/runtime/event_simulator.py`；相应测试 | 支持逻辑异步提案、状态事件、动作起止、共同安全门控、设备锁／约束／期限／容量感知基线 | 依赖文件、schema、测试必须一起核对；不直接覆盖独立仓库旧实现 |
| C1/C3 来源标注候选 | `homecoord_bench/generate_provenance_pilot.py`；`docs/C1_C3_DATA_PROVENANCE_PILOT_2026-09-28.md` | 5 条配对候选可通过契约和确定性回放；不是正式数据 | 审核状态、来源许可、未校准参数、旧草稿版本 |
| C1 SimuHome 对照 | `docs/C1_SIMUHOME_C3_SOURCE_AUDIT_2026-09-28.md` | 只支持 HVAC 命令时序的符号交叉检查 | 不能解释成真实室温或毫秒延迟 |
| C2 连续环境 | `homecoord_bench/probe_c2_recorded_model_physics.py`；`docs/C2_RECORDED_MODEL_PHYSICS_PILOT_2026-09-28.md` | 真实模型初始提案接入未校准连续方程；期限／能耗取舍随假设参数改变 | 联合轨迹或可复现后端缺失；不得写成家庭物理规律 |
| C3 三 Agent 容量 | `homecoord_bench/probe_c3_three_load_model.py`；`docs/C3_THREE_LOAD_REAL_PROPOSAL_PILOT_2026-09-28.md` | 三任务排序与部分并行可测；准确公开功率条件下强规则已解决该构造条件 | 固定负载、人工期限及家庭容量缺现场来源 |
| C4 消息停机 | `homecoord_bench/probe_c4_agent_message.py`；`docs/C4_AGENT_MESSAGE_SAFETY_PILOT_2026-09-28.md` | 第二 Agent 消息确实进入执行决策；事件后 LLM 报告过慢，不适合作紧急停机主路径 | 机器人停机、通信、事件时序为合成；需转向提前预约和恢复服务 |

逐项路径核对时，上表所列 11 个关键代码／报告文件在旧目录存在、在独立仓库不存在。旧目录的重复模型调用是同一模板的提案与时延采样，不是独立家庭样本。任何结果迁移都应连同任务输入、提案日志、策略版本、证据等级和测试记录核对。

## 安全迁移顺序

1. 先冻结独立仓库当前提交和旧目录所需文件的哈希、依赖图与数据口径。
2. 按“运行时＋schema＋测试”最小闭环迁移；在独立仓库运行原有测试、新增相关测试与代表性回放，不改变旧目录。
3. 再迁移已核对的候选任务、试点脚本及去敏结果；按 `candidate`／`synthetic_stress`／`source_anchored` 明确分层。原始模型请求与响应在公开或推送前单独检查敏感信息。
4. 更新独立仓库 README、实验入口和结果索引；不能沿用 9 月 20 日的旧“当前状态”陈述。
5. 经人工审核和环境参数核对后，才将任务升级为正式 benchmark 数据。用户未要求上传时不推送 GitHub。

## 审计时决策（迁移前）

本轮先完成设计与版本审计，不做盲目整库迁移。下一份《12 种试点任务结构》是未来任务说明，独立仓库当前尚不能运行其中的大部分任务。

## 2026-09-28 执行更新

已按 docs/LOCAL_SOURCE_MIGRATION_MANIFEST_2026-09-28.json 复制 193 个文件（含补齐的四份测试输入），逐文件校验 SHA256；未删除或移动旧目录文件。独立仓库完整离线测试 162 项通过。12 种结构中 7 种有部分合成机制试验，5 种尚无可执行 episode；详情见 docs/PILOT_12_STRUCTURE_AUDIT_2026-09-28.md。本更新替代上文尚未迁移的历史状态，不表示所有历史结果或文档已同步。



