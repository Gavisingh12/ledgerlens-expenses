from decimal import Decimal
from pathlib import Path
import unittest

from app.import_engine import import_csv_text, balances_for, settlement_plan


CSV_TEXT = Path("data/expenses_export.csv").read_text(encoding="utf-8")


class ImportEngineTest(unittest.TestCase):
    def test_import_detects_required_anomaly_categories(self):
        result = import_csv_text(CSV_TEXT)
        codes = {anomaly.code for anomaly in result.anomalies}

        expected = {
            "duplicate_exact",
            "duplicate_conflict",
            "foreign_currency_converted",
            "negative_amount",
            "missing_payer",
            "settlement_detected",
            "missing_currency",
            "zero_amount",
            "inactive_member_in_split",
            "percentage_total_not_100",
            "guest_participant",
            "split_type_detail_conflict",
        }
        self.assertTrue(expected.issubset(codes))

    def test_settlements_are_not_loaded_as_expenses(self):
        result = import_csv_text(CSV_TEXT)

        descriptions = {payment.description for payment in result.payments}
        self.assertIn("Rohan paid Aisha back", descriptions)
        self.assertIn("Sam deposit share", descriptions)
        self.assertTrue(all(expense.description != "Rohan paid Aisha back" for expense in result.expenses))

    def test_missing_payer_is_skipped_not_reclassified_as_payment(self):
        result = import_csv_text(CSV_TEXT)

        codes_by_row = {(anomaly.row_number, anomaly.code) for anomaly in result.anomalies}
        self.assertIn((13, "missing_payer"), codes_by_row)
        self.assertTrue(all(payment.row_number != 13 for payment in result.payments))

    def test_excluded_duplicates_do_not_affect_balance_math(self):
        result = import_csv_text(CSV_TEXT)
        balances = balances_for(result.expenses, result.payments)
        total = sum(balances.values(), Decimal("0"))

        self.assertEqual(total, Decimal("0.00"))
        self.assertTrue(any(expense.status == "excluded_duplicate" for expense in result.expenses))
        self.assertTrue(any(expense.status == "needs_review" for expense in result.expenses))

    def test_settlement_plan_balances_all_people(self):
        result = import_csv_text(CSV_TEXT)
        balances = balances_for(result.expenses, result.payments)
        plan = settlement_plan(balances)

        paid = {}
        for payer, receiver, amount in plan:
            paid[payer] = paid.get(payer, Decimal("0")) + amount
            paid[receiver] = paid.get(receiver, Decimal("0")) - amount

        for name, balance in balances.items():
            self.assertEqual(balance + paid.get(name, Decimal("0")), Decimal("0.00"), name)


if __name__ == "__main__":
    unittest.main()
