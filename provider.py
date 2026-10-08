"""Independent offline root-safety provider; public python-chess APIs only.

This candidate deliberately grants no history-adjusted or exact move authority.
It is not an engine, evaluator or active-leaf search callback.
"""
import json
import re
import time
import chess
import chess.syzygy

REQUEST_SCHEMA = "uci_arena_syzygy_root_request_v1"
RESULT_SCHEMA = "uci_arena_syzygy_root_result_v1"
MOVE = re.compile(r"[a-h][1-8][a-h][1-8][qrbn]?\Z")
HEX128 = re.compile(r"[0-9a-f]{32}\Z")


class ProviderError(ValueError):
    pass


def validate_request(request):
    fields = {"schema", "request_id", "root_fence", "fen", "legal_moves", "searchmoves"}
    if not isinstance(request, dict) or set(request) != fields:
        raise ProviderError("closed root request fields required")
    if len(json.dumps(request, ensure_ascii=False).encode("utf-8")) > 65536:
        raise ProviderError("root request exceeds byte bound")
    if request["schema"] != REQUEST_SCHEMA:
        raise ProviderError("root request major is unsupported")
    if not isinstance(request["request_id"], str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", request["request_id"]):
        raise ProviderError("invalid request identity")
    if not isinstance(request["root_fence"], str) or not HEX128.fullmatch(request["root_fence"]):
        raise ProviderError("invalid opaque root fence")
    if not isinstance(request["fen"], str) or len(request["fen"]) > 256 or any(ord(c) < 32 for c in request["fen"]):
        raise ProviderError("invalid root FEN")
    try:
        chess.Board(request["fen"])
    except ValueError as error:
        raise ProviderError("invalid root FEN") from error
    moves = request["legal_moves"]
    if not isinstance(moves, list) or len(moves) > 256 or any(not isinstance(m, str) or not MOVE.fullmatch(m) for m in moves) or len(set(moves)) != len(moves):
        raise ProviderError("invalid complete root legal set")
    restriction = request["searchmoves"]
    if restriction is not None and (not isinstance(restriction, list) or not restriction or len(restriction) > 256 or any(not isinstance(m, str) or m not in moves for m in restriction) or len(set(restriction)) != len(restriction)):
        raise ProviderError("invalid root move restriction")
    return request


class RootProvider:
    def __init__(self, tablebase, identity, *, maximum_pieces=7, maximum_request_ms=1000):
        if type(maximum_pieces) is not int or not 3 <= maximum_pieces <= 7 or type(maximum_request_ms) is not int or not 1 <= maximum_request_ms <= 60000:
            raise ProviderError("invalid finite provider bounds")
        self.tablebase = tablebase
        self.identity = identity
        self.maximum_pieces = maximum_pieces
        self.maximum_request_ms = maximum_request_ms

    def probe(self, request):
        request = validate_request(request)
        board = chess.Board(request["fen"])
        actual_legal = {move.uci() for move in board.legal_moves}
        if set(request["legal_moves"]) != actual_legal:
            raise ProviderError("complete canonical legal set differs from provider verification")
        result = {"schema": RESULT_SCHEMA, "request_id": request["request_id"],
                  "root_fence": request["root_fence"], "provider_identity": self.identity,
                  "status": "not_applicable", "exact": False, "safe_moves": None,
                  "move": None, "raw_wdl": None, "rows": [],
                  "authority": {"raw_wdl_safety": False, "history_adjusted": False, "exact_move": False},
                  "rule_policy": {"rule50": True},
                  "history_refinement": "not_published"}
        if not board.is_valid() or board.castling_rights or len(board.piece_map()) > self.maximum_pieces or board.is_game_over(claim_draw=False):
            return result
        # Raw WDL is expressly a zero-clock abstraction. It must never be
        # relabelled as the result of this game's nonzero clock or repetition.
        raw = board.copy(stack=False)
        raw.halfmove_clock = 0
        deadline = time.monotonic() + self.maximum_request_ms / 1000
        allowed = request["searchmoves"] or request["legal_moves"]
        root_admitted = False
        try:
            root_wdl = self.tablebase.probe_wdl(raw)
            if type(root_wdl) is not int or root_wdl not in (-2, -1, 0, 1, 2):
                raise ProviderError("provider returned invalid raw WDL")
            root_admitted = True
            rows = []
            for text in allowed:
                if time.monotonic() >= deadline:
                    result["status"] = "deferred"
                    return result
                child = raw.copy(stack=False)
                child.push(chess.Move.from_uci(text))
                child.halfmove_clock = 0
                if child.is_checkmate():
                    value = 2
                elif child.is_stalemate() or child.is_insufficient_material():
                    value = 0
                else:
                    child_wdl = self.tablebase.probe_wdl(child)
                    if type(child_wdl) is not int or child_wdl not in (-2, -1, 0, 1, 2):
                        raise ProviderError("provider returned invalid child WDL")
                    value = -child_wdl
                if type(value) is not int or value not in (-2, -1, 0, 1, 2):
                    raise ProviderError("provider returned invalid child WDL")
                # Cursed wins and blessed losses are draws under the admitted
                # rule-50 policy. Preference values cannot narrow safety to a
                # different result class or acquire game-exact authority.
                result_class = 1 if value == 2 else -1 if value == -2 else 0
                rows.append({"move": text, "raw_wdl": value, "result_class": result_class})
        except KeyError:
            result["status"] = "deferred" if root_admitted else "miss"
            return result
        if time.monotonic() >= deadline:
            result["status"] = "deferred"
            return result
        best = max(row["result_class"] for row in rows)
        result.update(status="safety_only", raw_wdl=root_wdl, rows=rows,
                      safe_moves=[row["move"] for row in rows if row["result_class"] == best])
        result["authority"]["raw_wdl_safety"] = True
        return result
