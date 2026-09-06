# FINDINGS.md

Running log of ambiguities, judgement calls, and places the brief and reality
disagree. Every provisional number in this project traces back to an entry here.

---

## F001 — PLAN.md reconciled against BRIEF v2 (2026-09-07)

BRIEF v2 adopted all eight disagreements raised in `PLAN.md §7`. Status of each:

| # | v1 position | v2 outcome |
|---|---|---|
| 1 | Tier 2 budgeted in spend, not request count | **Adopted** (§2) |
| 2 | Quality criterion must be a non-inferiority test | **Adopted** (§10.1) |
| 3 | Overhead denominator should be counterfactual spend | **Adopted** (§10.4) |
| 4 | Counterfactual needs shadow calibration + CI | **Adopted** (§6) |
| 5 | Cheapest-that-clears-*with-margin* | **Adopted** (§5.5 + our `selection.capability_margin_*`) |
| 6 | Composite index must not survive as a routing input | **Partially adopted** (§3 rule 3 restates the principle; no explicit sunset date — we enforce it ourselves, see F004) |
| 7 | Swap drill should also run against the real registry | **Not adopted** (§9 M6 remains CI + mock only). We will do the staging run anyway; it costs nothing and the claim is otherwise untested. |
| 8 | Synthetic workload numbers must be labelled | **Adopted and strengthened** (§10 — labelling must be in the eval *output*, not a README) |

New obligations in v2 that were not in v1 and are now on the build list:

- Digest bound enforced **structurally, in the type system** (§2). Not a convention, not a check — the Tier 2 call must be impossible to make with a raw prompt.
- **Both** local cost numbers live in the registry (§3).
- Judge requires API access to a **second frontier lab** (§5). Budget line, not an afterthought.
- Absolute routing cost per request reported alongside the ratio (§10.4).
- Judge–human agreement is acceptance criterion 8 and a **promotion gate** (§10.7).
- Postgres/Redis swap moves into M3 explicitly (§9).

No conflicts found between `PLAN.md` and BRIEF v2. `PLAN.md` stands as written
except for the overhead-budget table in its §2, whose denominator changes from
total spend to counterfactual spend, and which gains a fourth line (F002).

---

## F002 — Shadow calibration is a fourth cost line, and it is not "overhead"

BRIEF v2 §6 requires sampled shadow execution on the frontier model to calibrate
the counterfactual, and says to treat it as a line item. It is not in the §2
overhead decomposition, and it should not simply be added there — it is
*measurement* cost, not *routing* cost, and folding it into routing overhead
would make the router look worse the more honestly it measures itself.

Decision: the ledger carries five cost lines, and two different totals.

```
execution_cost           work the customer asked for
routing_cost             Tier 2 consults
verification_cost        gates + judge
compilation_cost         policy compiler, amortised
shadow_calibration_cost  measuring the counterfactual

routing_overhead     = routing + verification + compilation      -> §10.4 metric
total_programme_cost = all five                                  -> savings arithmetic
savings              = counterfactual - total_programme_cost
```

Savings is computed against `total_programme_cost`, not `execution_cost`. If we
netted shadow-calibration spend out of the savings figure, the number would
overstate by exactly the amount we spent proving it. Both totals are exposed on
`/v1/routing/stats`.

**Raised for a decision:** shadow sampling rate is a direct trade of savings
accuracy against savings size. Default set to 1% with the CI reported; if the CI
is too wide to be credible to a buyer, the rate goes up and the headline number
goes down. That is a commercial call, not a technical one.

---

## F003 — Blinding does not fix self-preference when the judge and the executor share a lab

BRIEF v2 §5 requires the judge to come from a different lab than the *policy
compiler*, blinded to which model produced the output. That closes the loop where
the policy author grades its own policy. It does not close a second loop:

> If the judge is from lab B, and the output under test was produced by lab B's
> model, blinding does not help — the judge cannot be told which model wrote the
> output, but it can still recognise its own family's style and score it higher.

Documented self-preference in model-as-judge setups survives blinding, because
the preference is over the output's characteristics, not over a label.

Decision: the judge must differ from **both** the policy compiler **and** the
model under test. Implementation: a judge-selection rule that excludes the
executor's lab; where the pool leaves no valid third-party judge for a given
comparison, that comparison is not judged by a model at all — it goes to the
human gold set queue and is reported as `unjudgeable_by_model`, never silently
scored. Expect this to bite on frontier-vs-frontier comparisons, where the pool
of eligible judges is smallest and the stakes are highest.

Consequence: this needs a **third** lab's API access, not a second, for full
coverage. Flagging the cost now rather than discovering it at M3.

---

## F004 — The composite index must not become a routing input

The seed registry supplies only `scores.composite`. It is the only score we have
on day one, and it is the single easiest thing to route on. BRIEF §3 rule 3 says
not to; nothing enforces it.

Decision: `quality_floors.yaml` expresses floors as sub-eval requirements only.
The selector reads the capability vector; the composite is available for display
and ranking in `/v1/models` but the selection path will raise if a floor names
`composite`. Enforced by test, not by discipline. Until sub-scores are sourced,
models with no sub-scores are ineligible for capability-specific task classes and
eligible only for classes whose floor is empty — which is the honest behaviour and
will make the day-one candidate pool look embarrassingly small. That is correct.

---

## F005 — Placement is a property of a deployment, not of a model

BRIEF §3 says every registry entry carries a placement. But the same open-weight
model can legitimately be run on local hardware *and* bought from a hosted
provider, at very different costs, latencies and residency guarantees.

Decision: registry entries are keyed `<model>@<deployment>` and the same model may
appear more than once. `models.seed.yaml` seeds one entry per row of the §3 table
with our best-guess placement, all `verified: false`. Placement guesses are
unverified data like everything else in that table.

---

## F006 — Day-one candidate pool is empty, by design

`verified: false` and `pricing: null` on all 22 seed entries means **no model is
selectable** until verification runs. `scripts/verify_registry.py` fails loudly.
This is the brief's requirement (§3 rule 2) working as intended, not a bug: a
router that silently misclassifies a closed model as open is a compliance
incident. M0/M1 therefore run against a deterministic stub provider so the path is
provable end to end without inventing a single price.
