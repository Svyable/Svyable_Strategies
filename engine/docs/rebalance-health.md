# Rebalance health status

This branch makes rebalance health explicit.

- The execution engine stops after the first unsuccessful leg by default.
- Remaining legs are marked as skipped after the first failure.
- A caller can request best-effort behavior, but the result is degraded if any leg is unsuccessful.
- The ledger no longer trusts a pre-written OK status for rebalance runs. It reviews the recorded leg results and corrects the run status to failed or degraded when needed.
- Dry runs remain informational and keep the parent run status unchanged.
