# Offline root-safety diagnostic candidate

This local candidate uses the public python-chess Syzygy API as an independent,
offline root-only knowledge boundary. It does not implement the engine, neural
evaluation, GPU features, canonical game transitions, or an active-leaf callback.
The original engine knowledge-source contract remains authoritative.

`provider.py` accepts a closed bounded request with an opaque current-root fence,
FEN, complete GPU-produced legal UCI move set, and optional searchmoves restriction.
Independent public board legality must agree before probing. Raw WDL results use
an explicit zero-clock abstraction and rule-50 result classes. Cursed wins and
blessed losses remain draw-class preferences. A verified missing root returns
`miss`; missing child dependencies, cancellation/time pressure or incomplete
work cannot publish a partial safety subset. Successful raw safety returns every
allowed move preserving the best raw result class and no exact selected move.

History-adjusted full-ledger minimax, DTZ exact move selection, cancellable
production process transport, public consumer wiring, a pinned stable managed
Python runtime and signed component packaging are **not implemented or qualified**.
The local Python installation is a diagnostic dependency, not a production runtime.
No live bot or installed suite may use this prototype as an exact tablebase proof.

`qualify_kqvk.py` hashes the existing manifest and the two KQvK WDL/DTZ files before
three physical probes. Its authority covers only that closed three-piece subset.
It neither validates every six-piece resource nor claims history-adjusted exactness.
Old observations remain historical; the rule-50 observation binds the corrected
provider source. Unit tests falsify malformed ingress, incomplete legality, root
miss versus missing child dependency, malformed booleans and draw-class safety.

Dependency API: <https://python-chess.readthedocs.io/en/latest/syzygy.html>.
The dependency is not vendored here; production redistribution must retain its
published license and source obligations as part of its own provider release.
