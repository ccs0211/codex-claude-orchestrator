# 完全背包：编排任务起始项目

`knapsack.py` 的两个函数刻意保留 `NotImplementedError`，这是给模型实施的初始任务，不是已完成算法。直接运行这里的验收测试会失败，属于示例的预期起点。

需求、验收标准和固定测试命令位于上一级的 `knapsack_task.json`。从编排项目根目录，可以复制本例到外部目录并建立一个干净的 Git 起点：

```powershell
Copy-Item -Recurse .\examples\knapsack_demo ..\knapsack-work
git -C ..\knapsack-work init
git -C ..\knapsack-work add .
git -C ..\knapsack-work commit -m "Add knapsack starter"
python orchestrate.py run --repo ..\knapsack-work --task .\examples\knapsack_task.json
```

首次使用 Git 时需先配置自己的提交身份。任务要求只修改 `knapsack.py`，保留 `tests/`，并让 Claude 审查。产物在编排目录的 `runs/` 下。

仓库自身的测试命令为根目录的 `python -m unittest discover -s tests -v`，不会把这个待实现练习当作编排器的回归测试。
