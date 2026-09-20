from decimal import Decimal

import pytest

from controller.banking_ledger_controller import (
	balance,
	create_account,
	credit,
	debit,
	list_accounts,
	list_transactions,
	parse_amount,
)
from model.banking_ledger_model import BankingLedger


def test_create_account_and_balance_starts_at_zero() -> None:
	ledger = BankingLedger()
	account = create_account(ledger, "CHK-1")

	assert account.id == "CHK-1"
	assert balance(ledger, "CHK-1") == Decimal("0.00")


def test_credit_records_transaction_and_updates_balance() -> None:
	ledger = BankingLedger()
	create_account(ledger, "CHK-1")

	transaction = credit(ledger, "CHK-1", "25.50")

	assert transaction.account == "CHK-1"
	assert transaction.type == "credit"
	assert transaction.amount == Decimal("25.50")
	assert transaction.running_balance == Decimal("25.50")
	assert transaction.id
	assert transaction.timestamp.tzinfo is not None
	assert balance(ledger, "CHK-1") == Decimal("25.50")


def test_debit_reduces_balance_and_rejects_overdraft_by_default() -> None:
	ledger = BankingLedger()
	create_account(ledger, "CHK-1")
	credit(ledger, "CHK-1", "10.00")

	transaction = debit(ledger, "CHK-1", "4.25")

	assert transaction.type == "debit"
	assert transaction.running_balance == Decimal("5.75")
	assert balance(ledger, "CHK-1") == Decimal("5.75")

	with pytest.raises(ValueError, match="Insufficient funds"):
		debit(ledger, "CHK-1", "6.00")


def test_debit_can_allow_overdraft_when_requested() -> None:
	ledger = BankingLedger()
	create_account(ledger, "CHK-1")
	credit(ledger, "CHK-1", "10.00")

	transaction = ledger.debit("CHK-1", Decimal("15.00"), allow_overdraft=True)

	assert transaction.running_balance == Decimal("-5.00")
	assert balance(ledger, "CHK-1") == Decimal("-5.00")


def test_parse_amount_rejects_invalid_text() -> None:
	with pytest.raises(ValueError, match="Invalid amount: abc"):
		parse_amount("abc")


def test_create_account_rejects_duplicate_and_blank_id() -> None:
	ledger = BankingLedger()
	create_account(ledger, "CHK-1")

	with pytest.raises(ValueError, match="Account already exists: CHK-1"):
		create_account(ledger, "CHK-1")
	with pytest.raises(ValueError, match="Account id is required"):
		create_account(ledger, "   ")


def test_operations_on_unknown_account_raise_value_error() -> None:
	ledger = BankingLedger()

	with pytest.raises(ValueError, match="Unknown account: CHK-1"):
		balance(ledger, "CHK-1")
	with pytest.raises(ValueError, match="Unknown account: CHK-1"):
		credit(ledger, "CHK-1", "10.00")
	with pytest.raises(ValueError, match="Unknown account: CHK-1"):
		debit(ledger, "CHK-1", "10.00")


def test_credit_and_debit_reject_non_positive_amounts() -> None:
	ledger = BankingLedger()
	create_account(ledger, "CHK-1")

	with pytest.raises(ValueError, match="Amount must be positive"):
		credit(ledger, "CHK-1", "0")
	with pytest.raises(ValueError, match="Amount must be positive"):
		credit(ledger, "CHK-1", "-5.00")


def test_amount_rounds_to_nearest_cent() -> None:
	ledger = BankingLedger()
	create_account(ledger, "CHK-1")

	transaction = credit(ledger, "CHK-1", "10.005")

	assert transaction.amount == Decimal("10.01")
	assert balance(ledger, "CHK-1") == Decimal("10.01")


def test_running_balance_reflects_full_transaction_history() -> None:
	ledger = BankingLedger()
	account = create_account(ledger, "CHK-1")
	credit(ledger, "CHK-1", "100.00")
	debit(ledger, "CHK-1", "30.00")
	credit(ledger, "CHK-1", "5.00")

	assert [t.running_balance for t in account.transactions] == [
		Decimal("100.00"),
		Decimal("70.00"),
		Decimal("75.00"),
	]
	assert len({t.id for t in account.transactions}) == 3
	assert balance(ledger, "CHK-1") == Decimal("75.00")


def test_controller_debit_allows_overdraft_when_requested() -> None:
	ledger = BankingLedger()
	create_account(ledger, "CHK-1")
	credit(ledger, "CHK-1", "10.00")

	transaction = debit(ledger, "CHK-1", "15.00", allow_overdraft=True)

	assert transaction.running_balance == Decimal("-5.00")
	assert balance(ledger, "CHK-1") == Decimal("-5.00")


def test_controller_list_accounts_returns_sorted_account_ids() -> None:
	ledger = BankingLedger()
	create_account(ledger, "SAV-1")
	create_account(ledger, "CHK-1")

	assert list_accounts(ledger) == ["CHK-1", "SAV-1"]


def test_controller_list_transactions_returns_account_history_in_order() -> None:
	ledger = BankingLedger()
	create_account(ledger, "CHK-1")
	credit(ledger, "CHK-1", "20.00")
	debit(ledger, "CHK-1", "7.50")

	transactions = list_transactions(ledger, "CHK-1")

	assert [transaction.type for transaction in transactions] == ["credit", "debit"]
	assert [transaction.running_balance for transaction in transactions] == [
		Decimal("20.00"),
		Decimal("12.50"),
	]