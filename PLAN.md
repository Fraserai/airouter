# Model Router implementation

The September 9 product reset is defined in `BRIEF.md`. The active implementation
is a single-request gateway, frontier routing engine, shared model pool, generic
provider adapters and a cost ledger.

Implemented in the pivot:

- Replace the older market roster with the supplied 23-model September 8 snapshot.
- Keep the market snapshot distinct from deployment metadata and token pricing.
- Resolve the intended brain from the top intelligence rank, using benchmark cost
  only to break a rank tie. Support an explicit configuration override.
- Enable automatic frontier consultation and include the brain in the pool.
- Show dated intelligence references to the brain without certifying effort parity.
- Fail live routing explicitly if consultation cannot produce a valid choice.
- Retain consultation costs even when no executor runs.
- Apply executor constraints to explicit selection and preview as well as routing.
- Remove autonomous job endpoints, job code and unused compiler/governor/tenant
  configuration. Preserve the previous working copy in the ignored work archive.

Verification uses the actual gateway, real protocol adapters and mocked upstream
HTTP calls. The wider catalog still needs verified provider deployments. Paired
workload evaluations must include routing overhead before savings are reported.
The website remains provisional while mockups are refined.
