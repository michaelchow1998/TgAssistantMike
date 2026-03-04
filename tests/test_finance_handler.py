# tests/test_finance_handler.py
import pytest
from decimal import Decimal
from unittest.mock import patch

from handlers.finance import handle_finance_summary

OWNER_ID = 111
CHAT_ID = 222
USER_ID = OWNER_ID


def _income(amount, date="2026-03-10"):
    return {"fin_type": "income", "amount": Decimal(str(amount)), "date": date, "title": "薪水", "category": "salary"}

def _expense(amount, date="2026-03-10"):
    return {"fin_type": "expense", "amount": Decimal(str(amount)), "date": date, "title": "支出", "category": "food"}

def _payment(amount, status, date="2026-03-10"):
    return {"fin_type": "payment", "amount": Decimal(str(amount)), "date": date, "title": "帳單", "status": status, "due_date": date}

def _sub(amount, next_due="2026-03-15"):
    return {"name": "Netflix", "amount": Decimal(str(amount)), "next_due": next_due, "cycle": "monthly"}


class TestFinanceSummaryTwoNets:
    def test_net_excludes_pending_payment_from_settled(self):
        # income=10000, expense=1000, paid=2000, pending=500
        # settled = 10000-1000-2000 = 7000; with_pending = 7000-500 = 6500
        with patch("handlers.finance.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.finance.get_today_date", return_value=__import__("datetime").date(2026, 3, 31)), \
             patch("handlers.finance.query_gsi1", side_effect=[
                 [_income(10000)],             # income
                 [_expense(1000)],             # expense
                 [_payment(2000, "paid"), _payment(500, "pending")],  # payments
                 [],                           # subscriptions
             ]), \
             patch("handlers.finance.send_message") as mock_send:
            handle_finance_summary(USER_ID, CHAT_ID)
            msg = mock_send.call_args[0][1]
            assert "7,000" in msg    # settled net
            assert "6,500" in msg    # with-pending net
            assert "已結清淨額" in msg
            assert "含待付淨額" in msg

    def test_subscription_deducted_from_both_nets(self):
        # income=10000, no expense, no payment, sub=500
        # settled = 10000-500 = 9500; with_pending = 9500-0 = 9500
        with patch("handlers.finance.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.finance.get_today_date", return_value=__import__("datetime").date(2026, 3, 31)), \
             patch("handlers.finance.query_gsi1", side_effect=[
                 [_income(10000)],   # income
                 [],                 # expense
                 [],                 # payments
                 [_sub(500)],        # subscriptions
             ]), \
             patch("handlers.finance.send_message") as mock_send:
            handle_finance_summary(USER_ID, CHAT_ID)
            msg = mock_send.call_args[0][1]
            assert "9,500" in msg

    def test_no_subscription_no_deduction(self):
        with patch("handlers.finance.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.finance.get_today_date", return_value=__import__("datetime").date(2026, 3, 31)), \
             patch("handlers.finance.query_gsi1", side_effect=[
                 [_income(5000)],
                 [],
                 [],
                 [],  # empty subscriptions
             ]), \
             patch("handlers.finance.send_message") as mock_send:
            handle_finance_summary(USER_ID, CHAT_ID)
            msg = mock_send.call_args[0][1]
            assert "5,000" in msg
            assert "已結清淨額" in msg
