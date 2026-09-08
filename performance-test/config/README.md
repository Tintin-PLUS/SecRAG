# 测试配置

- `retest.json`：默认正式小切分矩阵；修改变量后必须新建 Session，不能覆盖旧结果。
- `retest_smoke.json`：快速验证进程、数据结构和功能闭环，不用于选型结论。
- `retest_large_hardware_matrix.json`：历史大切分复测；硬件阶段覆盖三模型、4/8/14 线程档、300/50—500/80—800/120、K=3/5/10，共 81 个组合，每组合 3 轮。

切分名称、参数、轮次、样本数和硬件线程限额都以 JSON 为唯一真相源，脚本与报告不得另设一份隐藏默认值。

正式字符切分矩阵为 `100/20`、`150/30`、`200/40`，另设 `structure-200`；跨模型受控比较固定使用 `baseline_chunk_config=fixed-150-30`。三个 fixed 配置均为 20% 重叠。

三模型大矩阵通过现有 `run_formal_tests.ps1 -ConfigPath .\performance-test\config\retest_large_hardware_matrix.json` 运行，不需要另一套执行器；输出必须使用新的 Session ID。

这些值不是冒充“统一行业标准”：当前切分器的单位是中文字符。LangChain 官方递归切分示例使用 100/20，并专门列出中文标点分隔符；Haystack 默认 200 的单位是词，RAGFlow 默认 512 的单位是 token，不能直接照搬。100/20 是开源锚点，150/30、200/40 是围绕它的单变量实验点。

- https://docs.langchain.com/oss/python/integrations/splitters/recursive_text_splitter
- https://docs.haystack.deepset.ai/docs/documentsplitter
- https://github.com/infiniflow/ragflow/blob/main/docs/guides/agent/ingestion_pipeline/configure_chunker_component.md
