# Decision Log

## Use SQLite and standard-library Python

Options considered:

- Flask or Django with an ORM.
- Node/Express with a SQL adapter.
- Python standard library WSGI plus SQLite.

Decision: use Python standard library WSGI plus SQLite.

Why: the assignment emphasizes understanding and traceability. A small dependency-light app makes the importer, schema, and balance math easier to explain live. SQLite satisfies the relational database requirement and deploys easily for this project size.

## Keep payments separate from expenses

Options considered:

- Treat settlements as negative expenses.
- Store settlements in the same table with a special split type.
- Store payments in a dedicated table.

Decision: store payments in `payments`.

Why: settlements change who owes whom but are not shared costs. Keeping them separate makes balance math and audit traces clearer.

## Convert USD at a fixed documented rate

Options considered:

- Fetch live exchange rates.
- Ask the user for a rate during import.
- Use a fixed documented rate.

Decision: use 1 USD = 83 INR.

Why: live rates would make historical imports non-reproducible. A fixed rate makes the report repeatable and easy to challenge or change during the live session.

## Duplicate policy

Options considered:

- Delete duplicates automatically.
- Keep all duplicate-looking rows.
- Exclude exact duplicates and hold conflicting duplicates for review.

Decision: exact duplicates are excluded from balances; conflicting duplicates become `needs_review`.

Why: Meera explicitly wants approval for deletes or changes. The app records the row, status, anomaly, and reviewer action instead of mutating the CSV silently.

## Membership policy

Options considered:

- Charge everyone listed in the CSV.
- Charge everyone active in the group on that date.
- Remove inactive members but keep explicit omissions.

Decision: remove inactive members from splits, keep explicit omissions, and surface missing active members for household-style expenses.

Why: Sam should not owe March expenses and Meera should not owe April expenses. At the same time, rows like movie snacks may intentionally exclude someone, so omissions are reported instead of overwritten.

## Percentage totals not equal to 100

Options considered:

- Skip the row.
- Use the percentages literally and leave residual imbalance.
- Normalize percentages to 100%.

Decision: normalize percentages and report the anomaly.

Why: the row still contains useful intent: relative weights. Normalization keeps the expense balanced while making the correction visible.

## Rounding

Options considered:

- Store all values as floats.
- Store integer paise.
- Store Decimal strings rounded to two decimals.

Decision: use `Decimal` and store string values rounded to two decimals.

Why: shared-expense math should not depend on binary floating point. String storage keeps SQLite simple while preserving exact decimal values in the app layer.

## Import report as database-backed artifact

Options considered:

- Print a one-time text report.
- Store anomalies only in logs.
- Store anomalies relationally and offer a JSON download.

Decision: persist every anomaly in `import_anomalies` and expose an HTML/JSON report.

Why: the required deliverable is produced by the app, and evaluators can inspect both the UI and the database state.
