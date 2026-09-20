"""Banking ledger application controller."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from model.banking_ledger_model import BankingLedger, Account, Transaction


def parse_amount(text: str) -> Decimal:
	try:
		return Decimal(text.strip())
	except InvalidOperation as exc:
		raise ValueError(f"Invalid amount: {text}") from exc


def create_account(ledger: BankingLedger, account_id: str) -> Account:
	return ledger.create_account(account_id)


def credit(ledger: BankingLedger, account_id: str, amount_text: str) -> Transaction:
	return ledger.credit(account_id, parse_amount(amount_text))


def debit(
	ledger: BankingLedger,
	account_id: str,
	amount_text: str,
	allow_overdraft: bool = False,
) -> Transaction:
	return ledger.debit(account_id, parse_amount(amount_text), allow_overdraft=allow_overdraft)


def balance(ledger: BankingLedger, account_id: str) -> Decimal:
	return ledger.balance(account_id)


def list_accounts(ledger: BankingLedger) -> list[str]:
	return ledger.list_accounts()


def list_transactions(ledger: BankingLedger, account_id: str) -> list[Transaction]:
	return list(ledger.get_account(account_id).transactions)