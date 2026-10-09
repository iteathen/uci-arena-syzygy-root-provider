# External root provider cold lifecycle

Owner-authorized implementation of the public process boundary: receive ingress
after bounded runtime/configuration admission, before dataset hashing. A separate
cold worker owns streamed exact file admission and public tablebase opening.
Describe distinguishes warming from ready; warming probes defer without proof.
Close cancels and joins the worker before closing any dataset owner. No change to
root proof rules, result-v2 metrics, active GPU search or historical v2-05 receipts.

1. TDD responsive warming describe/defer, cancellation, late owner cleanup,
   failed admission and incomplete drain.
2. TDD chunked hash cancellation and full pre/post file identity checks.
3. Wire literal public CLI and declare versioned cold lifecycle capability.
4. Run full source suite and literal packaged process warming/ready/close cases;
   retain exact package/source/receipt identities for independent review.

Observed RED then GREEN: 63 source tests pass on pinned CPython3.13.16/chess1.11.2.
Literal package-candidate-v2-07-warming (54 files), manifest
`a9ffc6a03a98fe5c0337510a5404734f9839958d39305ede5971dab847d39944`,
passes six existing KQ process cases and broken-output nonzero disposition.
The full1020-file selection publishes warming without dataset authority in
150.62/167.17ms, then close/EOF cancellation exits normally in9.28/9.33ms.
These timings are two lifecycle observations, not a latency population gate.
Receipts remain in the owned provider tools root; dataset-ready/full-ranking,
Vector integration, managed signing and production acceptance remain separate.

Independent review found an inherited manifest read/stamp race. Admission now
retains the pre-read regular-file stamp, checks it immediately after reading,
and keeps that same stamp through final admission and subsequent use. A real
file replacement immediately after the pinned read was observed RED (no
DatasetError), then GREEN; all64 source tests pass on the same pinned runtime.
The follow-up candidate inventory is rebuilt separately. The v2-07 native
receipts above remain historical evidence for their original source bytes;
this source repair does not relabel them or add a dataset-ready/native claim.
