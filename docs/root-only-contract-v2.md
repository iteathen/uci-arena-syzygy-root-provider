# Offline root knowledge contract v2

**Status:** Source candidate; independent external provider. No signed installation or Vector consumer acceptance is implied.

This provider owns offline root Syzygy access through pinned public chess APIs. The original `uci_knowledge_sources_v1.yaml` result, history, default and degraded meanings remain authority. The external profile substitutes the historical Fathom implementation at this root-only boundary; it grants no internal GPU callback, engine search, NN or canonical state mutation authority.

## Request

`uci_arena_syzygy_root_request_v2` is closed: `schema`, `request_id`, `root_fence`, `position`, `legal_moves`, `searchmoves`, `rules`, `history_mode`, `limits`.

- `request_id` is a unique bounded public identifier; `root_fence` is an opaque 128-bit lowercase hex fence owned by the consumer's actual admitted GPU root.
- `position` contains exactly `origin_fen` and at most 4096 legal UCI `moves`. It is the consumer's immutable admitted root input, not a provider-derived replacement position.
- `legal_moves` is the complete GPU-produced legal UCI set, at most 256 unique moves. Independent public board legality must agree. `searchmoves` is null or a nonempty subset. Root tie order follows the supplied legal order.
- `rules` contains `rule50` boolean, `repetition: "threefold-as-draw"`, and mandatory `claim_policy`. `adjudicated-claims-as-draw` explicitly adjudicates threefold/100-halfmove draws under the historical tablebase policy; both rule50 values are admitted. `orthodoxy-live-claims-v1` admits rule50 true only, represents a current or intended-move threefold/50-move claim as an optional draw action, and makes fivefold/150-halfmove draws automatic. A winning side may decline a claim. These profiles are never implicitly substituted. Missing policy and unsupported combinations fail closed.

An optional claim is a virtual draw action inside the external proof. If claiming is better than every proved allowed legal move, refinement returns `claim_action_required` with no exact move and retains completed raw safety. The canonical engine owns claim/terminal publication. An externally proved legal move is exact only after every required allowed row resolves under the selected policy.
- `history_mode` is `replay-from-origin` or `unavailable`. The provider's normalized request owns the effective-FEN4 key sequence, count, availability and verified any-prior-repetition aggregate. Keys contain pieces, side, castling and only legally effective en passant. A zero-clock origin or later zeroing move establishes the full reversible window. A nonzero origin with no later zeroing cannot manufacture a missing prefix. Count must equal current halfmove clock plus one for complete history. At zero clock the one-key window is history-safe.
- `limits` contains `max_nodes` (1..16384), `max_depth` (1..128), and `max_milliseconds` (1..1000). Values may reduce advertised bounds, never increase them.

No request contains a filesystem path, executable, code, callback or private engine identifier. Malformed ingress and a conflicting legal set fail before table access. Semantically unavailable or over-capacity history defers refinement while preserving completed raw safety.

## Results and authority

The provider emits bounded `uci_arena_syzygy_root_result_v2` events with an increasing per-request sequence. Every event binds request id, opaque root fence, canonical request digest, provider generation and admitted provider/resource identity.

The raw event independently reports `miss`, `not_applicable`, `deferred`, or `safety_only`. Raw WDL uses an explicit zero-clock abstraction. With rule50 enabled, cursed wins and blessed losses belong to the draw class; with it disabled their signs map to win/loss. Only a complete probe of every allowed child publishes the full best-class subset. Missing child dependencies, cancellation or deadline never publish partial safety. Raw safety is never exact move or game-result proof.

Refinement uses bounded tablebase-only minimax over the complete relevant ledger. Checkmate/stalemate/material terminals precede repetition and rule50 draws. A zeroing child transfers game-result authority to raw zero-clock WDL. Required nonzero DTZ availability is checked; its rounded numeric estimate is not used as an exact distance or a near-rule50 clock heuristic. The first profile exhaustively proves outcome and distance to the first zeroing/mate boundary, without an augmented-history cache, static evaluation or neural score. Every allowed root row required for ranking must be proved; otherwise the complete refinement is deferred. Winning ties minimize this proved distance, losing ties maximize it, and draw ties use consumer move order. The metric is explicitly `reversible-minimax-plies-to-zeroing-or-mate`, not a claim that rounded stored DTZ is exact DTM.

Direct selection stays inside the completed raw-safe subset. A contradiction between independently completed proof and raw class safety fails closed. Completed safety is retained through missing-history/DTZ, node/depth/time capacity and cancellation. A deferred or cancelled event cannot broaden it or acquire exact authority. At a terminal root the canonical engine retains terminal publication ownership.

## Transport and lifecycle

Version 2.1.0 adds `uci_arena_root_provider_cold_lifecycle_v1`. After bounded
package/runtime/configuration admission, ingress runs while a separate cold
worker hashes the complete selected dataset. `describe.status="warming"`
contains admitted runtime/package and canonical configuration identity only;
it has no dataset identity and `readiness.dataset="not-admitted"`. It is not a
successful tablebase admission. Warming probes receive a transport-v1 deferred
frame with `reason="provider_warming"`, request id, root fence and provider
generation, without miss, safety or exact authority. No ticket is created.

Consumers poll the existing describe operation for readiness; no unsolicited
ready frame or private constructor API is introduced. The same generation
becomes ready only after exact full hashes, pre/post file stamps, public file
opening and repeated runtime/configuration identity checks complete. The ready
description carries the actual admitted file set and `readiness.dataset="admitted"`.
One process may remain alive across games; ordinary game boundaries do not
reload its immutable dataset or change its generation.

Close and EOF cancel hashing between 65536-byte reads and between public file
admissions, join the cold worker, then drain request work before dataset close.
Close reports closed/drained only after those owners finish. A stalled file read
or public call can produce `draining`; failed admission/cleanup produces
`quarantined` and nonzero process disposition. No background owner is declared
closed merely because no ready dataset was published. Historical 2.0.0/v2-05
bytes and observations remain unchanged; this capability does not change the
exhaustive result-v2 proof/ranking profile.

The closed transport envelopes are `{"operation":"describe"}`, `{"operation":"probe","request":<v2 request>}`, `{"operation":"cancel","request_id":<id>,"root_fence":<fence>}`, and `{"operation":"close"}`. Probe events are direct result-v2 objects without an operation wrapper. Cancel has no acknowledgment; consumer abandonment is immediate and in-flight output must be discarded by binding. Close reports separate `drained` and `failed` facts with `closed`, `draining` or `quarantined` disposition; zero exit and EOF are checked separately. Ticket pressure and transport errors supply no proof authority.

The canonical request digest hashes the request object only, using UTF-8, recursively sorted object keys, comma/colon separators without spaces, no ASCII escaping and no nonfinite numbers. The transport wrapper and trailing LF are excluded. `provider_identity.configuration_sha256` hashes the same canonical JSON convention for the admitted cold configuration; this is semantic configuration identity, distinct from the configuration file's exact byte digest.

Literal launch arguments resolve package-relative script/inventory paths against the declared package working directory. The registered cold configuration is an absolute locator. The producer normalizes that inventory locator before its strict regular-file/package-root checks; consumers must not invent a private absolute-argument substitution.

One offline framed JSON process owns one serialized tablebase worker and two bounded request tickets. Describe, probe, cancel and close are closed public operations. Cancellation is observed between replay/probe/minimax steps; a synchronous library/file probe may still drain. Consumer abandonment never joins that drain or delays its move emission. A new fenced request may occupy the second ticket. Late completion is discarded by matching request, root, generation and input digest; substitution/reconfiguration starts a new provider generation. Close stops ingress, cancels work and drains before tablebase close. A bounded external process termination is the final failure containment for a stalled library call.

The provider loads only an explicit manifest-admitted immutable local dataset. Request-time discovery, substitute directories and network access are absent. Startup binds source inventory, exact runtime/dependency archives, manifest bytes, admitted file digests, cardinality and rule/worker profile. An unavailable configuration remains unavailable and may be disabled for normal GPU search through the declared degraded mode; it is never successful validation.

## Runtime and distribution

The Windows source candidate pins official CPython 3.13.16 embeddable x64 archive SHA256 `97dae5274cc54867065e8d5a3226e48c35017ed332a0fdb0e27d5b5821961297` and public chess 1.11.2 source archive SHA256 `a8b43e5678fdb3000695bdaa573117ad683761e5ca38e591c4826eba6d25bb39`. CPython's license and the complete GPL-3.0-or-later chess source/license must accompany provider distribution. No dependency source build or new native source is required. The embedded runtime uses a closed `_pth`, isolated launch and inventoried provider/dependency paths. Existing beta-Python observations remain historical diagnostics.

Primary dependency facts: [Syzygy public API](https://python-chess.readthedocs.io/en/v1.11.2/syzygy.html), [chess 1.11.2 distribution](https://pypi.org/project/chess/1.11.2/), [CPython 3.13.16 archive](https://www.python.org/downloads/release/python-31316/). Provider schema documents are provider-owned actual bytes; their digests do not impersonate engine, Installer or dependency-issued schema provenance.
