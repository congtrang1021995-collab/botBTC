from __future__ import annotations

import unittest

from trading_bot.core.swings import SwingState, update_swings
from tests.helpers import make_bar


class SwingTests(unittest.TestCase):
    def test_pivot_is_confirmed_only_after_right_legs_close(self) -> None:
        state = SwingState()
        highs = (2.0, 3.0, 6.0, 4.0, 2.0)
        snapshots = []
        for index, high in enumerate(highs):
            state, snapshot = update_swings(
                state,
                make_bar(index, 1.0, high=high, low=0.0),
                legs=2,
            )
            snapshots.append(snapshot)

        self.assertTrue(all(item.confirmed_high is None for item in snapshots[:4]))
        pivot = snapshots[4].confirmed_high
        self.assertIsNotNone(pivot)
        assert pivot is not None
        self.assertEqual(pivot.pivot_bar_index, 2)
        self.assertEqual(pivot.confirmation_bar_index, 4)
        self.assertEqual(pivot.price, 6.0)

    def test_equal_neighbor_rejects_strict_pivot(self) -> None:
        state = SwingState()
        for index, high in enumerate((2.0, 6.0, 6.0, 4.0, 2.0)):
            state, snapshot = update_swings(
                state,
                make_bar(index, 1.0, high=high, low=0.0),
                legs=2,
            )
        self.assertIsNone(snapshot.confirmed_high)
        self.assertIsNone(snapshot.last_high)


if __name__ == "__main__":
    unittest.main()

