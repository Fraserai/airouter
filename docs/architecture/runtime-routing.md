# Runtime routing

1. Validate the request and normalize its output allowance.
2. Filter the shared execution pool using verified deployment metadata, configured
   providers, supported features, context estimates and caller constraints.
3. Supply the configured frontier brain with the bounded request digest, eligible
   candidates, request-specific cost projections and dated intelligence references.
4. Reserve consultation cost when a request cost limit is supplied.
5. Validate the brain's structured choice against the exact offered candidate set.
6. Execute once through the selected model's provider adapter; the brain is a
   valid executor when it satisfies the same constraints.
7. Record decision provenance, routing charges, execution usage and total cost.

Live automatic requests require a valid brain decision. Consultation failures or
rejected choices return 503 and do not execute a fallback. Any known consultation
charge is retained; missing usage remains unknown. Development and simulation can
use explicitly identified deterministic selection.

The catalog and deployments are separate immutable registry snapshots. The
catalog ranks the supplied market data; deployment entries hold verified token
rates and adapter configuration. Updating the highest-ranked model changes the
intended brain on restart. An unverified replacement is not silently enabled.
