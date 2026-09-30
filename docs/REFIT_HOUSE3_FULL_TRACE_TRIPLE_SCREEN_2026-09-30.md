# REFIT House 3 全量审计与九通道三路共现筛查

日期：2026-09-30。状态：**完整清洗轨迹已校验并完成描述性筛查；官方 House 3 Appliance 通道映射仍未核实。因此本报告只报告原始通道编号，不对具体设备作标签。**

## 数据身份与质量

- 来源：REFIT cleaned data，Zenodo DOI [10.5281/zenodo.5063428](https://zenodo.org/records/5063428)，文件 `CLEAN_House3.csv`，许可 CC BY 4.0。
- 文件大小：407,273,065 bytes；发布方 MD5：`ab6e34ea386eb4563bfcb9762619dc8f`；SHA-256：`3694186fd607a779d90dc34f834db908c152a86cfb0fd32e4bf009d86e444e97`。
- 全量 6,994,594 行；`Issues=1` 为 408,627 行（5.842%），其余 6,585,967 行 `Issues=0`；无无效质量标志。
- 按 8 秒名义采样间隔审计，超过 16 秒的相邻时间间隔有 12,447 处，最大间隔 3,594,416 秒。九路 Appliance 数值均可解析且无负值。
- House 3 总表据论文受太阳能干扰，因此本次只筛 Appliance 设备分表，不使用 Aggregate 推断配电预算。

全量审计机器记录：[refit_house3_source_audit_20260930.json](../homecoord_bench/results/refit_house3_source_audit_20260930.json)。

## 筛查规则

脚本 [`extract_refit_triple_coactivity_full_trace.py`](../homecoord_bench/extract_refit_triple_coactivity_full_trace.py) 对九路 `Appliance1`–`Appliance9` 枚举全部 84 种三通道组合。分别在 50、100、300 W 阈值下，要求同一时间行的三路均达到阈值；`Issues=1` 行排除并切断片段；任意相邻时间戳间隔超过 16 秒也切断片段。片段估算时长按末行减首行再加 8 秒计算。三种阈值只是探索性功率门槛，不代表设备额定功率或物理安全限值。

边界可核查的定义是：片段前后紧邻的记录均为 `Issues=0`、时间间隔不超过 16 秒，且至少一路低于该次筛查阈值。其它边界（数据起止、质量标记或长缺口）不算作阈值清晰边界。

## 全量筛查结果

| 同行阈值 | 有共现的通道组合 | 不同源记录行（至少有一组三路） | 通道组合×记录行次数 | 连续片段数 | ≥60 秒 | ≥300 秒 | ≥1800 秒 | 片段时长中位数 / 最长 |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 50 W | 84/84 | 783,145 | 1,287,046 | 98,091 | 24,753 | 6,792 | 157 | 20 秒 / 9,307 秒 |
| 100 W | 83/84 | 105,327 | 141,750 | 22,538 | 3,281 | 389 | 8 | 15 秒 / 3,694 秒 |
| 300 W | 26/84 | 1,864 | 1,984 | 291 | 74 | 0 | 0 | 22 秒 / 272 秒 |

记录行是数据采样点，不是独立事件。`通道组合×记录行次数`会在四路或更多通道同时过阈值时对同一个采样行重复计数；“不同源记录行”才是按源 CSV 行去重后的数目。阈值越高，共现范围和持续时间明显收缩：300 W 下没有任何片段达到 5 分钟。

在 100 W 下，389 个至少 300 秒的片段中，有 **186 个**具备上述质量正常、连续且阈值清晰的两端边界。一个边界清晰的长片段为 `Appliance2 + Appliance5 + Appliance7`：2014-03-27 18:44:31 至 19:25:34，估算 2,471 秒，412 行，片段内最大相邻间隔 14 秒。该例可按其通道和时间在结果 CSV 中复核；**由于 House 3 官方通道映射尚未确认，不得给这三路贴上具体家电名称。**

结果文件：

- 完整阈值与组合汇总：[refit_house3_triple_coactivity_20260930.json](../homecoord_bench/results/refit_house3_triple_coactivity_20260930.json)。
- 候选片段：[refit_house3_triple_coactivity_bouts_20260930.csv](../homecoord_bench/results/refit_house3_triple_coactivity_bouts_20260930.csv)，仅导出估算时长至少 60 秒的 28,108 段；完整片段总数保留在 JSON 汇总中。
- 边界和缺口处理有合成小型 CSV 单元测试覆盖：`python -m unittest homecoord_bench.tests.test_refit_triple_coactivity_full_trace -v`，通过。

## 对 HomeCoord-Bench 的含义与限制

这是对真实家庭清洗功率时间序列的全量、阈值敏感性筛查，说明三路设备通道的同时高功率现象并非只能靠手工虚构；它可以为后续构造**由实测负载轨迹参数化的受控回放**提供候选片段。但现阶段它不能证明目标三类家电曾同时活动，因为 House 3 通道映射未确认；也不能证明用户提交了三个任务、存在截止时间、设备可远程启动、家庭电路发生超载或 Agent 之间发生冲突。

因此，本结果**提升了 C3 的真实负载来源基础，但尚未验证 C3 任务/协调命题本身**。若用于回放，任务到达、截止时间、可控性和容量预算仍要明示为实验设计变量，真实功率序列与研究者构造的任务契约分开标注。

## 下一门槛

1. 从 REFIT 发布方官方 ReadMe 或官方 metadata 中核实 House 3 的九路通道映射。官方清洗数据页列出了 [REFIT_Readme.txt](https://pureportal.strath.ac.uk/files/52873458/REFIT_Readme.txt) 和 [MetaData_Tables.xlsx](https://pureportal.strath.ac.uk/files/62090313/MetaData_Tables.xlsx)；直接打开 ReadMe 时遇到 Cloudflare 安全验证，未尝试绕过，也未将二手映射当作官方标签。
2. 只有官方映射确认目标三类通道后，才从全量片段表抽取目标组合，并进行边界/阈值盲审；不能根据功率形状猜设备身份。
3. 后续跨家庭复核只用于检验映射确认后的负载候选是否重复出现；任务请求、截止时间、控制能力和配电容量仍需独立数据或显式研究者设定。
