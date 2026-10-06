# F2 v7 复审入口与作者验证

**设计和实现仍待复审，acceptance=null。**先读 [设计合同](F2_INFORMATION_BOUNDARY_V7_2026-10-02.md)，第一轮不参考方法成绩；接受修改项后再审下列轨迹。作者测试及数字复现不等于独立审查。本轮无API、无保留集运行、无GitHub上传。

## 证据入口

证据目录：`homecoord_bench/task_revision/fixtures/f2_v7/`。共24份JSON，分文件提交，避免把8配置或48反事实重复计为独立任务结构。

| 文件 | 内容及审查要求 |
| --- | --- |
| inputs.json | 8配置、工具/grounding、参数及非抢占委托；先验设计 |
| feasibility.json | 8份离线证书；重查资源、时长、release+2100、截止；不是在线保证 |
| index.json | 8主文件、12反事实文件的路径；32主回放、48反事实回放；48项前缀一致性摘要 |
| runs/*.json | 每配置4策略，实际calls、完整trace、result、作者事件重计；每文件runs[0..3]依次为Independent/Constraint/DeadlineAware/GateRetry |
| diagnostics/*.json | 每个晚到配置×3反事实条件各一文件，每文件4策略；保存修改后的完整episode和回放，可与对应主文件在before_ms之前逐字段比对 |
| manifest.json | 新模块、所用基础源码、8原开发输入及23份其他JSON的SHA256；验收保留null |

诊断同时插入私有ID、goal/context、工具description、agent额外字段和未来成本上界canary；改变未来时刻、期限/优先级，或移除未来请求。静态设备清单保持不变。部分原始外源context/评估goal故意带诊断标记，不用于新的服务设计或离线可行声明；其作用是验证白名单不会把这些字段带入provider。未来移除组只用于信息不变性诊断。

## 代码索引

- `f2_information.py:7`：支持范围、hook/instructions拒绝、静态字段及成本一致性。
- `f2_information.py:45`：已发布任务规范化。
- `f2_information.py:52`：完整实际白名单请求；忽略任意私有request_id、evaluation hints、pending输入，重建context。
- `event_simulator_v7.py:321`：执行前范围校验；`:791` 发布；`:799` 真实调用builder并保存实际请求；`:909` 启动复核。其余调度/完成/评分继承基础引擎，测试逐源码核对差异，旧基础文件未编辑。
- `f2_revision.py:17`：只加载development/D-F2-*，保留成本和预算；`:42` PublicProposals从公开工具成本形成prepare提案，不读隐藏答案模板；`:59` 独立按事件重计；`:113` 调用；`:121` 反事实；`:156` 证据包。
- 评分仍使用 `runtime/task_response_metrics.py` 和 `evaluate.py`；作者audit不调用这些生产计分函数，只比对真实启动/完成、半开资源区间、状态版本及自发布等待/完成/迟到/按时。

## 必须审查什么

1. **完整实际输入**：所有通道无未来内容/存在性/时刻/私有条件标签；不能只搜关键词。原目录/额外上下文及评分模板是否确实不进入请求？实际provider输入与trace是否一致？同刻发布是否对所有策略公平？
2. **48组反事实**：分别在60000/120000ms之前对完整calls与events重做比较。摘要哈希不是独立证据；需从对应主文件、诊断文件重建前缀。同时发布组不属于这些相同历史配对。
3. **32条主执行**：无任务提前调用/启动，实际完成回执匹配，运行负载不超容量，完整非抢占周期无截断；必要排队不是失败，未完成保留false/null，迟到完成仍超期。对全部事件重算，不只接受作者audit。
4. **信息与策略旁路**：四在线策略不能调用ideal_schedule；不接受future reserve、整episode hook、外部instructions或离线批次计划。范围限制与明确拒绝是否充分？
5. **冻结与结论**：检查manifest及旧冻结包测试。脚本未用泄露信息时修正前后数字可以一致，数字一致不证明旧输入正确；不能推广为模型性能或在线不可避免性结论。

空白表：[F2 v7审查表](F2_V7_REVIEW_FORM_2026-10-02.md)。审查者需记录独立性、审查范围、是否查看策略成绩，逐配置填写结论、理由、缺失证据、通过条件及JSON数组/代码定位。不要由作者替审查者填写验收。

## 作者验证记录

2026-10-02：8配置、32主回放、48反事实回放（16设备配置/策略组合×3未来变化）均执行并保存；8离线证书成立于明示假设。13新增测试、全套433通过。完整输入/在线事件前缀48对一致，实际调用与trace一致，规范化同刻发布、未完成false/null、真实排队完成、未来计划拒绝及不调用离线oracle均测试；主脚本核心指标与基础引擎32对一致，不比较方法优劣。C1 v5/v6及旧Phase A/B冻结复现测试仍通过。

本轮尚未对全部损失做因果归因；不把“资源相关排队/拒绝”自动改名“不可避免损失”。保留所有未完成和超期，不追加运行修成绩。

复现命令（仓库根目录、可用Python）：`-m unittest homecoord_bench.tests.test_f2_v7 -v`；全套 `-m unittest discover -s homecoord_bench/tests`。生成器 `-m homecoord_bench.task_revision.f2_revision` 输出文件列表，追加路径参数仅输出该文件的确定性JSON文本，不写文件。
