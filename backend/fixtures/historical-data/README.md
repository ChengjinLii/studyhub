# Historical Data Fixtures

These files are synthetic, hand-crafted compatibility cases for Step 3 and later regression tests.

Rules:

1. They are not copied from production and contain no real credentials, user data, or billing records.
2. They are JSON snapshots for mapper/query tests, not guaranteed to be directly loadable SQL fixtures.
3. Each file captures one family of edge cases that the FastAPI rewrite must tolerate without re-scanning the Java repository.

Files:

- `materials_legacy.json`: material/file/preview/view edge cases
- `commerce_legacy.json`: order/payment/settlement/payout edge cases
- `requests_legacy.json`: request/contribution/refund/arbitration edge cases
- `engagement_legacy.json`: user/profile/notification/market/report edge cases
- `legacy_tables_manifest.json`: legacy SQL-only tables still present in Flyway history
