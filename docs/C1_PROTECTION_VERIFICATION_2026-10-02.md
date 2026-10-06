# C1修订作者侧离线验证

2026-10-02。不是独立复审或实现验收通过；请先审设计卡再看本页。

8配置×4原普通策略=32脚本回放，全部保存到[新结果](../homecoord_bench/results/protection_v5_offline_20261002.json)，没有新API、保留测试或GitHub上传。脚本仍是答案模板，准入是共同可信用户政策，不证明LLM必需或多Agent优势。

默认300ms脚本下，高请求400ms启动、900ms真实完成。冲突臂低请求1200ms发布即终态拒绝，6000ms保护到期后仍不复活；安全臂6500ms发布、6900ms启动、7400ms完成。动作完成false/null与正确拒绝分开，没有把未执行动作记完成。两设备、两预算组遵循同样语义，保护失效正时长为0。

独立事件重计从发布时状态判断预期处置，重放设备状态、关联动作开始/完成、计算保护失效时长，并检查终态请求无脚本调用或完成。recount不是完整设备或所有legacy评分字段证明，所有acceptance仍null。

12新增测试覆盖32执行、拒绝后不复活、新身份到期后可执行、到期与发布同刻状态更新先行、慢提案不使发布时拒绝复活、等预算/合法性配对、输入无6000到期提示、缺授权/隐藏状态/混合合同拒绝、篡改状态和伪造完成、非布尔状态/重复请求身份拒绝、冻结产物/哈希复现。无本功能时，14个旧语义配置×4策略=56完整v3/v5配对一致。

```powershell
python -m homecoord_bench.task_revision.protection_revision
python -m unittest homecoord_bench.tests.test_protection_v5 -v
python -m unittest discover -s homecoord_bench/tests -q
```

生成器只打印产物或切片，不覆盖文件。原Phase A/B源和冻结执行器/成绩未修改。原13配置已获另一单模型Phase B核心计分接受，此次C1并不在该范围，需另复审修改项再验实现。

交付全套回归409项通过，git diff --check通过；测试数不是独立审查结论。
