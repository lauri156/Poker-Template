from __future__ import annotations

from cards import Deck
from evaluator import HandEvaluator
from player import Player
from table import Table
from ui import ConsoleUI
from typing import Any

class TexasHoldemGame:
    def __init__(self, players: list[Player], small_blind: int = 5, big_blind: int = 10, ui: Any = None) -> None:
        if len(players) < 2:
            raise ValueError("need at least 2 players")
        self.players = players
        self.small_blind = small_blind
        self.big_blind = big_blind
        self.table = Table()
        self.evaluator = HandEvaluator()
        self.ui = ui if ui is not None else ConsoleUI()

    def play_hand(self) -> None:
        deck = Deck()
        self.table.reset()
        for player in self.players:
            player.reset_for_hand()
        for player in self.players:
            player.receive(deck.draw(2))
        self._post_blinds()
        self._show_human_cards()
        self._betting_round("Pre-Flop")
        self._deal_community(deck, 3, "Flop")
        self._betting_round("Flop")
        self._deal_community(deck, 1, "Turn")
        self._betting_round("Turn")
        self._deal_community(deck, 1, "River")
        self._betting_round("River")
        self._showdown()
        if hasattr(self.ui, 'hand_over'):
            self.ui.hand_over()

    def _post_blinds(self) -> None:
        small = self.players[0].bet(self.small_blind)
        big = self.players[1].bet(self.big_blind)
        self.table.add_to_pot(small)
        self.table.add_to_pot(big)
        self.ui.show_message(
            f"{self.players[0].name} posts {small}; {self.players[1].name} posts {big}"
        )

    def _show_human_cards(self) -> None:
        for player in self.players:
            if player.is_human:
                cards_str = self.ui.format_cards(player.hole_cards)
                self.ui.show_message(f"{player.name}: {cards_str}")

    def _deal_community(self, deck: Deck, count: int, street: str) -> None:
        if self._only_one_player_left():
            return
        self.table.community_cards.extend(deck.draw(count))
        self.ui.show_message(f"\n-- {street} --")
        self.ui.show_table(self.table.community_cards, self.table.pot)

    def _betting_round(self, street: str) -> None:
        if self._only_one_player_left():
            return

        current_bet = max(p.current_bet for p in self.players)
        for player in self.players:
            if player.folded:
                continue
            if not player.active:
                continue
            call_amount = current_bet - player.current_bet
            if player.is_human:
                action = self.ui.ask_action(player, call_amount)
            else:
                action = self._bot_action(player, call_amount)
                self.ui.show_message(f"{player.name} {action}s")

            if action == "fold":
                player.folded = True
            elif action == "call":
                paid = player.bet(call_amount)
                self.table.add_to_pot(paid)
            elif action == "raise":
                minimum = max(self.big_blind, call_amount + self.big_blind)
                maximum = player.chips
                if player.is_human and maximum >= minimum:
                    raise_amount = self.ui.ask_raise_amount(minimum, maximum)
                else:
                    raise_amount = min(minimum, maximum)
                paid = player.bet(raise_amount)
                self.table.add_to_pot(paid)
                current_bet = player.current_bet

            if self._only_one_player_left():
                break

        for player in self.players:
            player.current_bet = 0

    def _bot_action(self, player: Player, call_amount: int) -> str:
        if call_amount > player.chips // 2:
            return "fold"
        return "call"

    def _showdown(self) -> None:
        active_players = [p for p in self.players if not p.folded]
        if len(active_players) == 1:
            winner = active_players[0]
            winner.chips += self.table.pot
            self.ui.show_message(f"\n{winner.name} wins {self.table.pot} chips (last player standing)!")
            return

        ranked = []
        for player in active_players:
            cards = player.hole_cards + self.table.community_cards
            rank = self.evaluator.best_rank(cards)
            ranked.append((rank, player))

        best_rank = max(r for r, _ in ranked)
        winners = [p for r, p in ranked if r == best_rank]

        share = self.table.pot // len(winners)
        for winner in winners:
            winner.chips += share

        winner_names = ", ".join(w.name for w in winners)
        self.ui.show_message(f"\n{winner_names} wins {share} chips with {best_rank.label}!")

    def _only_one_player_left(self) -> bool:
        return sum(1 for p in self.players if not p.folded) == 1
