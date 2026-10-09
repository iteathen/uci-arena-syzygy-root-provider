"""Provider-owned immutable offline root ingress; no engine state authority."""
from collections import Counter
from dataclasses import dataclass
import hashlib
import json
import re
import chess

REQUEST_SCHEMA = "uci_arena_syzygy_root_request_v2"
MAX_REQUEST_BYTES = 262144
MAX_ACTIONS = 4096
MAX_KEYS = 4097
MAX_NODES = 16384
MAX_DEPTH = 128
MAX_MILLISECONDS = 1000
MOVE = re.compile(r"[a-h][1-8][a-h][1-8][qrbn]?\Z")


class ContractError(ValueError):
    pass


def canonical_json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def effective_key(board):
    # Public FEN serialization explicitly suppresses ineffective/pinned EP.
    return " ".join(board.fen(en_passant="legal").split()[:4])


def exact(value, fields, label):
    if type(value) is not dict or set(value) != set(fields):
        raise ContractError(f"closed {label} fields required")


@dataclass(frozen=True)
class AdmittedRoot:
    request_id: str
    root_fence: str
    request_sha256: str
    origin_fen: str
    moves: tuple
    fen: str
    legal_moves: tuple
    allowed_moves: tuple
    rule50: bool
    claim_policy: str
    keys: tuple
    history_available: bool
    history_reason: str | None
    any_prior_repetition: bool
    max_nodes: int
    max_depth: int
    max_milliseconds: int


def admit_request(request, checkpoint=lambda: None):
    exact(request, ["schema", "request_id", "root_fence", "position", "legal_moves", "searchmoves", "rules", "history_mode", "limits"], "root request")
    try:
        text = canonical_json(request)
        if len(text.encode("utf-8")) > MAX_REQUEST_BYTES:
            raise ContractError("request byte capacity")
        request = json.loads(text)  # Request owns its copy before any replay.
    except (TypeError, ValueError) as error:
        raise ContractError("bounded JSON root request required") from error
    if request["schema"] != REQUEST_SCHEMA:
        raise ContractError("unsupported root request major")
    if not isinstance(request["request_id"], str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", request["request_id"]):
        raise ContractError("invalid request identity")
    if not isinstance(request["root_fence"], str) or not re.fullmatch(r"[0-9a-f]{32}", request["root_fence"]):
        raise ContractError("invalid root fence")
    position, rules, limits = request["position"], request["rules"], request["limits"]
    exact(position, ["origin_fen", "moves"], "position")
    exact(rules, ["rule50", "repetition", "claim_policy"], "draw policy")
    exact(limits, ["max_nodes", "max_depth", "max_milliseconds"], "request limits")
    if type(rules["rule50"]) is not bool or rules["repetition"] != "threefold-as-draw":
        raise ContractError("unsupported draw policy")
    if rules["claim_policy"] not in ("adjudicated-claims-as-draw", "orthodoxy-live-claims-v1") or rules["claim_policy"] == "orthodoxy-live-claims-v1" and not rules["rule50"]:
        raise ContractError("unsupported explicit claim policy")
    for key, maximum in [("max_nodes", MAX_NODES), ("max_depth", MAX_DEPTH), ("max_milliseconds", MAX_MILLISECONDS)]:
        if type(limits[key]) is not int or not 1 <= limits[key] <= maximum:
            raise ContractError("finite request limits required")
    if request["history_mode"] not in ("replay-from-origin", "unavailable"):
        raise ContractError("unsupported history mode")
    fen, moves = position["origin_fen"], position["moves"]
    if not isinstance(fen, str) or not 1 <= len(fen) <= 256 or any(not 32 <= ord(c) < 127 for c in fen):
        raise ContractError("bounded root FEN required")
    if type(moves) is not list or len(moves) > MAX_ACTIONS or any(not isinstance(m, str) or not MOVE.fullmatch(m) for m in moves):
        raise ContractError("bounded legal action replay required")
    legal = request["legal_moves"]
    if type(legal) is not list or len(legal) > 256 or any(not isinstance(m, str) or not MOVE.fullmatch(m) for m in legal) or len(set(legal)) != len(legal):
        raise ContractError("complete unique GPU legal set required")
    allowed = request["searchmoves"]
    if allowed is not None and (type(allowed) is not list or not allowed or len(allowed) > 256 or any(not isinstance(m, str) or m not in legal for m in allowed) or len(set(allowed)) != len(allowed)):
        raise ContractError("invalid allowed-root restriction")
    try:
        board = chess.Board(fen)
    except ValueError as error:
        raise ContractError("invalid origin FEN") from error
    if not board.is_valid():
        raise ContractError("invalid origin position")
    available = board.halfmove_clock == 0
    keys = [effective_key(board)]
    for encoded in moves:
        checkpoint()
        move = chess.Move.from_uci(encoded)
        if move not in board.legal_moves:
            raise ContractError("illegal root input replay")
        zeroing = board.is_zeroing(move)
        board.push(move)
        if zeroing:
            available, keys = True, []
        keys.append(effective_key(board))
    checkpoint()
    if set(legal) != {m.uci() for m in board.legal_moves}:
        raise ContractError("complete GPU legal set conflicts with independent public legality")
    if request["history_mode"] == "unavailable" and board.halfmove_clock != 0:
        available = False
    reason = None if available else "history_unavailable"
    if len(keys) > MAX_KEYS or available and len(keys) != board.halfmove_clock + 1:
        available, reason = False, "history_capacity"
    return AdmittedRoot(request["request_id"], request["root_fence"], hashlib.sha256(text.encode("utf-8")).hexdigest(),
                        fen, tuple(moves), board.fen(en_passant="fen"), tuple(legal), tuple(allowed if allowed is not None else legal),
                        rules["rule50"], rules["claim_policy"], tuple(keys), available, reason, any(n > 1 for n in Counter(keys).values()),
                        limits["max_nodes"], limits["max_depth"], limits["max_milliseconds"])
