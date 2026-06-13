# Scope, Anomalies, and Schema

## Import policy summary

The importer never silently guesses. Each data problem becomes an `import_anomalies` row with a code, field, message, severity, and action. Rows that cannot be safely imported are skipped. Rows that are probably duplicates are excluded from balances unless a reviewer includes them later.

## Anomalies found in `expenses_export.csv`

| CSV row | Problem | Code | Handling policy |
| ---: | --- | --- | --- |
| 6 | Exact duplicate of Marina Bites dinner | `duplicate_exact` | Excluded later duplicate from balances. |
| 7 | Amount includes comma formatting | `formatted_amount` | Removed comma and parsed amount. |
| 9 | `priya` uses lowercase | `name_normalized` | Canonicalized to `Priya`. |
| 10 | INR amount has three decimals | `amount_rounded` | Rounded to 2 decimals using half-up rounding. |
| 11 | `Priya S` alias | `name_normalized` | Canonicalized to `Priya`. |
| 13 | Missing payer | `missing_payer` | Skipped row until a payer is supplied. |
| 14 | Settlement logged in the expense sheet | `settlement_detected` | Recorded as payment from Rohan to Aisha. |
| 15, 32 | Percentages total 110%, not 100% | `percentage_total_not_100` | Normalized percentages before allocating the amount. |
| 16-26, 34 | Slash dates that may be ambiguous | `ambiguous_slash_date` | Parsed as DD/MM/YYYY because the flat is India/INR first. |
| 20, 21, 23, 26 | USD expenses/refund | `foreign_currency_converted` | Converted at fixed documented rate: 1 USD = 83 INR. |
| 22, 34 | Household-style expense excludes active member(s) | `active_member_missing_from_household_expense` | Kept explicit sheet participants and surfaced for review. |
| 23 | Kabir appears but is not a regular flatmate | `guest_participant` | Kept Kabir as a guest participant for that row. |
| 25 | Thalassa dinner appears twice with different amounts/payers | `duplicate_conflict` | Excluded later row pending review. |
| 26 | Negative USD amount | `negative_amount` | Treated as a refund/credit. |
| 27 | `Mar 14` has no year and payer has trailing/lowercase text | `incomplete_date`, `name_normalized` | Inferred 2026 and canonicalized `rohan ` to `Rohan`. |
| 28 | Missing currency | `missing_currency` | Defaulted to INR and surfaced. |
| 31 | Zero amount | `zero_amount` | Skipped as a no-op. |
| 36 | Meera included after move-out | `inactive_member_in_split` | Removed Meera from the charge split. |
| 38 | Sam deposit is money paid to Aisha, not a shared expense | `settlement_detected` | Recorded as payment from Sam to Aisha. |
| 42 | `split_type=equal` but share details supplied | `split_type_detail_conflict` | Used equal split and ignored conflicting details. |

The app may create multiple anomaly rows for one CSV row when there are multiple problems.

## Database schema

Relational database: SQLite.

### `users`

- `id` primary key
- `name` unique
- `password`

### `groups`

- `id` primary key
- `name` unique

### `members`

- `id` primary key
- `name` unique

### `group_memberships`

- `id` primary key
- `group_id` foreign key to `groups`
- `member_id` foreign key to `members`
- `joined_on`
- `left_on`

### `import_runs`

- `id` primary key
- `filename`
- `imported_by` foreign key to `users`
- `created_at`

### `expenses`

- `id` primary key
- `group_id` foreign key to `groups`
- `import_run_id` foreign key to `import_runs`
- `source_row`
- `expense_date`
- `description`
- `paid_by`
- `amount_original`
- `currency`
- `amount_inr`
- `split_type`
- `notes`
- `status`: `included`, `excluded_duplicate`, or `needs_review`

### `expense_splits`

- `id` primary key
- `expense_id` foreign key to `expenses`
- `member_name`
- `amount_inr`

### `payments`

- `id` primary key
- `group_id` foreign key to `groups`
- `import_run_id` foreign key to `import_runs`
- `source_row`
- `payment_date`
- `payer`
- `recipient`
- `amount_inr`
- `description`
- `notes`

### `import_anomalies`

- `id` primary key
- `import_run_id` foreign key to `import_runs`
- `source_row`
- `code`
- `field`
- `severity`
- `message`
- `action`
