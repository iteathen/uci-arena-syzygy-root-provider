# Offline root-only Syzygy provider candidate

The v2 source implements bounded external root knowledge through public chess
APIs: immutable replay/history ingress, complete raw WDL safety, optional
full-ledger minimax refinement, explicit draw-claim policy, exact dataset/package
inventory, one worker/two tickets, cancellable JSON-lines transport and isolated
managed-runtime packaging. It never implements canonical engine state, GPU
search, neural evaluation or an active-leaf callback.

The public locator is [contracts/offline-root-knowledge-v2.json](contracts/offline-root-knowledge-v2.json).
[Contract details](docs/root-only-contract-v2.md) bind the original knowledge-source
specification. The runtime pins official CPython 3.13.16 embeddable x64 and chess
1.11.2 source bytes. package_provider.py assembles a fresh unsigned candidate,
retains complete chess source/license and CPython license, and inventories every
member. A consumer must verify its admitted inventory before launching code.

The implementation separates adjudicated claims from live optional claims;
threefold/50 claims never silently become GPU terminal/no-action authority.
Proof capacity, missing history/DTZ, cancellation and pressure produce deferred
refinement while retaining completed safety. A virtual claim cannot become an
exact legal move. Rounded DTZ is recorded without pretending to be exact DTM.

Source tests run with the pinned isolated runtime (-I -B) and explicitly admit
this source directory for qualification. qualify_v2.py drives the actual packaged
public process over the existing manifest-selected KQvK WDL/DTZ pair. Its six cases
cover raw safety/capacity, missing prefix, adjudicated third occurrence, live third
occurrence without forced adjudication, and mate boundaries under both policies.
This proves a closed three-piece subset and narrow single-allowed-move refinements.
Full six-piece resources, broad DTZ ranking, live timing, signed installation and
Vector consumer acceptance remain unqualified.

Historical provider.py, its six tests and qualify_kqvk.py remain unchanged.
Their old beta-runtime/raw-safety receipts are historical diagnostics and are not
repurposed for v2 source, managed runtime or history/claim qualification.
