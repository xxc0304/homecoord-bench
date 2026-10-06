# F3 v8 空白设计／实现复审表

审查者／日期／是否作者之外／单模型或人类／是否查看方法成绩：待填。独立双审是否完成：待填。

第一轮只看设计卡、inputs、feasibility和权限源码，冻结设计判断后再读轨迹和成绩。设计总体结论、理由、缺失证据、通过条件：待填。

下表逐权限配置填写；01固定列仅表示laundry模式，02固定列表示drying/dishes，其余任务均prepare。每fixed配置必须核查四策略，每selectable配置必须核查三规则×四策略，不能只用8个基础世界判断代替32权限配置。

| 基础世界（D-F3前缀） | 能力／固定向量 | 设计：结论、理由、缺失证据、通过条件 | 实现：结论、理由、缺失证据、通过条件 | JSON调用/事件下标及代码位置 |
| --- | --- | --- | --- | --- |
| 01-competition-base | fixed eco | 待填 | 待填 | 待填 |
| 01-competition-base | fixed fast | 待填 | 待填 | 待填 |
| 01-competition-base | selectable | 待填 | 待填 | 待填 |
| 01-competition-loose | fixed eco | 待填 | 待填 | 待填 |
| 01-competition-loose | fixed fast | 待填 | 待填 | 待填 |
| 01-competition-loose | selectable | 待填 | 待填 | 待填 |
| 01-no_competition-base | fixed eco | 待填 | 待填 | 待填 |
| 01-no_competition-base | fixed fast | 待填 | 待填 | 待填 |
| 01-no_competition-base | selectable | 待填 | 待填 | 待填 |
| 01-no_competition-loose | fixed eco | 待填 | 待填 | 待填 |
| 01-no_competition-loose | fixed fast | 待填 | 待填 | 待填 |
| 01-no_competition-loose | selectable | 待填 | 待填 | 待填 |
| 02-competition-base | fixed eco/eco | 待填 | 待填 | 待填 |
| 02-competition-base | fixed eco/fast | 待填 | 待填 | 待填 |
| 02-competition-base | fixed fast/eco | 待填 | 待填 | 待填 |
| 02-competition-base | fixed fast/fast | 待填 | 待填 | 待填 |
| 02-competition-base | selectable | 待填 | 待填 | 待填 |
| 02-competition-loose | fixed eco/eco | 待填 | 待填 | 待填 |
| 02-competition-loose | fixed eco/fast | 待填 | 待填 | 待填 |
| 02-competition-loose | fixed fast/eco | 待填 | 待填 | 待填 |
| 02-competition-loose | fixed fast/fast | 待填 | 待填 | 待填 |
| 02-competition-loose | selectable | 待填 | 待填 | 待填 |
| 02-no_competition-base | fixed eco/eco | 待填 | 待填 | 待填 |
| 02-no_competition-base | fixed eco/fast | 待填 | 待填 | 待填 |
| 02-no_competition-base | fixed fast/eco | 待填 | 待填 | 待填 |
| 02-no_competition-base | fixed fast/fast | 待填 | 待填 | 待填 |
| 02-no_competition-base | selectable | 待填 | 待填 | 待填 |
| 02-no_competition-loose | fixed eco/eco | 待填 | 待填 | 待填 |
| 02-no_competition-loose | fixed eco/fast | 待填 | 待填 | 待填 |
| 02-no_competition-loose | fixed fast/eco | 待填 | 待填 | 待填 |
| 02-no_competition-loose | fixed fast/fast | 待填 | 待填 | 待填 |
| 02-no_competition-loose | selectable | 待填 | 待填 | 待填 |

必须单列：72固定模式排程对照、192同策略模式选择对照、96相同模式控制；32诊断的覆盖及局限；实际资源时间积与全服务/部分服务区分；同权限实际调用与无私有标签；承诺先于启动且重试不换模式；未完成/迟到/个体等待；冻结hash与不调用离线oracle。

总体实现结论与接受范围：待填。未接受范围／后续修订：待填。单模型审查不得写成独立双审、真实物理校准或模型性能证明。
