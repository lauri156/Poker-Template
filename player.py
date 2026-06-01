from __future__ import annotations
from dataclasses import dataclass, field
from cards import Card


@dataclass
class Player:
    name: str
    chips: int
    is_human: bool = False
    hole_cards: list[Card] = field(default_factory=list)
    current_bet: int = 0
    folded: bool = False

    @property
    def hand(self) -> list[Card]:
        return self.hole_cards

    def reset_for_hand(self) -> None:
        self.hole_cards.clear()
        self.current_bet = 0
        self.folded = False

    def receive(self, cards: list[Card]) -> None:
        self.hole_cards.extend(cards)

    def bet(self, amount: int) -> int:
        if amount < 0:
            raise ValueError("bet amount cannot be negative")
        wager = min(amount, self.chips)
        self.chips -= wager
        self.current_bet += wager
        return wager

    @property
    def active(self) -> bool:
        return not self.folded and self.chips > 0
