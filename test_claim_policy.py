"""Independent public-chess claim oracle; no product CPU search authority."""
from collections import Counter
import time
import unittest
import chess
from root_contract import effective_key
from root_provider import RootKnowledgeProvider, Budget


class ClaimPolicyTests(unittest.TestCase):
    def test_ledger_claims_and_automatic_draws_match_public_stack_oracle(self):
        provider = RootKnowledgeProvider(None, {})
        cycle = ["h1g1", "h8g8", "g1h1", "g8h8"]
        for turns in [0, 1, 2, 3, 4]:
            board = chess.Board("7k/8/8/8/8/8/P7/7K w - - 0 1")
            counts = Counter([effective_key(board)])
            for text in cycle * turns:
                board.push_uci(text)
                counts[effective_key(board)] += 1
            budget = Budget(time.monotonic, lambda: False, time.monotonic(), milliseconds=1000)
            self.assertEqual(provider._claim_available(board, counts, True, list(board.legal_moves), budget),
                             board.can_claim_threefold_repetition() or board.can_claim_fifty_moves())
            self.assertEqual(provider._terminal_draw(board, counts, True, "orthodoxy-live-claims-v1"),
                             board.is_fivefold_repetition() or board.is_seventyfive_moves())
        for clock in [98, 99, 100, 149, 150]:
            board = chess.Board(f"7k/8/8/8/8/8/P7/7K w - - {clock} 1")
            budget = Budget(time.monotonic, lambda: False, time.monotonic(), milliseconds=1000)
            self.assertEqual(provider._claim_available(board, Counter([effective_key(board)]), True, list(board.legal_moves), budget), board.can_claim_fifty_moves())

    def test_mate_precedes_automatic_draw_and_unavailable_dtz(self):
        class NoProbes:
            def probe_wdl(self, board):
                raise AssertionError("mate is legal terminal")
            def probe_dtz(self, board):
                raise AssertionError("mate is legal terminal")
        board = chess.Board("7k/6Q1/5K2/8/8/8/8/8 b - - 150 1")
        self.assertTrue(board.is_checkmate())
        provider = RootKnowledgeProvider(NoProbes(), {})
        budget = Budget(time.monotonic, lambda: False, time.monotonic(), milliseconds=1000)
        self.assertEqual(provider._solve(board, Counter({effective_key(board): 5}), True, budget, 0, "orthodoxy-live-claims-v1"), (-1, 0))

    def test_intended_move_claim_is_not_a_forced_terminal(self):
        board = chess.Board("7k/8/8/8/8/8/P7/7K w - - 0 1")
        counts = Counter([effective_key(board)])
        for text in ["h1g1", "h8g8", "g1h1", "g8h8", "h1g1", "h8g8", "g1h1"]:
            board.push_uci(text)
            counts[effective_key(board)] += 1
        self.assertFalse(board.is_repetition(3))
        self.assertTrue(board.can_claim_threefold_repetition())
        provider = RootKnowledgeProvider(None, {})
        budget = Budget(time.monotonic, lambda: False, time.monotonic(), milliseconds=1000)
        self.assertTrue(provider._claim_available(board, counts, True, list(board.legal_moves), budget))
        self.assertFalse(provider._terminal_draw(board, counts, True, "orthodoxy-live-claims-v1"))


if __name__ == "__main__":
    unittest.main()
