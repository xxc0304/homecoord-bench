# C3 实测用电轨迹候选：REFIT 洗衣—烘干—洗碗设备组合

日期：2026-09-30 更新。状态：**House 5、House 1 和 House 3 的完整清洗轨迹已校验并完成相应审计；House 1 的跨户双设备功率共现仍是当前映射明确的复核结果。House 3 已完成九通道 84 种三路组合的 50/100/300 W 全量筛查，但 House 3 官方通道映射待确认，因此不作为已确认的洗衣机—烘干机—洗碗机证据。人工独立审查未完成；这些轨迹只证明测量功率共现，不能证明任务冲突，也尚未纳入冻结 benchmark。**

House 3 的完整审计、阈值敏感性结果和当前证据边界见[全量筛查记录](REFIT_HOUSE3_FULL_TRACE_TRIPLE_SCREEN_2026-09-30.md)。

## 本轮来源核查

与 GREEND 相比，REFIT 有更直接的公开学术证据。REFIT 原始论文（Murray et al., *Scientific Data*, 2017）的表 3 按户列出被监测设备；据表中各列，洗衣机、独立滚筒烘干机和洗碗机同时出现于 **House 1、3、5、8、13、15、20、21**。这只证明三类设备在研究监测期间同户被监测，**不证明三台设备曾同时运行，也不包含用户请求、截止时间、Agent 行为或智能控制能力**。

本轮打开了 Strathclyde 官方数据页及其官方清洗版 ReadMe。官方清洗版 ReadMe 对 House 5 列出：`Appliance2` 是滚筒烘干机、`Appliance3` 是洗衣机、`Appliance4` 是洗碗机。由此，House 5 的**初始通道映射已由发布方资料确认**，并与社区代码相符。发布方明确说这些设备是研究开始时已知的接线；住户虽被要求不要移动或更换 IAM 监测设备，但发布方不能保证住户没有这样做。

House 5 的变化记录对烘干机通道尤其关键：官方 ReadMe 在 `Appliance2` 下注明 **2014-11-21 加入除湿机**。因此，不能把这一路在该日期之后的功率都解释成烘干机；除非有额外数据能拆分两台设备，否则只可把 **2014-11-21 之前**作为“烘干机单设备通道”的候选时间窗，实际起始日期和可用覆盖仍须由 CSV 核实。另有 `Appliance5`（Computer Site）在 2015-01-27 发生 signature change；它不属于本候选的三台目标设备，但说明设备/负载变化确实需要按 ReadMe 处理。

官方清洗版页面说明数据总体覆盖 2013 年 10 月至 2015 年 6 月，20 户、名义 8 秒采样，CC BY 4.0；清洗包括重复时间戳合并、IAM 高于 4000 W 置零、尽可能保持每个 IAM 只对应一种设备，以及短于 2 分钟的 NaN 前向填充、长缺口置零。House 5 的 Zenodo CSV 已完整下载并通过校验：435,272,416 字节，MD5 与发布方记录一致，本地 SHA-256 为 `897defbaeadb048ced0d7f6b0ba262a7fa701b7a6943b6a7ca8ad515d7fa3c50`。全量共有 7,430,755 行，`Time` 覆盖 2013-09-26 至 2015-07-06。ReadMe 另指出采集端约每 6–8 秒轮询、只记录负载变化后补值、各传感器不同步，单次更新时间可落在前 6–8 秒任意位置。故名义采样间隔不能被解释为精确同步的物理动作时间。完整审计见 [House 5 全量轨迹审计](REFIT_HOUSE5_FULL_TRACE_AUDIT_2026-09-29.md)，汇总数字可从 [机器可读结果](../homecoord_bench/results/refit_house5_source_audit_20260929.json)复查。

另一份官方 [CLEAN_READ_ME_081116.txt](https://pure.strath.ac.uk/ws/portalfiles/portal/62090183/CLEAN_READ_ME_081116.txt) 说明实际 CSV 含 `Issues` 列：当九路设备分表读数之和大于总表时标为 `1`，该行应被剔除或注明不一致；清洗时曾将监测器重置/移动后的区段移到对应设备列。完整文件共有 425,766 个 `Issues=1` 行，占 5.73%；三路目标功率列均可解析，但发布方的前向填充和置零意味着数值可解析不等于原始观测完整。读取时将 `Issues=1` 排除后，设备同时超过探索性阈值的采样行仍存在；它们不是任务冲突次数。House 5 的清洗轨迹下载、全文件身份与初步统计已完成，定点片段记录仍保留作历史审计，见 [House 5 片段核查记录](REFIT_HOUSE5_RANGE_PROBE_2026-09-29.md)。

Strathclyde 官方数据页列出原始和清洗数据文件及 `MetaData_Tables.xlsx`，均标注 CC BY 4.0；论文说明每户有一份 CSV，含时间、Unix 时间戳、总表和 9 路设备监测值，8 秒采样。论文还说明 House 3、11、21 的总表读数受太阳能干扰；House 1、6、7 通过改线去除了该干扰。因此，若需总表作参考，优先调查 House 5、8、13、15、20；House 1 可作为去除太阳能干扰的候选。不能把这种筛选误写为已验证房屋配电容量。

Zenodo 的清洗版记录标注 CC BY 4.0，列出的文件只有 House 1、2、3、4、5、11 六户，而记录描述提及 20 户。House 5 文件由 API 列为 435,272,416 字节，MD5 为 `03938c844fdb09d787eb637bcf65f956`。该记录**不是完整 20 户镜像**；在完整下载并核验前，MD5 仍只是发布页面给出的校验值。House 5 的初始通道映射已由官方 ReadMe 确认，但数据质量、变更后通道解释、设备执行能力仍未全部确认。

官方论文进一步说明：个体设备监测器不同步，单路设备数据相对聚合读数可能滞后最多约 7 秒；清洗流程会对小于 2 分钟的缺口前向填充，对更大的缺口置零；设备在监测期内的变化应以随数据提供的 ReadMe 为准。因而“零值”不能不加区分地当作设备实际关闭，短时动作边界也要考虑 8 秒采样与传感器时差。

## 证据边界与候选参数

| 内容 | 可用证据 | 当前结论 |
|---|---|---|
| 设备组合 | 原论文 Table 3，逐户设备类别 | House 5 是可继续核查的三设备家庭 |
| 测量形式 | 原论文 Methods / Data Records | 8 秒级、每户 CSV、总表 + 9 路 IAM；设备与总表时间不完全同步 |
| 清洗规则与持续变化 | 原论文 Data Records / Usage Notes | 必须读取 ReadMe 并显式处理前向填充和长缺口置零 |
| 初始通道映射 | 官方清洗版 `REFIT_Readme.txt`，House 5 设备表及变化注记 | **已确认**：Appliance2 烘干机、Appliance3 洗衣机、Appliance4 洗碗机；Appliance2 在 2014-11-21 后有除湿机加入，烘干机单设备解释只对该日之前的窗口暂时成立 |
| 清洗规则与采样时序 | 官方清洗版数据页及两份 ReadMe | 名义 8 秒采样；变化触发记录后补值；传感器异步；短于 2 分钟缺口前向填充、较长缺口置零；IAM 超过 4000 W 置零；`Issues=1` 表示分表总和超过总表 |
| 功率轨迹 | House 5 CSV 完整获取、字节数与 MD5 已核验；全量 7,430,755 行通过结构解析；共用电窗口已提取并导出上下文 | `Issues=1` 占 5.73%；目标列无解析缺失；108 个长共用电窗口中有 91 个去重源记录行达到三路 ≥100 W，其中最长一段为 44 行/381 秒估算，且首尾邻行是 `Issues=1`；20 个边界较清楚的窗口中没有三路 ≥100 W 的记录 |
| 配电预算、Agent 可控性 | REFIT 不提供本课题所需的设备控制接口证据；总表也不是断路器容量证明 | 只能作为明确标注的研究控制量，不能称为实测家庭硬容量或设备远程启动能力 |
| 用户任务、到达时间和截止期 | 数据集没有这些标签 | 必须另作研究者控制／合成变量，不能从历史用电曲线反推 |

社区实现将 House 5 的 `Appliance2/3/4` 映射为烘干机／洗衣机／洗碗机；现已由官方 ReadMe 交叉确认。标签依据以官方 ReadMe 为准，社区实现仅作一致性旁证。

### TEDDINET / Frictionless Data 示例包复核

Frictionless Data 的 TEDDINET 2017 试点说明，`refit-cleaned` 数据包**为演示而缩小了 REFIT 数据规模**；文档列出 20 个家庭资源，示例 `house-1` 资源为 999 行，整包示例元数据共 19,980 行。它记录的设备列标签仅用于 `house-1`：`Appliance4` 是滚筒烘干机、`Appliance5` 是洗衣机、`Appliance6` 是洗碗机。文档没有给 House 5 通道映射，不能把 House 1 的标签套到 House 5。README 指向的 S3 `datapackage.json` 在本轮浏览器中被客户端拦截（`ERR_BLOCKED_BY_CLIENT`）；没有改用其他方式绕过。故该试点只证实“有一个缩小版数据包示例及其 House 1 标签”，**不能提供 House 5 实测轨迹或官方通道映射**。

## 对 HomeCoord-Bench 的可用方式

即便 House 5 的轨迹可成功读取，它也只能为**设备功率曲线、实际测得的设备活动时间、传感器断档和可能的历史重叠**提供经验依据。多 Agent 的任务发布、洗衣完成后才烘干的工作流、硬截止时间、可用的负载预算以及控制命令，仍属于研究者构造的实验契约。实验结果应称为“由真实设备轨迹参数化的受控回放”，不能称为真实家庭多 Agent 执行日志。

若后续以 House 5 承载容量冲突：容量预算需在实验方案中注明为**研究者控制参数**，对一系列预算做敏感性分析；不要将其解释为该户真实的总电路额定值。采样与时差较粗时，冲突事件的物理时间只能按误差区间表示。不得用识别出的历史用电峰值冒充用户截止时间，也不得把移位、重放或叠加后的数据称作原始观测。

## House 1 第二户复核

House 1 的官方清洗版 CSV 已独立校验（400,840,083 字节；MD5 `f5336d80c700f866af0d997ea8d39146`，SHA-256 `15b8c60c0bf32f1fccfafae81a9bb04e1a24937cfb29840d5b955310df25ff30`）。官方 ReadMe 映射 `Appliance4/5/6` 为烘干机／洗衣机／洗碗机。全文件有 6,960,008 行，其中 `Issues=1` 占 0.84%；大于 16 秒的采样间隔有 12,778 处。候选段筛选排除 `Issues=1`，并在大于 16 秒间隔处分段。

House 1 的洗衣机—洗碗机在 50 W 下有 490 秒候选段、100 W 下有 443 秒段、300 W 下有 323 秒段。100 W 和 300 W 候选的首尾相邻记录均为质量正常且至少一路低于阈值；逐行上下文导出通过候选行数、功率阈值、质量标志和时间间隔一致性检查。另有短片段及烘干机—洗衣机重叠，但不能将窗口计数解释为独立任务或冲突发生率。

对 House 1 所有 60 个 100 W 设备对窗口进一步去重后，`Issues=0` 的行中没有任何一行让三条目标通道同时达到 100 W。这个规则下的三路负结果覆盖完整：任一三路同记录共现都必然落在至少一个两路 100 W 窗口内。故目前 House 1 支持二设备实测功率回放，不支持三路 100 W 实测负载回放。House 5 的一个长三路片段仍有 `Issues` 边界问题；若项目需要三 Agent 的实测负载案例，下一项有明确目的的工作是核查另一户，而不是继续堆叠同类双设备窗口。

这构成一个**第二户、双设备、测量功率共现**的复核，有助于排除 House 5 单户特例；它没有建立三设备共现的跨户复现，也没有提供用户任务、截止时间、设备控制能力或家庭回路容量。House 1 数据可用于以实测功率轨迹参数化的受控回放。任务请求、时限和容量预算仍需明确作为研究者设定。人工独立审查尚未完成，审查状态保持空白。

完整记录见 [House 1 跨户复核](REFIT_HOUSE1_CROSS_HOME_RECHECK_2026-09-29.md)。窗口 ID 生成器现接受 `--house-id H1`，修正了此前脚本对所有文件都写 `REFIT-H5` 的标识错误；不改变任何窗口筛选或功率统计。

## House 3 数据可得性检查（2026-09-29 历史记录；已更新）

> 下文记录 2026-09-29 当时的下载尝试和待办。House 3 已于 2026-09-30 完整下载、校验并完成全量审计及九通道三路共现筛查；“部分文件、不能统计”的旧状态已过时。当前仍未解决的是官方 House 3 Appliance 通道映射。最新结论以[2026-09-30 全量筛查记录](REFIT_HOUSE3_FULL_TRACE_TRIPLE_SCREEN_2026-09-30.md)为准。

Zenodo 的公开记录确认包含 `CLEAN_House3.csv`，发布方列出的大小为 407.3 MB、MD5 为 `ab6e34ea386eb4563bfcb9762619dc8f`，记录许可为 CC BY 4.0。House 3 是论文表格中三类目标设备同户监测的候选之一，但其总表有太阳能干扰，因此即使取得完整文件，也只考虑设备分表的共现筛查，不用总表推断配电容量。

当时下载测试仅收到 2,625,536 字节，故停止并等待完整数据来源。该下载探测文件状态现已被完整文件取代；官方 ReadMe 链接仍触发 Cloudflare 安全验证，House 3 的具体通道映射尚未核实。详见上方新审计。

## 下一道执行门槛

1. 优先查看 [20 个边界较清楚的窗口](../homecoord_bench/results/refit_house5_coactivity_review_summary_20260929.csv)和 [三设备共现片段表](../homecoord_bench/results/refit_house5_triple_coactivity_bouts_20260929.csv)。其中约 6 分钟的三路高负载段可用于 trace-backed 回放候选，但要保留两端 `Issues` 标记导致的边界不确定性。
2. 先核实 House 3 官方通道映射；映射确认后再从候选片段中筛目标设备组合并进行独立审查。没有独立审核者时，留空人工复核列并标注未独立审查，不能把机器筛查写成专家确认。
3. 如果需要家电活动片段而非共用电观测，再单独定义、检验周期提取规则；排除 `Issues=1`，将长缺口和清洗置零视为不确定边界，并报告阈值、持续时间与缺口敏感性。真实数据不包含任务请求、期限、设备控制能力或家庭回路容量，这些需在后续实验中明确作为研究者设定。

## 来源

- Murray, D., Stankovic, L., & Stankovic, V. (2017). *An electrical load measurements dataset of United Kingdom households from a two-year longitudinal study*. Scientific Data 4, 160122. [论文](https://www.nature.com/articles/sdata2016122)；[Table 3（逐户监测设备）](https://www.nature.com/articles/sdata2016122/tables/4)。
- University of Strathclyde, [REFIT: Electrical Load Measurements 官方数据页](https://pureportal.strath.ac.uk/en/datasets/refit-electrical-load-measurements/)，列出原始文件与 `REFITREADME.txt`，CC BY 4.0。
- University of Strathclyde, [REFIT 官方清洗数据页](https://pureportal.strath.ac.uk/en/datasets/refit-electrical-load-measurements-cleaned/)，列出 `CLEAN_REFIT_081116.7z`（490 MB）、清洗说明、更新版 ReadMe 和 `MetaData_Tables.xlsx`，CC BY 4.0。本轮读取的更新版 ReadMe 文件：[REFIT_Readme.txt](https://pureportal.strath.ac.uk/ws/portalfiles/portal/52873458/REFIT_Readme.txt)。
- University of Strathclyde, [CLEAN_READ_ME_081116.txt](https://pure.strath.ac.uk/ws/portalfiles/portal/62090183/CLEAN_READ_ME_081116.txt)，解释 CSV 的 `Issues` 列及清洗时的通道区段重映射。
- Murray & Stankovic, [REFIT cleaned data, Zenodo DOI 10.5281/zenodo.5063428](https://zenodo.org/records/5063428)，CC BY 4.0。House 5 文件大小与发布方 MD5 已下载核验，本地 SHA-256 和全量质量摘要见 [House 5 全量轨迹审计](REFIT_HOUSE5_FULL_TRACE_AUDIT_2026-09-29.md)。
- Frictionless Data / TEDDINET, [2017 REFIT cleaned Data Package pilot README](https://github.com/frictionlessdata/frictionlessdata.io/blob/main/site/blog/2017-12-19-dm4t/README.md)。作者明确说明为演示缩小数据规模；只给 House 1 通道描述，不能作为 House 5 的官方通道映射。
- House 5 二手映射线索：[community implementation](https://github.com/Agent07-X-lab/Internship-NIML-Project/blob/main/data_processing/refit_processor.py)，仅供核对，不作为标签依据。
