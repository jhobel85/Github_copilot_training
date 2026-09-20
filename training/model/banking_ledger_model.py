"""Banking ledger business rules and transaction records."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from uuid import uuid4

from model.calculator_model import add, subtract

MONEY_QUANTUM = Decimal("0.01")


def _normalize_amount(amount: Decimal) -> Decimal:
	return amount.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def _now() -> datetime:
	return datetime.now(timezone.utc)


@dataclass(slots=True)
class Transaction:
	id: str
	timestamp: datetime
	account: str
	type: str
	amount: Decimal
	running_balance: Decimal


@dataclass(slots=True)
class Account:
	id: str
	transactions: list[Transaction] = field(default_factory=list)

	@property
	def balance(self) -> Decimal:
		if not self.transactions:
			return Decimal("0.00")
		return self.transactions[-1].running_balance


class BankingLedger:
	"""Store accounts and their transaction history in memory."""

	def __init__(self) -> None:
		self._accounts: dict[str, Account] = {}
		self._lock = threading.Lock()

	def create_account(self, account_id: str) -> Account:
		account_key = account_id.strip()
		if not account_key:
			raise ValueError("Account id is required")

		with self._lock:
			if account_key in self._accounts:
				raise ValueError(f"Account already exists: {account_key}")

			account = Account(id=account_key)
			self._accounts[account_key] = account
			return account

	def get_account(self, account_id: str) -> Account:
		account_key = account_id.strip()
		try:
			return self._accounts[account_key]
		except KeyError as exc:
			raise ValueError(f"Unknown account: {account_key}") from exc

	def credit(self, account_id: str, amount: Decimal) -> Transaction:
		return self._record_transaction(account_id, "credit", amount, allow_overdraft=True)

	def debit(self, account_id: str, amount: Decimal, allow_overdraft: bool = False) -> Transaction:
		return self._record_transaction(account_id, "debit", amount, allow_overdraft=allow_overdraft)

	def balance(self, account_id: str) -> Decimal:
		return self.get_account(account_id).balance

	def list_accounts(self) -> list[str]:
		return sorted(self._accounts)

	def _record_transaction(
		self,
		account_id: str,
		transaction_type: str,
		amount: Decimal,
		allow_overdraft: bool,
	) -> Transaction:
		account = self.get_account(account_id)
		normalized_amount = _normalize_amount(amount)
		if normalized_amount <= 0:
			raise ValueError("Amount must be positive")

		with self._lock:
			current_balance = account.balance
			if transaction_type == "credit":
				running_balance = _normalize_amount(add(current_balance, normalized_amount))
			else:
				running_balance = _normalize_amount(subtract(current_balance, normalized_amount))
				if running_balance < 0 and not allow_overdraft:
					raise ValueError("Insufficient funds")

			transaction = Transaction(
				id=str(uuid4()),
				timestamp=_now(),
				account=account.id,
				type=transaction_type,
				amount=normalized_amount,
				running_balance=running_balance,
			)
			account.transactions.append(transaction)
		return transaction