"""MCP server exposing banking ledger operations as tools."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from mcp.server.mcpserver import MCPServer

from controller.banking_ledger_controller import (
    balance,
    create_account,
    credit,
    debit,
    list_accounts,
    list_transactions,
)
from model.banking_ledger_model import BankingLedger, Transaction

mcp = MCPServer(name="banking-ledger")

# Single in-memory ledger shared by all tool calls for the life of the server process.
_ledger = BankingLedger()


def _serialize_transaction(transaction: Transaction) -> dict[str, Any]:
    return {
        "id": transaction.id,
        "timestamp": transaction.timestamp.isoformat(),
        "account": transaction.account,
        "type": transaction.type,
        "amount": str(transaction.amount),
        "running_balance": str(transaction.running_balance),
    }


@mcp.tool()
def create_account_tool(account_id: str) -> dict[str, Any]:
    """Create a new ledger account and return its id."""
    account = create_account(_ledger, account_id)
    return {"account_id": account.id}


@mcp.tool()
def credit_tool(account_id: str, amount: str) -> dict[str, Any]:
    """Credit an account by the given amount and return the resulting transaction."""
    transaction = credit(_ledger, account_id, amount)
    return _serialize_transaction(transaction)


@mcp.tool()
def debit_tool(account_id: str, amount: str, allow_overdraft: bool = False) -> dict[str, Any]:
    """Debit an account by the given amount and return the resulting transaction."""
    transaction = debit(_ledger, account_id, amount, allow_overdraft=allow_overdraft)
    return _serialize_transaction(transaction)


@mcp.tool()
def get_balance_tool(account_id: str) -> dict[str, Any]:
    """Get the current balance of an account."""
    current_balance: Decimal = balance(_ledger, account_id)
    return {"account_id": account_id.strip(), "balance": str(current_balance)}


@mcp.tool()
def list_accounts_tool() -> list[str]:
    """List the ids of all known accounts."""
    return list_accounts(_ledger)


@mcp.tool()
def list_transactions_tool(account_id: str) -> list[dict[str, Any]]:
    """List the transaction history for an account, oldest first."""
    return [_serialize_transaction(transaction) for transaction in list_transactions(_ledger, account_id)]


def main() -> int:
    mcp.run(transport="stdio")
    return 0
