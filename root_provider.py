"""Bounded root-only tablebase proof owner; no evaluator or engine search API."""
from collections import Counter
import copy
import time
import chess
from root_contract import admit_request, effective_key, MAX_MILLISECONDS

RESULT_SCHEMA = "uci_arena_syzygy_root_result_v2"


class ProofError(ValueError):
    pass


class Deferred(Exception):
    def __init__(self, reason):
        self.reason = reason


class Budget:
    def __init__(self, clock, cancelled, start, *, milliseconds, nodes=16384, depth=128):
        self.clock, self.cancelled = clock, cancelled
        self.deadline = start + milliseconds / 1000
        self.maximum_nodes, self.maximum_depth = nodes, depth
        self.nodes = 0

    def check(self):
        if self.cancelled():
            raise Deferred("cancelled")
        if self.clock() >= self.deadline:
            raise Deferred("deadline")

    def visit(self, depth):
        self.check()
        if depth > self.maximum_depth:
            raise Deferred("depth_capacity")
        if self.nodes >= self.maximum_nodes:
            raise Deferred("node_capacity")
        self.nodes += 1


def result_class(wdl, rule50):
    if type(wdl) is not int or wdl not in (-2, -1, 0, 1, 2):
        raise ProofError("invalid_wdl")
    return (1 if wdl > 0 else -1 if wdl < 0 else 0) if not rule50 else (1 if wdl == 2 else -1 if wdl == -2 else 0)


class RootKnowledgeProvider:
    def __init__(self, tablebase, identity, *, maximum_pieces=6, generation="0" * 32, clock=time.monotonic):
        if type(maximum_pieces) is not int or not 3 <= maximum_pieces <= 6:
            raise ProofError("invalid_provider_cardinality")
        self.tablebase, self.identity = tablebase, copy.deepcopy(identity)
        self.maximum_pieces, self.generation, self.clock = maximum_pieces, generation, clock

    def _wdl(self, board, budget):
        budget.check()
        raw = board.copy(stack=False)
        raw.halfmove_clock = 0
        value = self.tablebase.probe_wdl(raw)
        result_class(value, True)  # Strict integer validation before negation.
        budget.check()
        return value

    def _dtz(self, board, budget):
        budget.check()
        try:
            value = self.tablebase.probe_dtz(board.copy(stack=False))
        except KeyError as error:
            raise Deferred("missing_dtz") from error
        if type(value) is not int or not -2147483647 <= value <= 2147483647:
            raise ProofError("invalid_dtz")
        budget.check()
        return value  # Recorded as rounded evidence, never exact clock arithmetic.

    def _claim_available(self, board, counts, rule50, legal, budget):
        if counts[effective_key(board)] >= 3 or rule50 and board.halfmove_clock >= 100:
            return True
        # A live claim can name an intended legal move without executing it.
        for move in legal:
            budget.check()
            zeroing = board.is_zeroing(move)
            board.push(move)
            try:
                if not zeroing and (counts[effective_key(board)] >= 2 or rule50 and board.halfmove_clock >= 100):
                    return True
            finally:
                board.pop()
        return False

    def _terminal_draw(self, board, counts, rule50, claim_policy):
        if claim_policy == "orthodoxy-live-claims-v1":
            return counts[effective_key(board)] >= 5 or board.halfmove_clock >= 150
        return counts[effective_key(board)] >= 3 or rule50 and board.halfmove_clock >= 100

    def _solve(self, board, counts, rule50, budget, depth, claim_policy="adjudicated-claims-as-draw"):
        budget.visit(depth)
        legal = list(board.legal_moves)
        # Terminal legality precedes draw clocks and repetition.
        if not legal:
            return (-1, 0) if board.is_check() else (0, 0)
        if board.is_insufficient_material():
            return 0, 0
        if self._terminal_draw(board, counts, rule50, claim_policy):
            return 0, 0
        if board.halfmove_clock == 0:
            try:
                return result_class(self._wdl(board, budget), rule50), 0
            except KeyError as error:
                raise Deferred("missing_child_wdl") from error
        self._dtz(board, budget)
        claim = claim_policy == "orthodoxy-live-claims-v1" and self._claim_available(board, counts, rule50, legal, budget)
        proved = [(0, 0)] if claim else []
        for move in legal:
            budget.check()
            zeroing = board.is_zeroing(move)
            board.push(move)
            key = effective_key(board)
            child_counts = Counter() if zeroing else counts
            child_counts[key] += 1
            try:
                outcome, distance = self._solve(board, child_counts, rule50, budget, depth + 1, claim_policy)
                outcome = -outcome
                proved.append((outcome, distance + 1 if outcome else 0))
            finally:
                child_counts[key] -= 1
                if child_counts[key] == 0:
                    del child_counts[key]
                board.pop()
        best = max(value for value, _ in proved)
        distances = [distance for value, distance in proved if value == best]
        return best, min(distances) if best > 0 else max(distances) if best < 0 else 0

    def events(self, request, *, cancelled=lambda: False):
        start = self.clock()
        ingress = Budget(self.clock, cancelled, start, milliseconds=MAX_MILLISECONDS)
        admitted = admit_request(request, ingress.check)
        budget = Budget(self.clock, cancelled, start, milliseconds=admitted.max_milliseconds,
                        nodes=admitted.max_nodes, depth=admitted.max_depth)
        board = chess.Board(admitted.fen)
        result = {"schema": RESULT_SCHEMA, "request_id": admitted.request_id, "root_fence": admitted.root_fence,
                  "request_sha256": admitted.request_sha256, "provider_generation": self.generation,
                  "provider_identity": self.identity, "sequence": 0, "status": "not_applicable", "safe_moves": None,
                  "move": None, "result_class": None, "raw": {"zero_clock_abstraction": True, "wdl": None, "rows": []},
                  "rules": {"rule50": admitted.rule50, "repetition": "threefold-as-draw", "claim_policy": admitted.claim_policy},
                  "history": {"encoding": "effective-fen4-v1", "available": admitted.history_available,
                              "count": len(admitted.keys), "any_prior_repetition": admitted.any_prior_repetition},
                  "authority": {"raw_wdl_safety": False, "history_adjusted": False, "exact_move": False},
                  "refinement": {"status": "not_started", "reason": None, "rows": [], "nodes": 0,
                                 "metric": "reversible-minimax-plies-to-zeroing-or-mate"}}
        if board.castling_rights or len(board.piece_map()) > self.maximum_pieces or not admitted.legal_moves or board.is_insufficient_material():
            result["reason"] = "outside_root_profile"
            yield copy.deepcopy(result)
            return
        root_admitted = False
        rows = []
        try:
            root_wdl = self._wdl(board, budget)
            root_admitted = True
            for text in admitted.allowed_moves:
                budget.check()
                child = board.copy(stack=False)
                child.push_uci(text)
                value = 2 if child.is_checkmate() else 0 if child.is_stalemate() or child.is_insufficient_material() else -self._wdl(child, budget)
                rows.append({"move": text, "wdl": value, "result_class": result_class(value, admitted.rule50)})
            budget.check()
        except KeyError:
            result["status"] = "deferred" if root_admitted else "miss"
            result["reason"] = "missing_child_wdl" if root_admitted else "missing_root_wdl"
            yield copy.deepcopy(result)
            return
        except Deferred as error:
            result["status"], result["reason"] = "deferred", error.reason
            yield copy.deepcopy(result)
            return
        best_raw = max(row["result_class"] for row in rows)
        safe = tuple(row["move"] for row in rows if row["result_class"] == best_raw)
        result.update(status="safety_only", safe_moves=list(safe))
        result["raw"].update(wdl=root_wdl, rows=rows)
        result["authority"]["raw_wdl_safety"] = True
        result["refinement"]["status"] = "pending"
        yield copy.deepcopy(result)  # Never lend the retained safety authority.
        result["sequence"] = 1
        try:
            budget.check()
            if not admitted.history_available:
                raise Deferred(admitted.history_reason)
            counts = Counter(admitted.keys)
            if self._terminal_draw(board, counts, admitted.rule50, admitted.claim_policy):
                raise Deferred("terminal_root_engine_owned")
            claim = admitted.claim_policy == "orthodoxy-live-claims-v1" and self._claim_available(board, counts, admitted.rule50, list(board.legal_moves), budget)
            stored_dtz = self._dtz(board, budget) if board.halfmove_clock else None
            refined = []
            for text in admitted.allowed_moves:
                child = board.copy(stack=False)
                move = chess.Move.from_uci(text)
                child_counts = Counter() if child.is_zeroing(move) else counts.copy()
                child.push(move)
                child_counts[effective_key(child)] += 1
                value, distance = self._solve(child, child_counts, admitted.rule50, budget, 1, admitted.claim_policy)
                value = -value
                refined.append({"move": text, "result_class": value, "boundary_plies": distance + 1 if value else 0})
            budget.check()
            best = max(row["result_class"] for row in refined)
            if claim and best < 0:
                raise Deferred("claim_action_required")
            choices = [row for row in refined if row["result_class"] == best and row["move"] in safe]
            if not choices:
                raise ProofError("safety_proof_conflict")
            order = {text: index for index, text in enumerate(admitted.legal_moves)}
            chosen = min(choices, key=lambda row: (row["boundary_plies"] if best > 0 else -row["boundary_plies"] if best < 0 else 0, order[row["move"]]))
            result.update(status="exact", move=chosen["move"], result_class=best)
            result["authority"].update(history_adjusted=True, exact_move=True)
            result["refinement"].update(status="complete", rows=refined, stored_root_dtz=stored_dtz, nodes=budget.nodes)
        except Deferred as error:
            result["refinement"].update(status="deferred", reason=error.reason, nodes=budget.nodes)
        except (KeyError, OSError, ValueError):
            result["refinement"].update(status="deferred", reason="provider_failure", nodes=budget.nodes)
        yield copy.deepcopy(result)
