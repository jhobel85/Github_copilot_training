import threading
from datetime import datetime
from decimal import Decimal

import pytest

from model.banking_ledger_model import BankingLedger
from view import banking_ledger_mcp_view


@pytest.fixture(autouse=True)
def fresh_ledger(monkeypatch: pytest.MonkeyPatch) -> None:
	monkeypatch.setattr(banking_ledger_mcp_view, "_ledger", BankingLedger())


def test_create_account_tool_creates_account_with_zero_balance() -> None:
	assert banking_ledger_mcp_view.create_account_tool(" CHK-1 ") == {"account_id": "CHK-1"}
	assert banking_ledger_mcp_view.get_balance_tool("CHK-1") == {
		"account_id": "CHK-1",
		"balance": "0.00",
	}


def test_credit_and_debit_tools_serialize_transactions() -> None:
	banking_ledger_mcp_view.create_account_tool("CHK-1")

	credit_transaction = banking_ledger_mcp_view.credit_tool("CHK-1", "25.50")
	debit_transaction = banking_ledger_mcp_view.debit_tool("CHK-1", "5.25")

	assert credit_transaction["account"] == "CHK-1"
	assert credit_transaction["type"] == "credit"
	assert credit_transaction["amount"] == "25.50"
	assert credit_transaction["running_balance"] == "25.50"
	assert credit_transaction["id"]
	assert datetime.fromisoformat(credit_transaction["timestamp"]).tzinfo is not None
	assert debit_transaction["type"] == "debit"
	assert debit_transaction["amount"] == "5.25"
	assert debit_transaction["running_balance"] == "20.25"


def test_debit_tool_rejects_insufficient_funds_and_allows_requested_overdraft() -> None:
	banking_ledger_mcp_view.create_account_tool("CHK-1")

	with pytest.raises(ValueError, match="Insufficient funds"):
		banking_ledger_mcp_view.debit_tool("CHK-1", "1.00")

	transaction = banking_ledger_mcp_view.debit_tool("CHK-1", "1.00", allow_overdraft=True)

	assert transaction["running_balance"] == "-1.00"
	assert banking_ledger_mcp_view.get_balance_tool("CHK-1") == {
		"account_id": "CHK-1",
		"balance": "-1.00",
	}


def test_list_tools_return_sorted_accounts_and_ordered_serialized_history() -> None:
	banking_ledger_mcp_view.create_account_tool("SAV-1")
	banking_ledger_mcp_view.create_account_tool("CHK-1")
	banking_ledger_mcp_view.credit_tool("CHK-1", "10.00")
	banking_ledger_mcp_view.debit_tool("CHK-1", "3.00")

	transactions = banking_ledger_mcp_view.list_transactions_tool("CHK-1")

	assert banking_ledger_mcp_view.list_accounts_tool() == ["CHK-1", "SAV-1"]
	assert [(transaction["type"], transaction["running_balance"]) for transaction in transactions] == [
		("credit", "10.00"),
		("debit", "7.00"),
	]
	assert all(isinstance(transaction["amount"], str) for transaction in transactions)


def test_tools_propagate_duplicate_and_unknown_account_errors() -> None:
	banking_ledger_mcp_view.create_account_tool("CHK-1")

	with pytest.raises(ValueError, match="Account already exists: CHK-1"):
		banking_ledger_mcp_view.create_account_tool("CHK-1")
	with pytest.raises(ValueError, match="Unknown account: MISSING"):
		banking_ledger_mcp_view.credit_tool("MISSING", "10.00")
	with pytest.raises(ValueError, match="Unknown account: MISSING"):
		banking_ledger_mcp_view.list_transactions_tool("MISSING")


def test_concurrent_credit_tool_calls_have_no_race_condition() -> None:
	banking_ledger_mcp_view.create_account_tool("CHK-1")

	thread_count = 20
	barrier = threading.Barrier(thread_count)

	def credit_one() -> None:
		barrier.wait()
		banking_ledger_mcp_view.credit_tool("CHK-1", "1.00")

	threads = [threading.Thread(target=credit_one) for _ in range(thread_count)]
	for thread in threads:
		thread.start()
	for thread in threads:
		thread.join()

	transactions = banking_ledger_mcp_view.list_transactions_tool("CHK-1")

	assert len(transactions) == thread_count
	assert len({transaction["id"] for transaction in transactions}) == thread_count
	assert sorted(Decimal(transaction["running_balance"]) for transaction in transactions) == [
		Decimal(amount) for amount in range(1, thread_count + 1)
	]
	assert banking_ledger_mcp_view.get_balance_tool("CHK-1") == {
		"account_id": "CHK-1",
		"balance": f"{thread_count}.00",
	}


def test_concurrent_create_account_tool_calls_have_no_race_condition() -> None:
	thread_count = 20
	barrier = threading.Barrier(thread_count)
	results: list[str] = []
	results_lock = threading.Lock()

	def create_same_account() -> None:
		barrier.wait()
		try:
			banking_ledger_mcp_view.create_account_tool("SHARED")
		except ValueError as error:
			with results_lock:
				results.append(str(error))
		else:
			with results_lock:
				results.append("created")

	threads = [threading.Thread(target=create_same_account) for _ in range(thread_count)]
	for thread in threads:
		thread.start()
	for thread in threads:
		thread.join()

	assert results.count("created") == 1
	assert results.count("Account already exists: SHARED") == thread_count - 1
	assert banking_ledger_mcp_view.list_accounts_tool() == ["SHARED"]


def test_concurrent_debits_cannot_overdraw_an_account() -> None:
	banking_ledger_mcp_view.create_account_tool("CHK-1")
	banking_ledger_mcp_view.credit_tool("CHK-1", "10.00")

	thread_count = 20
	barrier = threading.Barrier(thread_count)
	results: list[str] = []
	results_lock = threading.Lock()

	def debit_one() -> None:
		barrier.wait()
		try:
			banking_ledger_mcp_view.debit_tool("CHK-1", "1.00")
		except ValueError as error:
			with results_lock:
				results.append(str(error))
		else:
			with results_lock:
				results.append("debited")

	threads = [threading.Thread(target=debit_one) for _ in range(thread_count)]
	for thread in threads:
		thread.start()
	for thread in threads:
		thread.join()

	transactions = banking_ledger_mcp_view.list_transactions_tool("CHK-1")

	assert results.count("debited") == 10
	assert results.count("Insufficient funds") == 10
	assert len(transactions) == 11
	assert Decimal(transactions[-1]["running_balance"]) == Decimal("0.00")
	assert banking_ledger_mcp_view.get_balance_tool("CHK-1")["balance"] == "0.00"


def test_concurrent_credits_to_independent_accounts_remain_isolated() -> None:
	account_ids = [f"ACC-{index}" for index in range(10)]
	for account_id in account_ids:
		banking_ledger_mcp_view.create_account_tool(account_id)

	credits_per_account = 10
	thread_count = len(account_ids) * credits_per_account
	barrier = threading.Barrier(thread_count)

	def credit_account(account_id: str) -> None:
		barrier.wait()
		banking_ledger_mcp_view.credit_tool(account_id, "1.00")

	threads = [
		threading.Thread(target=credit_account, args=(account_id,))
		for account_id in account_ids
		for _ in range(credits_per_account)
	]
	for thread in threads:
		thread.start()
	for thread in threads:
		thread.join()

	for account_id in account_ids:
		transactions = banking_ledger_mcp_view.list_transactions_tool(account_id)
		assert len(transactions) == credits_per_account
		assert Decimal(transactions[-1]["running_balance"]) == Decimal(credits_per_account)
		assert banking_ledger_mcp_view.get_balance_tool(account_id)["balance"] == "10.00"


def test_read_tools_remain_consistent_while_credits_are_in_flight() -> None:
	banking_ledger_mcp_view.create_account_tool("CHK-1")

	credit_count = 50
	start = threading.Barrier(2)
	writer_finished = threading.Event()
	observed_balances: list[Decimal] = []
	reader_failures: list[BaseException] = []

	def credit_many() -> None:
		start.wait()
		for _ in range(credit_count):
			banking_ledger_mcp_view.credit_tool("CHK-1", "1.00")
		writer_finished.set()

	def read_many() -> None:
		try:
			start.wait()
			while not writer_finished.is_set():
				observed_balances.append(
					Decimal(banking_ledger_mcp_view.get_balance_tool("CHK-1")["balance"])
				)
				transactions = banking_ledger_mcp_view.list_transactions_tool("CHK-1")
				if transactions:
					assert Decimal(transactions[-1]["running_balance"]) >= Decimal("1.00")
		except BaseException as error:
			reader_failures.append(error)

	writer = threading.Thread(target=credit_many)
	reader = threading.Thread(target=read_many)
	writer.start()
	reader.start()
	writer.join()
	reader.join()

	assert not reader_failures
	assert observed_balances
	assert all(Decimal("0.00") <= amount <= Decimal(credit_count) for amount in observed_balances)
	assert banking_ledger_mcp_view.get_balance_tool("CHK-1")["balance"] == "50.00"