# Offline Root Provider v2 Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task; no additional delegation.

**Goal:** Deliver a reviewable bounded offline root-only provider with separate raw safety and genuinely proved full-history refinement.

**Architecture:** Preserve `provider.py` and its six legacy tests. New closed ingress normalizes an immutable independently verified root/history request; a separate tablebase-only proof owner and serialized cancellable transport publish fenced results. Dataset/runtime/package admission stays cold and consumer integration remains a public external process port.

**Tech Stack:** CPython 3.13.16, chess 1.11.2 public APIs, Python stdlib, JavaScript packaging/consumer transport where needed.

**Spec:** `docs/root-only-contract-v2.md`; original `C:/chess_engine/stand_alone_uci_engine/specs/uci_knowledge_sources_v1.yaml`1.4; Vector CONNECTOR_MAP connector8/native boundary.

## Constraints

- Root only; no active GPU leaf/NN callback, engine CPU search, C++/WASM or private SDK APIs.
- No tablebase download, user-data cleanup, signing, installation or new repository publication.
- Exact declared local resources and managed runtime/dependency bytes; old receipts immutable.
- Peer adapter remediation has priority over this work.

## Tasks

- [ ] `root_contract.py` + `test_root_contract.py`: RED/GREEN closed bounded ingress, replay legality, effective EP identity, zeroing history boundary, unavailable prefix and request digest/fence.
- [ ] `root_provider.py` + `test_root_provider.py`: RED/GREEN complete raw safety under both rule policies; missing root/child distinction; full-ledger terminal ordering/zeroing/minimax distance; repeat/deeper repeat, cancellation/time/node/depth/missing-DTZ deferral with retained safety and no partial exactness. Compare bounded cases to an independent simple exhaustive oracle.
- [ ] `dataset.py` + `test_dataset.py`: regular/reparse-safe manifest/file/source/runtime identity admission; explicit closed subset; public tablebase ownership/close; corruption and substitution falsifiers.
- [ ] `service.py` + `test_service.py`: bounded framed transport, two tickets/one worker, generation/request/root/digest matching, cancel/replacement and draining close; no request path/code injection.
- [ ] Source/package records and exact stable-runtime tests. Physical probes use only manifest-admitted existing E dataset members; distinguish closed subset evidence from full live cardinality and consumer acceptance. Give model owner the exact public wire/API shape.

## Review focus

Rounded DTZ must not fabricate clock exactness; full relevant history cannot be replaced by a repeat flag; terminal precedence must survive rule50 boundary; deferred/late results cannot broaden safety; package/data identities must bind actual bytes and retain license/source.

## Candidate freeze evidence

The isolated CPython 3.13.16/chess 1.11.2 run passes 47 source tests, including the
unchanged six legacy cases. The public packaged-process gate passes six existing
KQvK cases. Those exact refinements cover single allowed moves and independently
known mate/repetition outcomes, not broad DTZ-ranking or full live-cardinality
qualification. Public-chess stack APIs independently check current/intended claim
availability and automatic-draw predicates. A comprehensive independent slow
minimax oracle remains a release qualification gap.

The v2-03 unsigned package has 53 inventoried files; CPython's license and the
complete chess source archive are included. Frozen package/receipt identities
are retained in the external owned tools directory, rather than rewriting old
receipts. Vector consumer integration, source-independent review, signed provider
release and broader tablebase qualification remain pending. No live engine uses
this candidate as qualified exact root authority.
