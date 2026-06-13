# AI Usage

## Tools used

- OpenAI Codex in the Codex desktop app as the primary development collaborator.

## Key prompts

- "Build and deploy a shared expenses app for this group in 2 days."
- "The importer must detect every anomaly in `expenses_export.csv`, surface it, and handle it according to a documented policy."
- "Keep the code understandable enough for a live walkthrough where any line can be explained."
- "Use the supplied CSV exactly as provided; do not edit it before import."

## Cases where AI output was wrong and how I caught it

### 1. False payment detection from the phrase "who paid"

Wrong output: the initial payment detector looked for the word `paid` anywhere in the description or notes. Row 13 says "can't remember who paid", so the importer incorrectly classified a missing-payer expense as a payment.

How I caught it: I printed anomaly codes by CSV row and saw `invalid_payment` on row 13 instead of `missing_payer`.

What changed: `looks_like_payment` now checks more specific signals such as blank split type, `paid back`, `deposit`, or `settlement`.

### 2. Test used the wrong settlement sign convention

Wrong output: the first settlement-plan test subtracted money from payers and added it to receivers, which is backwards for this app's net-balance model.

How I caught it: the test said Aisha had double her balance after applying settlements.

What changed: the test now applies payments the same way the app does: payer net increases, receiver net decreases.

### 3. Test runner assumed pytest was installed

Wrong output: the first test setup used `pytest` only.

How I caught it: local verification failed with `No module named pytest`.

What changed: tests were rewritten with standard-library `unittest`, while still remaining compatible with pytest if a host installs it.

### 4. Framework assumption

Wrong output: the early implementation plan leaned toward Flask, but this workspace did not have Flask installed and network access may be restricted.

How I caught it: `flask` was not available on PATH.

What changed: the app uses Python's standard-library WSGI server and SQLite so local verification does not depend on downloading packages.
