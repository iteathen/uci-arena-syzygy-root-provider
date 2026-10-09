import unittest
import chess
from root_contract import admit_request
from root_provider import RootKnowledgeProvider, ProofError
from test_root_contract import request


class MissingDtz:
    def probe_wdl(self, board):
        return 0
    def probe_dtz(self, board):
        raise KeyError("missing")


class ProviderTests(unittest.TestCase):
    def test_live_claims_can_be_declined_for_a_proved_winning_legal_move(self):
        raw = request("7k/8/8/8/8/8/P7/7K w - - 0 1", ["h1g1", "h8g8", "g1h1", "g8h8"] * 2)
        raw["rules"]["claim_policy"] = "orthodoxy-live-claims-v1"
        raw["searchmoves"] = ["a2a4"]
        class Oracle:
            def probe_wdl(self, board):
                return 2 if board.turn == chess.WHITE else -2
            def probe_dtz(self, board):
                return 1
        result = list(RootKnowledgeProvider(Oracle(), {}).events(raw))[-1]
        self.assertEqual(result["status"], "exact")
        self.assertEqual(result["move"], "a2a4")
        self.assertEqual(result["result_class"], 1)
        self.assertEqual(result["rules"]["claim_policy"], "orthodoxy-live-claims-v1")

    def test_virtual_live_claim_never_becomes_an_exact_legal_move(self):
        raw = request("7k/8/8/8/8/8/P7/7K w - - 0 1", ["h1g1", "h8g8", "g1h1", "g8h8"] * 2)
        raw["rules"]["claim_policy"] = "orthodoxy-live-claims-v1"
        raw["searchmoves"] = ["a2a4"]
        class Oracle:
            def probe_wdl(self, board):
                return -2 if board.turn == chess.WHITE else 2
            def probe_dtz(self, board):
                return 1
        result = list(RootKnowledgeProvider(Oracle(), {}).events(raw))[-1]
        self.assertEqual(result["refinement"]["reason"], "claim_action_required")
        self.assertFalse(result["authority"]["exact_move"])
        self.assertIsNone(result["move"])
        self.assertEqual(result["safe_moves"], ["a2a4"])

    def test_rule_policy_changes_raw_classes_without_promoting_safety(self):
        for rule50, count in [(True, 3), (False, 1)]:
            raw = request()
            raw["searchmoves"] = raw["legal_moves"][:3]
            raw["rules"]["rule50"] = rule50
            class Oracle(MissingDtz):
                values = iter([1, -1, 0, 1])
                def probe_wdl(self, board):
                    return next(self.values)
            events = list(RootKnowledgeProvider(Oracle(), {"fixture": "raw"}).events(raw))
            self.assertEqual(len(events[0]["safe_moves"]), count)
            self.assertEqual(events[0]["status"], "safety_only")
            self.assertFalse(events[0]["authority"]["exact_move"])
            self.assertEqual(events[-1]["refinement"]["reason"], "missing_dtz")
            self.assertEqual(events[-1]["safe_moves"], events[0]["safe_moves"])

    def test_root_miss_and_child_dependency_have_distinct_authority(self):
        for child_missing in [False, True]:
            class Oracle(MissingDtz):
                calls = 0
                def probe_wdl(self, board):
                    self.calls += 1
                    if child_missing and self.calls == 1:
                        return 2
                    raise KeyError("missing")
            event = list(RootKnowledgeProvider(Oracle(), {}).events(request()))[0]
            self.assertEqual(event["status"], "deferred" if child_missing else "miss")
            self.assertIsNone(event["safe_moves"])
            self.assertFalse(event["authority"]["raw_wdl_safety"])

    def test_boolean_child_wdl_fails_before_integer_negation(self):
        class Oracle(MissingDtz):
            calls = 0
            def probe_wdl(self, board):
                self.calls += 1
                return 2 if self.calls == 1 else True
        with self.assertRaises(ProofError):
            list(RootKnowledgeProvider(Oracle(), {}).events(request()))

    def test_full_history_zeroing_moves_have_proved_outcome_and_first_boundary_distance(self):
        raw = request("7k/8/8/8/8/8/P7/7K b - - 0 1", ["h8g8"])
        raw["searchmoves"] = ["a2a4", "a2a3"]
        class Oracle:
            def probe_wdl(self, board):
                return 2 if board.turn == chess.WHITE else -2
            def probe_dtz(self, board):
                return 1 if board.turn == chess.WHITE else -1
        events = list(RootKnowledgeProvider(Oracle(), {}).events(raw))
        exact = events[-1]
        self.assertEqual(exact["status"], "exact")
        self.assertTrue(exact["authority"]["history_adjusted"])
        self.assertTrue(exact["authority"]["exact_move"])
        self.assertEqual(exact["result_class"], 1)
        self.assertTrue(all(row["boundary_plies"] == 1 for row in exact["refinement"]["rows"]))
        self.assertEqual(exact["move"], next(m for m in raw["legal_moves"] if m in raw["searchmoves"]))

    def test_reaching_third_occurrence_is_draw_before_any_nonterminal_dtz_probe(self):
        moves = ["b1b2", "c3c4", "b2b1", "c4c3", "b1b2", "c3c4", "b2b1"]
        raw = request(moves=moves)
        raw["searchmoves"] = ["c4c3"]
        class Oracle:
            dtz_calls = 0
            def probe_wdl(self, board):
                return -2 if board.turn == chess.BLACK else 2
            def probe_dtz(self, board):
                self.dtz_calls += 1
                return -5
        oracle = Oracle()
        exact = list(RootKnowledgeProvider(oracle, {}).events(raw))[-1]
        self.assertEqual(exact["result_class"], 0)
        self.assertEqual(exact["move"], "c4c3")
        self.assertEqual(oracle.dtz_calls, 1)  # Root dependency admission only.

    def test_nonzero_missing_prefix_never_becomes_exact_even_when_rule50_disabled(self):
        for rule50 in [True, False]:
            raw = request("8/8/8/8/8/2k5/8/KQ6 w - - 7 1")
            raw["rules"]["rule50"] = rule50
            result = list(RootKnowledgeProvider(MissingDtz(), {}).events(raw))[-1]
            self.assertEqual(result["refinement"]["reason"], "history_unavailable")
            self.assertFalse(result["authority"]["exact_move"])
            self.assertIsNotNone(result["safe_moves"])

    def test_capacity_cancellation_and_deadline_retain_completed_safety_without_partial_exactness(self):
        class Oracle(MissingDtz):
            def probe_dtz(self, board):
                return 1
        for mode in ["nodes", "depth", "cancel", "time"]:
            raw = request()
            if mode == "nodes":
                raw["limits"]["max_nodes"] = 1
            if mode == "depth":
                raw["limits"]["max_depth"] = 1
            cancelled = [False]
            now = [0.0]
            provider = RootKnowledgeProvider(Oracle(), {}, clock=lambda: now[0])
            stream = provider.events(raw, cancelled=lambda: cancelled[0])
            first = next(stream)
            safe = list(first["safe_moves"])
            if mode == "cancel":
                cancelled[0] = True
            if mode == "time":
                now[0] = 2.0
            final = next(stream)
            self.assertEqual(final["safe_moves"], safe)
            self.assertEqual(final["refinement"]["status"], "deferred")
            self.assertFalse(final["authority"]["exact_move"])
            self.assertIsNone(final["move"])
            self.assertEqual(final["refinement"]["rows"], [])

    def test_mutating_an_emitted_safety_snapshot_cannot_change_provider_authority(self):
        stream = RootKnowledgeProvider(MissingDtz(), {}).events(request())
        first = next(stream)
        safe = list(first["safe_moves"])
        first["safe_moves"].clear()
        self.assertEqual(next(stream)["safe_moves"], safe)

    def test_provider_substitution_failure_retains_safety_and_never_publishes_exactness(self):
        class Substituted(MissingDtz):
            def probe_dtz(self, board):
                raise ValueError("owned immutable dataset quarantined")
        stream = RootKnowledgeProvider(Substituted(), {}).events(request())
        safety = next(stream)
        final = next(stream)
        self.assertEqual(final["safe_moves"], safety["safe_moves"])
        self.assertEqual(final["refinement"]["reason"], "provider_failure")
        self.assertFalse(final["authority"]["exact_move"])


if __name__ == "__main__":
    unittest.main()
