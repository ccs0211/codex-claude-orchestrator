"""完全背包（每种物品可无限次选取）。"""


def unbounded_knapsack(weights, values, capacity):
    """返回容量不超过 capacity 时可获得的最大总价值。"""
    raise NotImplementedError


def unbounded_knapsack_solution(weights, values, capacity):
    """返回 (最大总价值, counts)，counts[i] 为第 i 种物品的选取次数。"""
    raise NotImplementedError
