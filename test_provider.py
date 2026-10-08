import unittest
from provider import validate_request, RootProvider, ProviderError


class RequestTests(unittest.TestCase):
    def request(self):
        return {"schema": "uci_arena_syzygy_root_request_v1", "request_id": "test",
                "root_fence": "a" * 32,
                "fen": "8/8/8/8/8/2k5/8/KQ6 w - - 0 1",
                "legal_moves": ["b1b2"], "searchmoves": None}

    def test_rejects_unknown_fields_paths_and_malformed_fences(self):
        for field, value in [("path", "E:/other"), ("root_fence", "wrong"),
                             ("legal_moves", ["b1b2", "b1b2"]),
                             ("searchmoves", ["b1b3"]), ("fen", "bad")]:
            request = self.request()
            request[field] = value
            with self.assertRaises(ProviderError):
                validate_request(request)

    def test_accepts_bounded_valid_ingress_but_requires_complete_canonical_legal_set(self):
        request = self.request()
        self.assertEqual(validate_request(request)["root_fence"], "a" * 32)
        class NoProbe:
            def probe_wdl(self, board):
                raise AssertionError("incomplete GPU legal set must fail before table probing")
        with self.assertRaisesRegex(ProviderError, "legal set"):
            RootProvider(NoProbe(), {}).probe(request)

    def test_missing_tables_do_not_fabricate_an_exact_result(self):
        import chess
        request = self.request()
        board = chess.Board(request["fen"])
        request["legal_moves"] = [move.uci() for move in board.legal_moves]
        class Missing:
            def probe_wdl(self, board):
                raise KeyError("missing")
        result = RootProvider(Missing(), {}).probe(request)
        self.assertEqual(result["status"], "miss")
        self.assertFalse(result["exact"])
        self.assertIsNone(result["safe_moves"])
        self.assertEqual(result["root_fence"], request["root_fence"])

    def test_missing_child_dependency_is_deferred_not_a_verified_root_miss(self):
        import chess
        request = self.request()
        request["legal_moves"] = [move.uci() for move in chess.Board(request["fen"]).legal_moves]
        class Incomplete:
            calls = 0
            def probe_wdl(self, board):
                self.calls += 1
                if self.calls == 1:
                    return 2
                raise KeyError("child dependency missing")
        result = RootProvider(Incomplete(), {}).probe(request)
        self.assertEqual(result["status"], "deferred")
        self.assertIsNone(result["safe_moves"])
        self.assertFalse(result["authority"]["raw_wdl_safety"])

    def test_boolean_child_value_cannot_become_a_valid_integer_after_negation(self):
        import chess
        request = self.request()
        request["legal_moves"] = [move.uci() for move in chess.Board(request["fen"]).legal_moves]
        class Malformed:
            calls = 0
            def probe_wdl(self, board):
                self.calls += 1
                return 2 if self.calls == 1 else True
        with self.assertRaisesRegex(ProviderError, "child WDL"):
            RootProvider(Malformed(), {}).probe(request)

    def test_rule50_safety_compares_result_classes_not_cursed_win_preferences(self):
        import chess
        request = self.request()
        request["legal_moves"] = [move.uci() for move in chess.Board(request["fen"]).legal_moves]
        request["searchmoves"] = request["legal_moves"][:3]
        class DrawClasses:
            values = iter([1, -1, 0, 1])
            def probe_wdl(self, board):
                return next(self.values)
        result = RootProvider(DrawClasses(), {}).probe(request)
        self.assertEqual(result["safe_moves"], request["searchmoves"])
        self.assertFalse(result["exact"])


if __name__ == "__main__":
    unittest.main()
