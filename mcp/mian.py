
# Minimal MCP server using the official MCP Python SDK
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("mcp-demo-server")

@mcp.tool(name="greet", description="Greet the user with a friendly message.")
def greet(name: str) -> str:
    return f"Hello, {name}! Welcome to the MCP demo server."

@mcp.tool()
def ping() -> dict:
    """Basic health check tool."""
    return {"status": "ok", "message": "pong"}


# Demo: Add two numbers
@mcp.tool()
def add(num1: int, num2: int) -> dict:
    """Add two numbers and return the result."""
    # for num in message.split(","):
    #     try:
    #         float(num)  # Validate that each part is a number
    #     except ValueError:
    #         return {"error": f"Invalid input '{num}'. Please provide numbers separated by commas."}
    result = num1 + num2
    return {"result": result}

# calculator + ledger

# Demo: Echo a message
@mcp.tool()
def echo(message: str) -> dict:
    """Echo the input message back to the caller."""
    # find my repos
    # repos = api.github.get_user().get_repos()
    return {"echo": message}

@mcp.tool()
def find_employee(): #name, EID
    pass # details+project they are working

@mcp.tool()
def find_project(): # project name, PID
    pass # details of project+ employee leading the project

if __name__ == "__main__":
    # VS Code MCP config starts this server as stdio.
    mcp.run(transport="stdio")