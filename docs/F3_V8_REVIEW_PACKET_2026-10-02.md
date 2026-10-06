# F3 v8 复审入口与作者验证

**设计和实现待复审，acceptance=null。**先读[F3能力合同](F3_MODE_CAPABILITY_V8_2026-10-02.md)，不看策略成绩，接受修改项后再核查实现。作者检查不是独立审查。本轮无API、无保留集实验、无上传；不扩大模型预算。

## 提交范围与证据

目录：homecoord_bench/task_revision/fixtures/f3_v8/，共45份JSON。

| 材料 | 内容／要审查什么 |
| --- | --- |
| inputs.json | 32权限配置、实际工具表、物理模式、服务及合成委托。8基础世界不是32新结构；24固定向量+8选择合同 |
| feasibility.json | 8份离线证书，共24合法模式组合。重验完整周期、容量、release+2100及截止，不当在线保证 |
| index.json | 所有主/诊断文件路径与规模：192主回放、32诊断、72排程对照、192模式选择对照、96相同模式控制 |
| runs/*.json（32份） | 每fixed文件4策略；每selectable文件3规则×4策略=12回放，实际calls/decisions、完整trace、result、作者audit齐 |
| diagnostics/*.json（8份） | 每世界4诊断：固定低预约组越权fast；选择组虚报时长、off、noop。每文件顺序固定如此，只跑ConstraintCoordinator，不冒充全部策略诊断覆盖 |
| contrasts.json | 固定向量内排程对比、同策略模式对比、相同实际选择向量的固定控制索引。全部差值需从原回放重算 |
| manifest.json | 新源码/测试、所用基础源码、8原开发输入及其他44份新JSON的SHA256；旧冻结包不回写 |

主文件中策略顺序始终Independent、Constraint、DeadlineAware、GateRetry。selectable文件runs[0..3]为low_resource，runs[4..7]为short_duration，runs[8..11]为capacity_pressure。fixed文件只使用唯一模式提案生成器；其selector字段low_resource不赋予额外可选模式。

实际评估episode_id固定组包含完整向量，但文件路径将冒号替换为--、逗号替换为-以满足Windows文件名；均可按index定位，不要根据文件名猜权限。provider实际ID为F3-public-home，与实验标签分离，单次隔离回放内唯一。

## 代码索引

- f3_capability.py:8 校验合同、实际工具权限、物理等价、公开/真实成本及支持范围；:75 逐提案模式与估计成本守卫；:87 规范化任务；:94 完整实际输入白名单。
- event_simulator_v8.py:321 执行前校验；:493 预约前模式守卫；:506 合法服务提案mode_selection_committed；:797 发布/真实调用；:915 启动前提与共同安全门。该引擎新增边界与承诺事件，调度/真实完成/生产计分保持基础实现。门控重试沿用同一候选动作，不再选模式。
- f3_revision.py:19 只加载D-F3开发输入；:33 分开物理合格与授权目录；:67 同权限简单模式规则；:105 独立事件/模式/成本重计；:168 回放；:175 控制差值；:189 证据生成与哈希。
- runtime/task_response_metrics.py 与 evaluate.py 是生产计分；新audit不调用它们，仅以真实事件独立比对。audit中all_service_completion_ms与资源时间积是新增明确指标，**不以旧legacy task_service投影字段作为真实完成或成本证据**。

## 实现必须核查

1. **同权限与同信息**：32配置内四策略实际目录/授权一致，三选择规则获得相同完整模式集合；私有配置/selector标签、自由文本、答案模板不进入调用。模板默认eco不得绑架选择组，也不得覆盖fixed-fast授权。
2. **服务等价与启动前承诺**：两物理模式提供同一请求服务；越权模式即使物理合格仍应预约前拒绝。mode_selection_committed必须先于对应实际启动，身份/操作/成本一致；排队和GateRetry重试不换模式、不缩周期。无外源中途更换API，本轮不验收动态切换策略。
3. **真实执行与评分**：重建192主回放的设备状态、版本、半开资源区间、真实启动/完成；无超容量/伪完成。逐任务时延从自己的release算；未完成false/null，迟到仍违规。整体全服务完成与部分服务latest_observed分开。
4. **实际成本**：对每个区间按实际预约量×结束减开始积分；与task成本和total对照，不能按默认eco、预计时长或标签填成本。off/noop低成本不等于服务成功；不同模式较早完工不能抹去别的任务等待/超期。
5. **对照归因**：72固定向量排程对照控制模式；192同策略模式对照控制执行政策；96mode-matched controls核对相同选择向量、世界、策略的核心指标及资源时间积一致。缺失完成时差值为null，而不是用0代替；both_all_services_completed必须同时看，不作简单排行。
6. **32诊断及回归**：越权fast应mode_not_authorized；虚报成本应declared_mode_cost_mismatch，均不得启动相关违规服务；off动作可以完成但请求服务仍false/null；noop未服务。同一文件四诊断按Constraint策略验证，其余策略覆盖仅限主回放/测试明示范围。
7. **冻结及结论**：哈希复现、C1/F2/Phase A/B旧材料不变；离线oracle不被这四在线方法调用。不能据作者脚本差值宣称模型优势、实机能源收益或在线不可避免性。

## 作者验证（不是验收）

2026-10-02：16新增测试及全套449通过。192主回放、32诊断、实际捕获与完整轨迹均保存；96相同模式控制指标/成本一致，72与192对照已生成，全部未完成/超期保留。24离线模式组合证书有效于明示假设。权限拒绝、成本撒谎、off/noop、mode/duration/commit/评分篡改、同信息、私有文本、门控重试模式不变、禁止离线oracle与基础同模式数值回归均检查。45份新JSON确定性复现，所用源码哈希一致；全套含旧冻结材料复现测试。

复现：仓库根目录、可用Python运行 `-m unittest homecoord_bench.tests.test_f3_v8 -v`；全套 `-m unittest discover -s homecoord_bench/tests`。生成器 `-m homecoord_bench.task_revision.f3_revision` 只输出路径列表；追加路径参数输出该文件文本，不写文件。

审查记录：[空白逐配置表](F3_V8_REVIEW_FORM_2026-10-02.md)。先保存设计结论再读取运行成绩；审查者逐配置/策略/选择规则重算，不只引用作者audit或449测试数。作者不填写reviewer_acceptance。
