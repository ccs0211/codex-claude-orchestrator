import random
import sys
import unittest
from functools import lru_cache
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from knapsack import unbounded_knapsack, unbounded_knapsack_solution


def brute_force(weights, values, capacity):
    @lru_cache(maxsize=None)
    def best(cap):
        return max([0] + [v + best(cap - w) for w, v in zip(weights, values) if w <= cap])
    return best(capacity)


class KnapsackTests(unittest.TestCase):
    def test_classic_cases(self):
        self.assertEqual(unbounded_knapsack([1, 3, 4], [15, 20, 30], 4), 60)
        self.assertEqual(unbounded_knapsack([5, 10, 15], [10, 30, 20], 100), 300)
        self.assertEqual(unbounded_knapsack([2], [3], 7), 9)

    def test_item_reused(self):
        self.assertEqual(unbounded_knapsack([3], [5], 10), 15)

    def test_edge_cases(self):
        self.assertEqual(unbounded_knapsack([], [], 10), 0)
        self.assertEqual(unbounded_knapsack([1, 2], [1, 2], 0), 0)
        self.assertEqual(unbounded_knapsack([5, 6], [10, 20], 4), 0)

    def test_matches_brute_force(self):
        rng = random.Random(20261020)
        for _ in range(200):
            n = rng.randint(1, 5)
            weights = [rng.randint(1, 10) for _ in range(n)]
            values = [rng.randint(0, 30) for _ in range(n)]
            capacity = rng.randint(0, 40)
            self.assertEqual(unbounded_knapsack(weights, values, capacity),
                             brute_force(tuple(weights), tuple(values), capacity))

    def test_solution_counts_are_consistent(self):
        rng = random.Random(7)
        for _ in range(100):
            n = rng.randint(1, 5)
            weights = [rng.randint(1, 10) for _ in range(n)]
            values = [rng.randint(0, 30) for _ in range(n)]
            capacity = rng.randint(0, 40)
            best, counts = unbounded_knapsack_solution(weights, values, capacity)
            self.assertEqual(len(counts), n)
            self.assertTrue(all(isinstance(c, int) and c >= 0 for c in counts))
            self.assertLessEqual(sum(c * w for c, w in zip(counts, weights)), capacity)
            self.assertEqual(sum(c * v for c, v in zip(counts, values)), best)
            self.assertEqual(best, unbounded_knapsack(weights, values, capacity))

    def test_invalid_input(self):
        for args in (([1, 2], [1], 5), ([0], [1], 5), ([-1], [1], 5), ([1], [-1], 5), ([1], [1], -1)):
            with self.assertRaises(ValueError):
                unbounded_knapsack(*args)
            with self.assertRaises(ValueError):
                unbounded_knapsack_solution(*args)

    def test_large_capacity_is_fast(self):
        weights = list(range(1, 101))
        values = [w * 3 + (w % 7) for w in weights]
        self.assertEqual(unbounded_knapsack(weights, values, 100000),
                         unbounded_knapsack_solution(weights, values, 100000)[0])


if __name__ == "__main__":
    unittest.main()
