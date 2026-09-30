# REFIT House 5 完整轨迹校验与首轮审计

日期：2026-09-29。状态：**House 5 清洗 CSV 已完整下载，文件身份通过发布方 MD5 校验；全量结构审计已完成。该轨迹尚未转成正式 episode，也不能单独证明真实家庭任务冲突或协调收益。**

## 文件身份

- 来源：Zenodo [REFIT cleaned data, DOI 10.5281/zenodo.5063428](https://zenodo.org/records/5063428)，文件 `CLEAN_House5.csv`。
- 文件大小：435,272,416 字节，与 Zenodo API 列出的大小一致。
- 发布方 MD5：`03938c844fdb09d787eb637bcf65f956`；本地计算值完全匹配。
- 本地 SHA-256：`897defbaeadb048ced0d7f6b0ba262a7fa701b7a6943b6a7ca8ad515d7fa3c50`。
- 本机文件：`homecoord_bench/data/external/REFIT/CLEAN_House5.csv`。该目录已由 `.gitignore` 排除，不会因普通 Git 提交意外纳入大型数据文件。
- 全量结构与活动片段探试摘要：[机器可读审计结果](../homecoord_bench/results/refit_house5_source_audit_20260929.json)。本地原始程序输出也保存在被忽略的数据目录。

## 全量观测摘要

使用 `homecoord_bench/inspect_power_trace_csv.py` 检查完整 CSV，时间列为 `Unix`，目标通道为 `Appliance2/3/4`，名义采样间隔设为 8 秒，并显式统计官方质量列 `Issues`。

| 检查项 | House 5 全量结果 |
|---|---:|
| 完整行数 | 7,430,755 |
| `Time` 时间范围 | 2013-09-26 09:56:09 至 2015-07-06 17:48:55 |
| `Issues=1` | 425,766 行（5.73%） |
| 无效或缺失 `Issues` | 0 行 |
| 时间戳间隔大于 16 秒 | 57,520 处 |
| 最大时间戳间隔 | 747,249 秒（约 8.65 天） |
| 数值可解析的目标通道 | 三路均为 100% |
| `Appliance2/3/4` 观测最大值 | 3,922 / 2,437 / 2,653 W |

三路都能解析出数值，只能说明 CSV 完整可读。发布方清洗曾对短缺口前向填充、长缺口置零；因此零值未必是实测关机，不能把“无缺失数值”解释为“无插补”。`Issues=1` 是发布方定义的总表与分表不一致行，应排除或显式标为不确定。长缺口也应切断活动周期，不能跨缺口补成连续运行。

## 设备变更前的重叠功率记录

官方 House 5 ReadMe 记载 `Appliance2` 于 2014-11-21 加入除湿机。为了不把这一路之后的数据直接解释成单独烘干机，本次只把 `Time` 日期早于 2014-11-21 的数据作为“烘干机通道可解释窗口”候选。此窗口有 4,985,937 行，其中 331,715 行（6.65%）被 `Issues=1` 标记；剔除这些行后有 4,654,222 行。

在清洁行中，以三路功率均达到至少 100 W 作为**探索性阈值**，观察到：烘干机与洗衣机同时超过阈值 42,891 行；烘干机与洗碗机 5,023 行；洗衣机与洗碗机 1,253 行；三路同时超过阈值 452 行。在正式提取周期前，仍需按发布方清洗规则处理填充值、质量标记和时间间隔，并对不同阈值做系统敏感性分析。

这些是相邻的 8 秒记录行，时间上高度相关。它们既不是 42,891 个独立事件，也不是用户同时提交了两个任务，更不代表家庭容量冲突。100 W 是本次分析用的阈值，不是 REFIT 发布方定义的设备开关标签。故这些数字只说明**完整轨迹确实包含设备功率重叠观测，可用于后续提取和审查活动片段**；不能作为真实任务冲突发生率或 benchmark 成效证据。

## 对 C3 数据方案的影响

REFIT House 5 已从“来源待确认”推进到“完整轨迹身份与初始质量已审计”。它可以为研究者构造的 C3 回放提供真实设备功率形状、活动片段候选、采样不齐和数据质量标记等经验基础。下一步需要先做带质量规则的活动片段提取，报告阈值和缺口处理敏感性，并对代表性片段人工抽检；任何片段库应保留原始文件哈希、行号/时间范围、Issues 筛除理由和设备通道映射。

REFIT 不包含 Agent 请求、家庭成员意图、硬截止时间、远程启动能力或断路器容量。多 Agent 的任务到达、依赖、可控性、容量预算和期限仍需作为独立标注的研究者设定变量。合适的表述是“基于真实家庭用电轨迹的受控多 Agent 回放”，不能称作真实家庭 Agent 执行日志。

## 阈值连续段试探

为确认简单阈值能否直接恢复设备任务周期，又做了一次保守的连续段试探：仅用 `Time` 早于 2014-11-21 的记录；`Issues=1` 行切断片段；相邻 Unix 时间差大于 16 秒也切断；功率达到阈值算活动，低于阈值结束片段。100 W 下得到烘干机 20,672 段（中位 38 秒）、洗衣机 9,818 段（中位 23 秒）、洗碗机 2,034 段（中位 15 秒）。500 W 下段数分别为 14,288、1,917、1,994。完整阈值扫查及方法参数见[机器可读审计结果](../homecoord_bench/results/refit_house5_source_audit_20260929.json)。

这些很短的连续段显然不能直接解释为一次完整洗衣、烘干或洗碗周期。它们反映了阈值切分会把多阶段设备功率曲线拆成许多短促片段，结果也随功率阈值改变。当前提取仅是规则试探，尚未经过独立人工标注或物理周期验证；不能把这些段数和时长用作服务时间分布。下一步需制定可审查的周期合并规则，并对 `Issues`、填充值、允许的低功率间隙、最短持续时间和阈值做敏感性分析。

## 同时用电窗口审查集

在相同的设备变更前日期窗内，按固定规则提取成对同时用电的观测窗口：两路功率都至少 100 W；只保留 `Issues=0` 行；相邻记录相差不超过 16 秒才连接到同一窗口；遇到质量标记或更大时间间隔就切断。结果为：烘干机＋洗衣机 5,443 个窗口，烘干机＋洗碗机 676 个，洗衣机＋洗碗机 155 个。三种组合窗口时长中位数分别为 23、18、16 秒；按同一规则至少 5 分钟的窗口分别为 87、14、7 个。

为方便人工查看，导出全部 108 个至少 5 分钟的窗口，包含时间范围、CSV 行号、采样行数和功率摘要，见[窗口审查清单](../homecoord_bench/results/refit_house5_coactivity_review_20260929.json)。可复跑的提取脚本为 [`extract_refit_coactivity_windows.py`](../homecoord_bench/extract_refit_coactivity_windows.py)；它只做观测筛选，不给窗口贴冲突标签。5 分钟只是缩小人工查看数量的筛选线，不是任务持续时间标准。

阈值敏感性也已检查，其他规则相同：两路各自至少 50 W 时共得到 11,286 个“配对窗口”（221 个达到 5 分钟）；至少 100 W 时为 6,274 个（108 个达到 5 分钟）；至少 300 W 时为 1,571 个（25 个达到 5 分钟）。这里的总数是三个设备对分别计数，同一时段三台都活动时会在多个设备对中出现。数量随阈值明显变化，说明窗口集合依赖研究者选定的功率阈值；不能把任何一档解释为家庭冲突的真实发生率。完整分设备对结果保存在机器可读审计 JSON。

这些窗口仍需人工检查数据缺口、零值和多阶段设备负载模式。当前未完成独立人工审查。窗口来自同一个家庭和同一段长时序；计数不代表独立事件或家庭样本。传感器不同步、采样边界误差、`Issues` 排除及清洗填充值也限制精确的同时性判断。

### 窗口上下文导出与边界质量筛查

为便于逐条查看，已将 108 个至少 5 分钟窗口连同每个窗口前后各 30 行原始清洗 CSV 上下文导出。长表共 14,604 行，其中候选窗口内部 8,124 行、上下文 6,480 行；另有一张每窗口一行的汇总表，提供窗口时间、功率摘要、边界质量筛查结果和留空的人工记录栏。两个 CSV 都是基于 CC BY 4.0 REFIT 清洗数据的审查材料，不包含用户任务或冲突标签。

导出程序对所有候选行自动复核了 CSV 行号跨度、`Issues=0`、设备对两路均不低于 100 W、相邻采样间隔不超过 16 秒，并确认候选行数与窗口 JSON 一致；108 个窗口全部通过这些**筛选规则一致性检查**。它们的持续时间为 301–1,933 秒，中位数 428.5 秒。这里的“通过”只表示提取规则和源 CSV 相符，不表示已经人工确认设备周期或物理冲突。

进一步检查每个候选窗口紧邻的前、后一个采样行：

| 边界依据 | 开始端 | 结束端 |
|---|---:|---:|
| 紧邻记录质量正常且设备对不再同时达到 100 W（至少一路低于阈值） | 40 | 37 |
| 紧邻记录 `Issues` 非零 | 60 | 63 |
| 与紧邻记录时间差大于 16 秒 | 8 | 8 |

仅 20 个窗口的两端都由紧邻的正常记录夹住，且设备对不再同时达到 100 W（至少一路低于阈值）（烘干机＋洗衣机 17 个、烘干机＋洗碗机 2 个、洗衣机＋洗碗机 1 个）。这 20 个可作为优先复核的**边界较清楚的功率共现片段**，持续时间为 301–807 秒，中位数 434 秒。即使在这 20 个中，11 个窗口的前后 30 行上下文里仍出现过 `Issues` 行，4 个上下文里仍有超过 16 秒的时间间隔；因此“边界较清楚”只指候选段两端的紧邻记录，不代表整段周围数据完全无质量问题。

每窗口汇总表中的 `strict_clean_boundary_pair=true` 可筛出上述 20 个窗口。没有独立人工审核者时，可以把人工复核列留空并保留审查状态未完成；这不妨碍把它们作为受限的真实功率轨迹例子，但不能将其升级为真实任务周期、用户请求、截止时间或 Agent 冲突标签。

审查材料：

- 每窗口汇总及空白复核字段：[窗口审查汇总 CSV](../homecoord_bench/results/refit_house5_coactivity_review_summary_20260929.csv)
- 全部候选行及前后各 30 行上下文：[逐行上下文 CSV](../homecoord_bench/results/refit_house5_coactivity_review_rows_20260929.csv)
- 提取结果 JSON：[共用电窗口清单](../homecoord_bench/results/refit_house5_coactivity_review_20260929.json)
- 上下文导出程序：[export_refit_coactivity_review_rows.py](../homecoord_bench/export_refit_coactivity_review_rows.py)

### 三路设备共现筛查

考虑到 C3 可能涉及三个以上的 Agent，我又在全部 108 个长时设备对窗口中检查了 Appliance2、Appliance3、Appliance4 是否在同一记录行都达到阈值，并按原始 CSV 行号去重。这里的统计只覆盖这 108 个已选窗口，并非 House 5 全量三设备共现次数。

| 三路阈值 | 去重后的共现源数据行 | 出现共现的审查窗口 | 20 个边界较清楚窗口中的共现源数据行 |
|---|---:|---:|---:|
| 每路 ≥50 W | 559 | 20 | 16 |
| 每路 ≥100 W | 91 | 7 | 0 |
| 每路 ≥300 W | 44 | 3 | 0 |

50 W、100 W 和 300 W 下数字差异明显，不能把某个阈值解释为客观的“冲突定义”。在 100 W 条件下，去重后共识别出 7 个连续共现片段；其中唯一超过 5 分钟的片段是 **2014-01-02 15:18:06 至 15:24:19**：44 行连续记录、实际首末时间跨度 373 秒（按提取器的 8 秒尾部估算规则为 381 秒），三路内部样本均为 `Issues=0`，最大相邻采样间隔 15 秒。三路功率中位数分别为 Appliance2 **1,839 W**、Appliance3 **1,981 W**、Appliance4 **2,220 W**；Aggregate 中位数为 **6,524 W**。这个片段在三个设备对窗口里重复出现，去重后是一个源数据区间，不应计成三个事件。

该长片段紧邻的前后记录都标为 `Issues=1`，因此内部约六分钟的三路功率共现有清洁采样支持，但精确开始和结束时刻受质量边界影响。它支持“真实家庭数据中出现过三路同时高负载的观测”这一有限结论；它不说明三位用户分别提交了任务、不证明家庭回路超限，也不显示设备可以被 Agent 控制。其余六段各为 8–113 秒，不能当作长任务服务时间。

**对多 Agent 实验的含义：**House 5 可为三设备并发回放提供一个实测负载轨迹例子，但当前最干净的 20 个边界子集中没有每路 ≥100 W 的三路共现。若要研究三 Agent 协同，可以把 2014-01-02 片段作为单独的 trace-backed 负载案例，并把任务请求、调度期限和容量约束明确标成研究者设定；仅凭这一个家庭、一个较长三路片段，不足以支撑三设备冲突的普遍性或发生率主张。下一步应在其他 REFIT 家庭及阈值敏感性下查找可复核的三路轨迹。

相关输出：

- [三路共现片段汇总 CSV](../homecoord_bench/results/refit_house5_triple_coactivity_bouts_20260929.csv)
- [91 行去重后的三路共现源记录](../homecoord_bench/results/refit_house5_triple_coactivity_source_rows_20260929.csv)
- [三路共现审计 JSON](../homecoord_bench/results/refit_house5_triple_coactivity_bouts_20260929.json)
- [20 个边界子集及阈值敏感性结果](../homecoord_bench/results/refit_house5_strict_coactivity_subset_audit_20260929.json)
- [三路共现提取脚本](../homecoord_bench/extract_refit_triple_coactivity_bouts.py)
- [边界子集审计脚本](../homecoord_bench/audit_refit_coactivity_subset.py)

本次上下文检查不会将这些片段识别为任务周期或智能家居冲突；它只为下一步选取可信度更高的观测功率轨迹提供筛查依据。

## 可复现命令

```powershell
python homecoord_bench/inspect_power_trace_csv.py `
  homecoord_bench/data/external/REFIT/CLEAN_House5.csv `
  --timestamp-column Unix `
  --device dryer=Appliance2 `
  --device washer=Appliance3 `
  --device dishwasher=Appliance4 `
  --expected-interval-seconds 8 `
  --source-url https://zenodo.org/records/5063428 `
  --house-id REFIT-House5 `
  --quality-flag-column Issues `
  --output homecoord_bench/data/external/REFIT/full_trace_audit_20260929.json

python homecoord_bench/export_refit_coactivity_review_rows.py `
  homecoord_bench/data/external/REFIT/CLEAN_House5.csv `
  homecoord_bench/results/refit_house5_coactivity_review_20260929.json `
  homecoord_bench/results/refit_house5_coactivity_review_rows_20260929.csv `
  --context-rows 30 `
  --summary-output homecoord_bench/results/refit_house5_coactivity_review_summary_20260929.csv

python homecoord_bench/audit_refit_coactivity_subset.py `
  homecoord_bench/results/refit_house5_coactivity_review_summary_20260929.csv `
  homecoord_bench/results/refit_house5_coactivity_review_rows_20260929.csv `
  homecoord_bench/results/refit_house5_strict_coactivity_subset_audit_20260929.csv `
  homecoord_bench/results/refit_house5_strict_coactivity_subset_audit_20260929.json

python homecoord_bench/extract_refit_triple_coactivity_bouts.py `
  homecoord_bench/results/refit_house5_coactivity_review_summary_20260929.csv `
  homecoord_bench/results/refit_house5_coactivity_review_rows_20260929.csv `
  homecoord_bench/results/refit_house5_triple_coactivity_bouts_20260929.csv `
  homecoord_bench/results/refit_house5_triple_coactivity_source_rows_20260929.csv `
  homecoord_bench/results/refit_house5_triple_coactivity_bouts_20260929.json
```

后续周期抽取要把 `Issues=1` 行视为无效/不确定，把时间缺口视为边界，谨慎解释零值，并只在 2014-11-21 前把 `Appliance2` 标成单独烘干机候选通道。
