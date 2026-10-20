# Python 约束 MPC：一维位置跟踪

这是可直接运行的名义控制示例，也提供独立的 Claude 审查入口。模型为无扰动、全状态可测的一维双积分器：

```text
x = [位置 p, 速度 v]，u = 加速度
p(k+1) = p(k) + dt*v(k) + 0.5*dt²*u(k)
v(k+1) = v(k) + dt*u(k)
```

默认采样时间 0.1s，预测时域 20 步。求出未来控制序列后仅施加第一个控制量，下一拍重新优化。

目标为 `x(1)..x(N-1)` 的 Q 加权跟踪误差、`x(N)` 的 P 加权终端误差、R 加权控制量平方以及输入增量平方之和。P 由离散代数 Riccati 方程得到；首个输入增量按上一拍实际施加的输入计算。

约束：加速度绝对值不超过 2m/s²、预测速度不超过 0.8m/s、每采样加速度变化不超过 0.5m/s²。最后一项对应默认采样下5m/s³的变化率。约束数值容限为 `1e-6`，内部采用其中1%的界限余量处理舍入误差，再按实际物理约束检查返回值。

求解采用 SciPy SLSQP、解析梯度和线性约束。失败、非有限候选、错误形状或明显约束违例会抛出 `MPCSolveError`；代码不截断失败候选并将其标记为成功。

## 运行

从仓库根目录进入示例：

```powershell
python -m pip install -r examples/mpc_demo/requirements.txt
cd examples/mpc_demo
python -m unittest -v
python run_demo.py
```

结果写入本例的 `artifacts/`：`mpc_tracking.png`、`trajectory.csv`、`metrics.json`。CSV 每行对应采样时刻，该行控制量施加在其后的采样区间；最后一行只有终态，没有后续控制，所以加速度为 NaN。

## 真实 Claude 审查

在配置了模型服务凭据的终端，从本例目录运行：

```powershell
python review_with_claude.py
```

程序重新执行固定测试和名义仿真，将完整源码、逐行编号、测试日志和验收标准自动提交给 Claude 只读审查。它通过上两级目录导入仓库内的 `orchestrate.py`，因此请保留本例的目录层级。

结果位于 `reviews/<run-id>/CLAUDE_REVIEW.md`，最新状态保存在 `review_status.json`。这些实际运行产物和凭据不随公开源码打包。没有凭据时只准备代码和测试材料，状态为 `awaiting_credentials`，不会伪造审查通过。API 还需支持结构化响应，单次普通聊天成功不代表所有 CLI 功能都已验证。

## 验证范围

单元测试涵盖独立动力学递推、代价梯度有限差分、正负方向闭环跟踪、实际约束、首拍输入变化、真实不可行初态、失败注入、坏候选和坏输入。

这是名义教学仿真，没有加入扰动、状态估计、参数误差、终端不变集或实时调度。DARE 终端权重不能单独证明带状态与输入变化约束的递归可行性或鲁棒稳定性；当前机器上的求解耗时也不能作为实时部署时限保证。

建模参考 [OSQP MPC 示例](https://osqp.org/docs/examples/mpc.html)，数值接口参考 [SciPy SLSQP 文档](https://docs.scipy.org/doc/scipy/reference/optimize.minimize-slsqp.html)。本例使用 SciPy，无需安装 OSQP。
