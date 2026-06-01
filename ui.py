"""Console input/output helpers."""

from __future__ import annotations

from cards import Card
from player import Player


class ConsoleUI:

    def show_table(self, community_cards: list[Card], pot: int) -> None:
        if community_cards:
            board = self.format_cards(community_cards)
        else:
            board = "(empty)"

        print("Board: " + board)
        print("Pot: " + str(pot))

    def show_player(self, player: Player) -> None:
        print("Player: " + player.name)
        print("Hand: " + self.format_cards(player.hand))
        print("Chips: " + str(player.chips))

    def ask_action(self, player: Player, call_amount: int) -> str:
        while True:
            action = input(
                f"{player.name} – call/check ({call_amount}), raise, or fold? "
            ).strip().lower()

            if action in {'c', 'call', 'check'}:
                return 'call'
            elif action in {'r', 'raise'}:
                return 'raise'
            elif action in {'f', 'fold'}:
                return 'fold'
            else:
                print("Invalid input. Please type call/check, raise, or fold.")

    def ask_raise_amount(self, minimum: int, maximum: int) -> int:
        while True:
            raw = input(f"Raise amount ({minimum}–{maximum}): ").strip()
            try:
                amount = int(raw)
            except ValueError:
                print("Please enter a valid number.")
                continue

            if minimum <= amount <= maximum:
                return amount
            else:
                print(f"Amount must be between {minimum} and {maximum}.")

    def show_message(self, message: str) -> None:
        print(message)

    def format_cards(self, cards: list[Card]) -> str:
        return " ".join(str(card) for card in cards)
