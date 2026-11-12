# Model Router evidence and limitations

Current as of the September 9 codebase pivot.

- The supplied September 8 snapshot contains 23 models. The old September 6
  numbers and K2 Horizon roster entry have been replaced.
- Equal Intelligence Index scores do not establish equal performance on a
  specific workload. The brain receives scores as dated aggregate references.
- Benchmark task costs are not API billing rates. Runtime projections use
  deployment token prices; actual recorded costs use reported token usage.
- Rankings alone do not establish model access, licenses, effort/fallback parity
  or a verified endpoint. Unknown fields remain unknown.
- The supplied Qwen3.8 247B A95B name differs from the older 2.4T name. The old
  endpoint mapping is removed rather than silently treated as equivalent.
- The existing brain deployment uses xhigh while its historical catalog ID says
  max. Catalog references explicitly do not assert configuration parity.
- A bounded request digest can omit relevant context. The brain is told when it
  is truncated. Selection quality still needs representative workload evaluation.
- Consultation limits and request cost filters use estimates. They are not
  provider invoice reconciliation, monthly budgets or billing infrastructure.
- `placement_allow` restricts the executor, not where the routing brain processes
  the digest. It is not a data residency control.
- The gateway retains request text in its local ledger. Provider credentials are
  not included in request events.
- Protocol and routing tests use mocked upstream transports. No new live provider
  smoke test or proof of customer savings is claimed by this revamp.
