# 回归测试

测试覆盖切分、原始 34 题冻结、正式矩阵样本量、原始数据完整性工具、图表小圆点约束，以及单次运行参数映射和非法 overlap 拒绝。修改配置或生成逻辑时先写/改测试，再改实现。

```powershell
& .\embedding-test\.venv\Scripts\python.exe -m unittest discover -s performance-test\tests -v
```
