"""Banking ledger command-line interface."""

from __future__ import annotations

import sys

from controller.banking_ledger_controller import balance, create_account, credit, debit
from model.banking_ledger_model import BankingLedger


def run_interactive() -> int:
	ledger = BankingLedger()
	print("Banking Ledger")
	print("Commands: create, credit, debit, balance, quit")

	while True:
		command = input("Command: ").strip().lower()
		if command in {"q", "quit", "exit"}:
			return 0

		try:
			if command == "create":
				account = create_account(ledger, input("Account id: "))
				print(f"Created account: {account.id}")
			elif command == "credit":
				transaction = credit(ledger, input("Account id: "), input("Amount: "))
				print(f"Credited {transaction.amount} to {transaction.account}")
				print(f"Balance: {transaction.running_balance}")
			elif command == "debit":
				transaction = debit(ledger, input("Account id: "), input("Amount: "))
				print(f"Debited {transaction.amount} from {transaction.account}")
				print(f"Balance: {transaction.running_balance}")
			elif command == "balance":
				account_id = input("Account id: ")
				print(f"Balance: {balance(ledger, account_id)}")
			else:
				print("Unknown command")
		except ValueError as error:
			print(error)


def main(argv: list[str] | None = None) -> int:
	_ = sys.argv[1:] if argv is None else argv
	return run_interactive()