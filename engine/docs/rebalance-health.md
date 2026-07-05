# Rebalance health status

Rebalance health is an explicit mainline contract between the execution engine, CLI, and ledger.

- The execution engine stops after the first unsuccessful leg by default.
- Remaining legs are marked as `skipped_after_failure` after the first failure.
- A caller can request best-effort behavior with `--continue-on-error`, but the result is `degraded` if any leg is unsuccessful.
- Dry runs are informational and keep the parent ledger run status unchanged.
- Executed rebalances return nonzero when execution is `failed`/`degraded` or reconciliation downgrades the run.
- The ledger no longer trusts a pre-written OK status for rebalance runs. It reviews recorded leg results and corrects run status to `failed` or `degraded` when needed.
- Reconciliation can only worsen run health through `Ledger.update_run_status(..., worse_only=True)`, so a later drift check cannot mask an execution failure.
