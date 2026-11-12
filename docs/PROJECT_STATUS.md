# Model Router status — September 9, 2026

The codebase now follows the four-part Model Router vision. Automatic live
requests consult a frontier brain; the brain and other open/closed deployments
share one execution pool. The catalog contains the exact supplied 23-model
snapshot. Jobs, compiler/governor stubs and their configuration are removed.

The gateway's real protocol path is tested using isolated upstream HTTP mocks,
including self-selection, cheaper open selection, rejected decisions, provider
failures, cost accounting and request constraints. Existing protocol, costing,
evaluation and registry tests remain part of the checks.

Unfinished external validation: newly smoke-test the configured live brain and
executors, verify deployments for the wider open/local catalog, and measure total
routing-plus-execution costs against a workload quality baseline. This status does
not claim all catalog models are connected or that customer savings are proven.

The mockup remains provisional; no final marketing site is implemented here.
