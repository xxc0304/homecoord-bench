# 集中／功能 Agent 同模型比较：实现与离线验收

后续真实运行已完成，当前状态见 [真实结果](ARCHITECTURE_COMPARISON_RESULT_2026-10-01.md)：224 次请求预算已用满。本文以下保留运行前准备记录，缺凭证与待运行状态为历史；不要再次调用 live 补采成功。

已完成三组比较实现、事前协议和预算锁、72 个离线执行单位及独立回放审计。新增 11 项测试，完整 287 项测试通过。当前设备没有 DEEPSEEK_API_KEY；live 入口前置检查确认未发送任何新 API 请求。真实架构效果保持未知，保留测试未打开。本轮仅在本地修改。

## 已完成的比较链路

central_batch 每个发布组调用一次；functional_local 每个任务看自身允许信息并发调用；functional_pooled 每个任务同时获得与集中组同源的发布组视图列表，但仍只允许提交自己的设备动作。三组共用 DeadlineAwareCoordinator、权限和安全门，设备可并行。局部视图原来就包含公共请求成本/期限；这次对照研究的是额外设备观测/角色/工具信息汇集，不能声称局部组没有全局公共信息。

每家族两个开发结构，竞争/无竞争各一个条件，两次采样，三个组，合计 12 条情境、72 个执行单位。新协议上限 224 次请求：集中 32、局部功能 96、汇集功能 96；一次尝试、45 秒超时、失败不返还预算、不补采成功。调用前持久记录预算预约，中断单位拒绝自动重新采样。原 09-30 试点和其用满的 26 次预算保持独立。

协议、12 条开发输入、源划分清单与相关代码哈希已经锁定。保留测试只沿用既有静态划分验证，不执行或读取其结果。F2 晚到请求在每个架构自身虚拟分支的 release 现场生成；功能组内真实线程并发采集，按公共起点的真实返回偏移模拟提案到达。该机制不是实际设备实时在线部署。

集中输出原子校验；批次失败全组作为缺失提案，功能输出失败只影响相应任务。两者以明确标记的本地 defer 保留执行分母与等待成本，原回复和错误保存。合法 off/defer 不计作服务。逐任务启动/完成缺失为 null。提供方/协议失败、授权错误、服务选择正确、执行服务、安全、截止与逐任务等待分别报告。

## 离线验收结果

假 transport 返回 API 形状的脚本提案；所有任务固定 1000 ms 模拟返回，三组动作相同。72 次执行包含 24 个三组匹配控制，不是 72 个独立模型或家庭样本。

| 组 | 脚本请求 | 执行单位 | 最终全部服务 | 全部按时 | 服务选择正确 |
|---|---:|---:|---:|---:|---:|
| 集中批次 | 32 | 24 | 24/24 | 20/24 | 96/96 |
| 功能局部 | 96 | 24 | 24/24 | 20/24 | 96/96 |
| 功能汇集 | 96 | 24 | 24/24 | 20/24 | 96/96 |

24 个三组匹配控制的服务、按时、逐任务等待/完成、模型返回时间和过程违规全部一致。独立重放 72 条记录轨迹也完全一致，逐发布组输入状态和版本可重建。每组 F1/F3 及全部无竞争条件均按时，F2 竞争条件 0/4 全部按时，失败均保留。没有发现新的服务语义错误；相同固定提案的超期来源是当前资源承诺和期限安排。

这些结果验证接口同一性、信息合同、执行与审计，不证明集中架构更省钱、功能架构更快或模型能力差异。脚本实际调用耗时是本地假 transport/日志开销；虚拟 1000 ms 是设定值，均不能充当 API 性能。脚本无实际 token 账单，usage 缺失单列，不把报告中的已知 token 总和 0 当模型零成本。

## 文件和运行入口

实现：`homecoord_bench/runtime/architecture_comparison.py`。
脚本：`homecoord_bench/probe_architecture_comparison_20261001.py`。
协议：`docs/ARCHITECTURE_COMPARISON_PREREG_2026-10-01.md`。
锁定输入：`homecoord_bench/revision_drafts/20261001_architecture_comparison/`。
离线结果/审计：`homecoord_bench/results/architecture_comparison_offline*_20261001.json`。
完整脚本调用日志在已忽略的 `homecoord_bench/runs/architecture-comparison-offline-20261001/`。

在仓库根目录运行，prepare 已完成，不应再次覆盖：

```powershell
python -m unittest discover -s homecoord_bench/tests
python homecoord_bench/probe_architecture_comparison_20261001.py audit --mode offline
```

本机为 Python 进程配置 DEEPSEEK_API_KEY 后，按新锁定预算执行：

```powershell
python homecoord_bench/probe_architecture_comparison_20261001.py live
python homecoord_bench/probe_architecture_comparison_20261001.py audit --mode live
```

live 与 offline 有各自结果及预算日志；已完成单位恢复时跳过，失败单位不重采，中断单位需先审查原日志。API 上限 224 而非授权无限调用。原始运行结果包含完整合成请求，后续发布前需按项目聚合数据口径整理；不能误把 15 MB 的离线完整记录当论文正式数据。协议或实现哈希不匹配时停止，须另开登记版本。

## 后续判断

真实阶段完成后，先看失败/分母/实际 model/信息及成本审计，再按家族和资源条件比较服务、截止、逐任务等待及整体完成。只有两次重复、六个作者开发结构、同一 EDF，不形成稳定尾时延或显著性结论。第二模型、额外执行策略、更多重复以及开启保留测试均留待新协议。本轮不上传 GitHub。
