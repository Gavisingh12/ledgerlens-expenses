from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable


FX_RATES = {"INR": Decimal("1"), "USD": Decimal("83")}
HOUSEHOLD_KEYWORDS = ("rent", "electricity", "wifi", "groceries", "maid", "cleaning", "furniture")

MEMBERSHIPS = {
    "Aisha": (date(2026, 2, 1), None),
    "Rohan": (date(2026, 2, 1), None),
    "Priya": (date(2026, 2, 1), None),
    "Meera": (date(2026, 2, 1), date(2026, 3, 31)),
    "Sam": (date(2026, 4, 10), None),
    "Dev": (date(2026, 2, 8), date(2026, 3, 14)),
}

NAME_ALIASES = {
    "aisha": "Aisha",
    "rohan": "Rohan",
    "priya": "Priya",
    "priya s": "Priya",
    "meera": "Meera",
    "sam": "Sam",
    "dev": "Dev",
    "dev's friend kabir": "Kabir",
    "kabir": "Kabir",
}


@dataclass
class Anomaly:
    row_number: int
    code: str
    field: str
    message: str
    action: str
    severity: str = "warning"


@dataclass
class ImportedExpense:
    row_number: int
    date: date
    description: str
    paid_by: str
    amount_original: Decimal
    currency: str
    amount_inr: Decimal
    split_type: str
    splits: dict[str, Decimal]
    notes: str
    status: str = "included"


@dataclass
class ImportedPayment:
    row_number: int
    date: date
    payer: str
    recipient: str
    amount_inr: Decimal
    description: str
    notes: str


@dataclass
class ImportResult:
    expenses: list[ImportedExpense] = field(default_factory=list)
    payments: list[ImportedPayment] = field(default_factory=list)
    anomalies: list[Anomaly] = field(default_factory=list)


def money(value: Decimal | str | int | float) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def canonical_name(raw: str | None, row_number: int, anomalies: list[Anomaly], field: str) -> str:
    cleaned = (raw or "").strip()
    if not cleaned:
        return ""
    key = re.sub(r"\s+", " ", cleaned).lower()
    canonical = NAME_ALIASES.get(key, cleaned)
    if canonical != cleaned:
        anomalies.append(
            Anomaly(
                row_number,
                "name_normalized",
                field,
                f"'{cleaned}' was normalized to '{canonical}'.",
                "Used canonical member name.",
            )
        )
    if canonical not in MEMBERSHIPS and canonical != "Kabir":
        anomalies.append(
            Anomaly(
                row_number,
                "unknown_member",
                field,
                f"'{canonical}' is not in the known flatmate/member roster.",
                "Kept as a guest participant and surfaced in the report.",
            )
        )
    if canonical == "Kabir":
        anomalies.append(
            Anomaly(
                row_number,
                "guest_participant",
                field,
                "Kabir appears only in a trip expense.",
                "Kept as a guest participant for that row only.",
            )
        )
    return canonical


def parse_date(raw: str, row_number: int, anomalies: list[Anomaly]) -> date | None:
    text = (raw or "").strip()
    if not text:
        anomalies.append(Anomaly(row_number, "missing_date", "date", "No date supplied.", "Skipped row.", "error"))
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            parsed = datetime.strptime(text, fmt).date()
            if fmt == "%d/%m/%Y":
                day, month, _ = text.split("/")
                if int(day) <= 12 and int(month) <= 12:
                    anomalies.append(
                        Anomaly(
                            row_number,
                            "ambiguous_slash_date",
                            "date",
                            f"'{text}' could be DD/MM/YYYY or MM/DD/YYYY.",
                            "Parsed as DD/MM/YYYY because the sheet is India/INR first.",
                        )
                    )
            return parsed
        except ValueError:
            pass
    try:
        parsed = datetime.strptime(f"{text} 2026", "%b %d %Y").date()
        anomalies.append(
            Anomaly(
                row_number,
                "incomplete_date",
                "date",
                f"'{text}' has no year.",
                "Inferred 2026 from the assignment period.",
            )
        )
        return parsed
    except ValueError:
        anomalies.append(
            Anomaly(row_number, "invalid_date", "date", f"Could not parse '{text}'.", "Skipped row.", "error")
        )
        return None


def parse_amount(raw: str, row_number: int, anomalies: list[Anomaly]) -> Decimal | None:
    text = (raw or "").strip()
    if "," in text:
        anomalies.append(
            Anomaly(row_number, "formatted_amount", "amount", f"Amount '{text}' contains separators.", "Removed commas.")
        )
    cleaned = text.replace(",", "")
    try:
        amount = Decimal(cleaned)
    except Exception:
        anomalies.append(
            Anomaly(row_number, "invalid_amount", "amount", f"Could not parse amount '{text}'.", "Skipped row.", "error")
        )
        return None
    rounded = money(amount)
    if rounded != amount:
        anomalies.append(
            Anomaly(
                row_number,
                "amount_rounded",
                "amount",
                f"Amount {amount} has more than two decimals.",
                f"Rounded to {rounded}.",
            )
        )
    if rounded == 0:
        anomalies.append(
            Anomaly(row_number, "zero_amount", "amount", "Expense amount is zero.", "Skipped as a no-op.")
        )
    if rounded < 0:
        anomalies.append(
            Anomaly(row_number, "negative_amount", "amount", "Amount is negative.", "Treated as a refund/credit.")
        )
    return rounded


def parse_currency(raw: str, row_number: int, anomalies: list[Anomaly]) -> str:
    currency = (raw or "").strip().upper()
    if not currency:
        anomalies.append(
            Anomaly(row_number, "missing_currency", "currency", "Currency is blank.", "Defaulted to INR.")
        )
        return "INR"
    if currency not in FX_RATES:
        anomalies.append(
            Anomaly(row_number, "unsupported_currency", "currency", f"Currency '{currency}' is not supported.", "Skipped row.", "error")
        )
    return currency


def split_people(raw: str, row_number: int, anomalies: list[Anomaly], field: str = "split_with") -> list[str]:
    people = []
    for item in (raw or "").split(";"):
        person = canonical_name(item, row_number, anomalies, field)
        if person:
            people.append(person)
    return people


def parse_split_details(raw: str, row_number: int, anomalies: list[Anomaly]) -> dict[str, Decimal]:
    details: dict[str, Decimal] = {}
    for part in (raw or "").split(";"):
        text = part.strip()
        if not text:
            continue
        match = re.match(r"(.+?)\s+(-?\d+(?:\.\d+)?)%?$", text)
        if not match:
            anomalies.append(
                Anomaly(row_number, "invalid_split_detail", "split_details", f"Could not parse '{text}'.", "Ignored that detail.")
            )
            continue
        person = canonical_name(match.group(1), row_number, anomalies, "split_details")
        details[person] = Decimal(match.group(2))
    return details


def is_active_member(person: str, expense_date: date) -> bool:
    if person == "Kabir":
        return True
    window = MEMBERSHIPS.get(person)
    if not window:
        return False
    start, end = window
    return start <= expense_date and (end is None or expense_date <= end)


def active_household_members(expense_date: date) -> set[str]:
    return {name for name in ("Aisha", "Rohan", "Priya", "Meera", "Sam") if is_active_member(name, expense_date)}


def apply_membership_policy(
    people: list[str], expense_date: date, description: str, row_number: int, anomalies: list[Anomaly]
) -> list[str]:
    kept = []
    for person in people:
        if is_active_member(person, expense_date):
            kept.append(person)
        else:
            anomalies.append(
                Anomaly(
                    row_number,
                    "inactive_member_in_split",
                    "split_with",
                    f"{person} was not an active member on {expense_date.isoformat()}.",
                    "Removed from charge split before calculating balances.",
                )
            )
    lower = description.lower()
    if any(word in lower for word in HOUSEHOLD_KEYWORDS):
        missing = active_household_members(expense_date) - set(kept)
        if missing:
            anomalies.append(
                Anomaly(
                    row_number,
                    "active_member_missing_from_household_expense",
                    "split_with",
                    f"Active household member(s) missing: {', '.join(sorted(missing))}.",
                    "Kept the sheet's explicit participant list and surfaced for review.",
                )
            )
    return kept


def calculate_splits(
    row_number: int,
    amount_inr: Decimal,
    split_type: str,
    people: list[str],
    split_details: str,
    anomalies: list[Anomaly],
) -> dict[str, Decimal]:
    if not people:
        anomalies.append(Anomaly(row_number, "empty_split", "split_with", "No valid split participants.", "Skipped row.", "error"))
        return {}

    details = parse_split_details(split_details, row_number, anomalies)
    if split_type == "equal":
        if details:
            anomalies.append(
                Anomaly(
                    row_number,
                    "split_type_detail_conflict",
                    "split_details",
                    "split_type is equal but split_details were supplied.",
                    "Ignored details and split equally.",
                )
            )
        share = money(amount_inr / Decimal(len(people)))
        splits = {person: share for person in people}
        return _fix_rounding(splits, amount_inr)

    if split_type == "unequal":
        if not details:
            anomalies.append(Anomaly(row_number, "missing_split_details", "split_details", "Unequal split has no details.", "Skipped row.", "error"))
            return {}
        total = sum(details.values())
        if money(total) != money(amount_inr):
            anomalies.append(
                Anomaly(
                    row_number,
                    "unequal_total_mismatch",
                    "split_details",
                    f"Details total {money(total)} but amount is {amount_inr}.",
                    "Used provided split details and left residual visible in report.",
                )
            )
        return {person: money(value) for person, value in details.items() if person in people}

    if split_type == "percentage":
        if not details:
            anomalies.append(Anomaly(row_number, "missing_split_details", "split_details", "Percentage split has no details.", "Skipped row.", "error"))
            return {}
        total_percent = sum(details.values())
        if total_percent != Decimal("100"):
            anomalies.append(
                Anomaly(
                    row_number,
                    "percentage_total_not_100",
                    "split_details",
                    f"Percentages total {total_percent}%.",
                    "Normalized percentages to 100% before allocating amount.",
                )
            )
        splits = {person: money(amount_inr * value / total_percent) for person, value in details.items() if person in people}
        return _fix_rounding(splits, amount_inr)

    if split_type == "share":
        if not details:
            anomalies.append(Anomaly(row_number, "missing_split_details", "split_details", "Share split has no details.", "Skipped row.", "error"))
            return {}
        total_shares = sum(details.values())
        splits = {person: money(amount_inr * value / total_shares) for person, value in details.items() if person in people}
        return _fix_rounding(splits, amount_inr)

    anomalies.append(
        Anomaly(row_number, "unsupported_split_type", "split_type", f"Split type '{split_type}' is not supported.", "Skipped row.", "error")
    )
    return {}


def _fix_rounding(splits: dict[str, Decimal], target: Decimal) -> dict[str, Decimal]:
    if not splits:
        return splits
    diff = money(target - sum(splits.values()))
    if diff:
        first = next(iter(splits))
        splits[first] = money(splits[first] + diff)
    return splits


def looks_like_payment(description: str, split_type: str, notes: str) -> bool:
    desc = description.lower()
    note_text = notes.lower()
    return (
        not split_type.strip()
        or "paid back" in desc
        or "deposit" in desc
        or "settlement" in desc
        or "settlement" in note_text
    )


def description_key(description: str) -> str:
    words = re.findall(r"[a-z0-9]+", description.lower())
    stop = {"at", "the", "a", "an", "order"}
    return " ".join(sorted(word for word in words if word not in stop))


def import_csv_text(csv_text: str) -> ImportResult:
    result = ImportResult()
    reader = csv.DictReader(io.StringIO(csv_text))
    seen: dict[tuple, ImportedExpense] = {}

    for row_number, row in enumerate(reader, start=2):
        row_anomalies: list[Anomaly] = []
        expense_date = parse_date(row.get("date", ""), row_number, row_anomalies)
        amount_original = parse_amount(row.get("amount", ""), row_number, row_anomalies)
        currency = parse_currency(row.get("currency", ""), row_number, row_anomalies)
        if currency not in FX_RATES:
            result.anomalies.extend(row_anomalies)
            continue
        paid_by = canonical_name(row.get("paid_by"), row_number, row_anomalies, "paid_by")
        description = (row.get("description") or "").strip()
        split_type = (row.get("split_type") or "").strip().lower()
        notes = (row.get("notes") or "").strip()

        if expense_date is None or amount_original is None:
            result.anomalies.extend(row_anomalies)
            continue
        amount_inr = money(amount_original * FX_RATES[currency])
        if currency != "INR":
            row_anomalies.append(
                Anomaly(
                    row_number,
                    "foreign_currency_converted",
                    "currency",
                    f"{amount_original} {currency} is not INR.",
                    f"Converted at documented rate 1 {currency} = {FX_RATES[currency]} INR.",
                )
            )

        if looks_like_payment(description, split_type, notes):
            recipient = canonical_name((row.get("split_with") or "").split(";")[0], row_number, row_anomalies, "split_with")
            if not paid_by or not recipient:
                row_anomalies.append(
                    Anomaly(row_number, "invalid_payment", "paid_by/split_with", "Payment row lacks payer or recipient.", "Skipped row.", "error")
                )
            else:
                row_anomalies.append(
                    Anomaly(
                        row_number,
                        "settlement_detected",
                        "description",
                        "Row appears to be money paid between members, not a shared expense.",
                        "Recorded as a payment/settlement.",
                    )
                )
                result.payments.append(
                    ImportedPayment(row_number, expense_date, paid_by, recipient, amount_inr, description, notes)
                )
            result.anomalies.extend(row_anomalies)
            continue

        if not paid_by:
            row_anomalies.append(
                Anomaly(row_number, "missing_payer", "paid_by", "No payer supplied.", "Skipped row until a user supplies payer.", "error")
            )
            result.anomalies.extend(row_anomalies)
            continue
        if amount_inr == 0:
            result.anomalies.extend(row_anomalies)
            continue

        people = split_people(row.get("split_with") or "", row_number, row_anomalies)
        people = apply_membership_policy(people, expense_date, description, row_number, row_anomalies)
        splits = calculate_splits(row_number, amount_inr, split_type, people, row.get("split_details") or "", row_anomalies)
        if any(a.severity == "error" for a in row_anomalies):
            result.anomalies.extend(row_anomalies)
            continue

        expense = ImportedExpense(
            row_number,
            expense_date,
            description,
            paid_by,
            amount_original,
            currency,
            amount_inr,
            split_type,
            splits,
            notes,
        )
        dup_key = (expense_date, description_key(description), paid_by, amount_inr, tuple(sorted(splits)))
        fuzzy_key = (expense_date, description_key(description), tuple(sorted(splits)))
        if dup_key in seen:
            row_anomalies.append(
                Anomaly(row_number, "duplicate_exact", "description", "This row matches an earlier expense.", "Excluded duplicate from balances.")
            )
            expense.status = "excluded_duplicate"
        else:
            conflict = next((old for key, old in seen.items() if key[:1] == fuzzy_key[:1] and key[1] == fuzzy_key[1] and key[4] == fuzzy_key[2]), None)
            if conflict and conflict.amount_inr != amount_inr:
                row_anomalies.append(
                    Anomaly(
                        row_number,
                        "duplicate_conflict",
                        "amount",
                        f"Possible duplicate of row {conflict.row_number} with different amount.",
                        "Excluded later row pending review.",
                    )
                )
                expense.status = "needs_review"
            else:
                seen[dup_key] = expense
        result.expenses.append(expense)
        result.anomalies.extend(row_anomalies)
    return result


def balances_for(expenses: Iterable[ImportedExpense], payments: Iterable[ImportedPayment]) -> dict[str, Decimal]:
    balances: dict[str, Decimal] = {}
    for expense in expenses:
        if expense.status != "included":
            continue
        balances[expense.paid_by] = money(balances.get(expense.paid_by, Decimal("0")) + expense.amount_inr)
        for person, share in expense.splits.items():
            balances[person] = money(balances.get(person, Decimal("0")) - share)
    for payment in payments:
        balances[payment.payer] = money(balances.get(payment.payer, Decimal("0")) + payment.amount_inr)
        balances[payment.recipient] = money(balances.get(payment.recipient, Decimal("0")) - payment.amount_inr)
    return dict(sorted(balances.items()))


def settlement_plan(balances: dict[str, Decimal]) -> list[tuple[str, str, Decimal]]:
    debtors = [[name, -amount] for name, amount in balances.items() if amount < 0]
    creditors = [[name, amount] for name, amount in balances.items() if amount > 0]
    debtors.sort(key=lambda item: item[1], reverse=True)
    creditors.sort(key=lambda item: item[1], reverse=True)
    plan: list[tuple[str, str, Decimal]] = []
    i = j = 0
    while i < len(debtors) and j < len(creditors):
        amount = money(min(debtors[i][1], creditors[j][1]))
        if amount:
            plan.append((debtors[i][0], creditors[j][0], amount))
        debtors[i][1] = money(debtors[i][1] - amount)
        creditors[j][1] = money(creditors[j][1] - amount)
        if debtors[i][1] == 0:
            i += 1
        if creditors[j][1] == 0:
            j += 1
    return plan
