# Security Policy

## Broker credentials

Never commit `.env`, OAuth refresh tokens, client secrets, quote tokens, broker account numbers, ledger databases, data caches, or generated audit/output directories. The repository `.gitignore` is configured for the common local paths, but contributors are responsible for checking diffs before publishing.

Use `engine/.env.example` as the public template. Real values belong only in a local `.env` or a secret manager.

## Tastytrade safety gates

The SDK adapter is intentionally conservative:

- Sandbox/test mode is the default.
- Production order submission requires `SVYABLE_ENABLE_LIVE=true` and account-number confirmation.
- Production order cancellation requires account-number confirmation.
- Generic `submit_order()` is disabled for production; production callers must use `submit_intent(..., confirmation=...)`.
- Audit logs redact secret-like keys and mask account identifiers.

## Reporting vulnerabilities

Open a private security advisory or contact the repository owner directly before disclosing broker, credential, or order-submission issues publicly. Include the affected command/path, expected behavior, observed behavior, and whether live credentials or production accounts were involved.

## Operational checklist before open-source release

- Rotate any credentials that may have existed in local branches, Actions logs, screenshots, notebooks, or generated files.
- Confirm no generated `engine/outputs*`, `engine/data-cache*`, `quote_token.json`, ledger databases, or `.env` files are committed.
- Run `engine-ci` before tagging a release, including the consolidated SDK/broker/rebalancer/ledger safety suite:
  `python -m pytest tests/test_tastytrade_sdk_preflight.py tests/test_broker_safety.py tests/test_rebalancer_execution_policy.py tests/test_ledger_execution_status.py tests/test_tastytrade_rest_boundary.py`.
