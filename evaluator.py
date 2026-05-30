"""Five-card hand evaluator used to rank Texas Hold'em showdowns."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from enum import IntEnum
from itertools import combinations

from cards import Card


class HandCategory(IntEnum):
    HIGH_CARD = 0
    ONE_PAIR = 1
    TWO_PAIR = 2
    THREE_OF_A_KIND = 3
    STRAIGHT = 4
    FLUSH = 5
    FULL_HOUSE = 6
    FOUR_OF_A_KIND = 7
    STRAIGHT_FLUSH = 8


@dataclass(frozen=True, order=True)
class HandRank:
    category: HandCategory
    tiebreakers: tuple

    @property
    def label(self) -> str:
        return self.category.name.replace("_", " ").title()


class HandEvaluator:
    def best_rank(self, cards: list[Card]) -> HandRank:
        if len(cards) < 5:
            raise ValueError("need at least 5 cards")
        return max(self._rank_five(list(combo)) for combo in combinations(cards, 5))

    def _rank_five(self, cards: list[Card]) -> HandRank:
        ranks = sorted([card.rank for card in cards], reverse=True)
        counts = Counter(ranks)
        # Sort groups by (count desc, rank desc) so highest group comes first
        groups = sorted(counts.items(), key=lambda x: (x[1], x[0]), reverse=True)
        is_flush = len(set(card.suit for card in cards)) == 1
        straight_high = self._straight_high(ranks)

        if is_flush and straight_high:
            return HandRank(HandCategory.STRAIGHT_FLUSH, (straight_high,))
        if groups[0][1] == 4:
            four_rank = groups[0][0]
            kicker = groups[1][0]
            return HandRank(HandCategory.FOUR_OF_A_KIND, (four_rank, kicker))
        if groups[0][1] == 3 and groups[1][1] == 2:
            return HandRank(HandCategory.FULL_HOUSE, (groups[0][0], groups[1][0]))
        if is_flush:
            return HandRank(HandCategory.FLUSH, tuple(ranks))
        if straight_high:
            return HandRank(HandCategory.STRAIGHT, (straight_high,))
        if groups[0][1] == 3:
            three_rank = groups[0][0]
            kickers = sorted([g[0] for g in groups[1:]], reverse=True)
            return HandRank(HandCategory.THREE_OF_A_KIND, (three_rank,) + tuple(kickers))
        if groups[0][1] == 2 and groups[1][1] == 2:
            pair1 = max(groups[0][0], groups[1][0])
            pair2 = min(groups[0][0], groups[1][0])
            kicker = groups[2][0]
            return HandRank(HandCategory.TWO_PAIR, (pair1, pair2, kicker))
        if groups[0][1] == 2:
            pair_rank = groups[0][0]
            kickers = sorted([g[0] for g in groups[1:]], reverse=True)
            return HandRank(HandCategory.ONE_PAIR, (pair_rank,) + tuple(kickers))
        return HandRank(HandCategory.HIGH_CARD, tuple(ranks))

    def _straight_high(self, ranks: list[int]) -> int | None:
        unique = sorted(set(ranks), reverse=True)
        # Check regular straights (5 consecutive unique ranks)
        for i in range(len(unique) - 4):
            window = unique[i:i + 5]
            if window[0] - window[4] == 4:
                return window[0]
        # Check wheel: A-2-3-4-5 (ace plays as 1, returns 5-high)
        if {14, 2, 3, 4, 5}.issubset(set(unique)):
            return 5
        return None
