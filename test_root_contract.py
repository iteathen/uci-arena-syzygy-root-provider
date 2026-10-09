import copy
import unittest
import chess
from root_contract import admit_request, effective_key, ContractError


def request(origin="8/8/8/8/8/2k5/8/KQ6 w - - 0 1", moves=()):
    board = chess.Board(origin)
    for text in moves:
        board.push_uci(text)
    return {"schema": "uci_arena_syzygy_root_request_v2", "request_id": "fixture", "root_fence": "a" * 32,
            "position": {"origin_fen": origin, "moves": list(moves)},
            "legal_moves": [move.uci() for move in board.legal_moves], "searchmoves": None,
            "rules": {"rule50": True, "repetition": "threefold-as-draw", "claim_policy": "adjudicated-claims-as-draw"},
            "history_mode": "replay-from-origin", "limits": {"max_nodes": 128, "max_depth": 16, "max_milliseconds": 1000}}


class ContractTests(unittest.TestCase):
    def test_closed_byte_and_type_limits_precede_external_work(self):
        for mutate in [lambda x: x.update(path="E:/other"), lambda x: x.update(schema="unknown-v3"),
                       lambda x: x["rules"].update(rule50="true"), lambda x: x["limits"].update(max_nodes=True),
                       lambda x: x["limits"].update(max_nodes=16385), lambda x: x["position"].update(moves=["b1b2"] * 4097),
                       lambda x: x.update(root_fence="bad")]:
            raw = request()
            mutate(raw)
            with self.assertRaises(ContractError):
                admit_request(raw)

    def test_actual_legal_replay_and_complete_gpu_move_set_required(self):
        for mutate in [lambda x: x["position"].update(moves=["b1b8"]), lambda x: x.update(legal_moves=x["legal_moves"][:-1]),
                       lambda x: x.update(searchmoves=["a1h8"])]:
            raw = request()
            mutate(raw)
            with self.assertRaises(ContractError):
                admit_request(raw)

    def test_complete_reversible_prefix_is_owned_and_digest_binds_all_request_meaning(self):
        moves = ["b1b2", "c3c4", "b2b1", "c4c3", "b1b2", "c3c4", "b2b1"]
        raw = request(moves=moves)
        admitted = admit_request(raw)
        self.assertTrue(admitted.history_available)
        self.assertEqual(len(admitted.keys), 8)
        self.assertTrue(admitted.any_prior_repetition)
        self.assertEqual(admitted.keys[-1], effective_key(chess.Board(admitted.fen)))
        raw["position"]["moves"].clear()
        self.assertEqual(len(admitted.moves), 7)
        different = request(moves=moves)
        different["rules"]["rule50"] = False
        self.assertNotEqual(admit_request(different).request_sha256, admitted.request_sha256)

    def test_unknown_nonzero_origin_cannot_invent_full_history(self):
        admitted = admit_request(request(origin="8/8/8/8/8/2k5/8/KQ6 w - - 7 1"))
        self.assertFalse(admitted.history_available)
        self.assertEqual(admitted.history_reason, "history_unavailable")

    def test_zeroing_restores_a_complete_one_key_prefix(self):
        raw = request(origin="7k/8/8/8/8/8/P7/7K w - - 7 1", moves=["a2a4"])
        admitted = admit_request(raw)
        self.assertTrue(admitted.history_available)
        self.assertEqual(len(admitted.keys), 1)
        self.assertEqual(chess.Board(admitted.fen).halfmove_clock, 0)

    def test_unhashable_searchmove_is_a_closed_contract_rejection(self):
        raw = request()
        raw["searchmoves"] = [{"move": "a1a2"}]
        with self.assertRaises(ContractError):
            admit_request(raw)

    def test_effective_repetition_identity_ignores_nominal_or_pinned_ep(self):
        for fen in ["7k/8/8/4p3/8/8/8/K7 w - e6 0 1", "4r2k/8/8/3pP3/8/8/8/4K3 w - d6 0 1"]:
            self.assertEqual(effective_key(chess.Board(fen)).split()[-1], "-")
        self.assertEqual(effective_key(chess.Board("7k/8/8/3pP3/8/8/8/4K3 w - d6 0 1")).split()[-1], "d6")


if __name__ == "__main__":
    unittest.main()
