# Banking Ledger Manual

This project includes a simple in-memory banking ledger that supports four basic actions:

1. Create an account.
2. Credit money to an account.
3. Debit money from an account.
4. Check the current balance.

## Start The Ledger

Run the ledger application from the project root:

```bash
python banking_ledger.py
```

The app starts an interactive prompt and keeps the ledger in memory for the current session.

## Available Commands

At the prompt, enter one of these commands:

- `create`
- `credit`
- `debit`
- `balance`
- `quit`

## How To Use It

### 1. Create An Account

Choose `create`, then enter an account id such as `CHK-100`.

Example flow:

```text
Command: create
Account id: CHK-100
Created account: CHK-100
```

### 2. Credit Money

Choose `credit`, then enter the account id and the amount to add.

Example flow:

```text
Command: credit
Account id: CHK-100
Amount: 25.50
Credited 25.50 to CHK-100
Balance: 25.50
```

### 3. Debit Money

Choose `debit`, then enter the account id and the amount to subtract.

If the debit would make the balance negative, the ledger rejects it unless overdraft handling is explicitly enabled in code.

Example flow:

```text
Command: debit
Account id: CHK-100
Amount: 10.00
Debited 10.00 from CHK-100
Balance: 15.50
```

### 4. Check Balance

Choose `balance`, then enter the account id.

Example flow:

```text
Command: balance
Account id: CHK-100
Balance: 15.50
```

## Notes

- Balances are kept in memory and reset when the program exits.
- Amounts are treated as monetary values, so use normal decimal input such as `12.34`.
- The ledger records each transaction with an id, timestamp, account, type, amount, and running balance.

## MCP Server

The ledger's operations are also exposed as an MCP (Model Context Protocol) server so that MCP-compatible clients (such as AI agents) can call them as tools.

Requires the `mcp` package (`pip install "mcp[cli]"`).

### Important: don't run it directly in a terminal

`banking_ledger_mcp_server.py` communicates over **stdio** using the MCP JSON-RPC protocol, not human-readable prompts. If you run it directly (`python banking_ledger_mcp_server.py`), it will look like a blank/frozen terminal — that's expected. It is waiting for an MCP client to send protocol messages, not for you to type commands. Press `Ctrl+C` to stop it if you started it this way by mistake.

The server keeps one in-memory ledger for the life of the process, shared by every tool call. Available tools:

- `create_account_tool(account_id)`
- `credit_tool(account_id, amount)`
- `debit_tool(account_id, amount, allow_overdraft=False)`
- `get_balance_tool(account_id)`
- `list_accounts_tool()`
- `list_transactions_tool(account_id)`

### Using it from VS Code

This repo already includes [.vscode/mcp.json](.vscode/mcp.json), registering the server as `banking-ledger`:

```json
{
	"servers": {
		"banking-ledger": {
			"type": "stdio",
			"command": "${workspaceFolder}/.venv/Scripts/python.exe",
			"args": ["${workspaceFolder}/banking_ledger_mcp_server.py"]
		}
	}
}
```

To use it:

1. Open this workspace in VS Code with the GitHub Copilot Chat extension enabled.
2. Open the Chat view and switch to **Agent** mode.
3. Open the tools picker (the tools icon in the chat input) — `banking-ledger` should be listed, with its six tools available to select.
4. Ask the agent to perform a ledger action (e.g. "create account CHK-100 and credit it 25.50"); it will call the MCP tools automatically.

You can also manage the server via the Command Palette: `MCP: List Servers` → `banking-ledger` → `Start Server` / `Show Output` (useful for viewing logs or restarting after code changes).

### Using it from other MCP clients

Any MCP client that supports stdio servers (e.g. Claude Desktop) can launch it with a similar config, pointing `command` at the project's Python executable and `args` at `banking_ledger_mcp_server.py`'s absolute path. The client is responsible for starting/stopping the process — you never run it manually.
