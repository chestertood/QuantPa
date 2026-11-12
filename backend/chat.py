"""Chat assistant: Claude Code (via claude-agent-sdk) + read-only MCP tools.

Uses this machine's Claude Code login — no API key. Each tool calls the same
function the matching /api endpoint uses, so the assistant sees exactly what
the dashboard shows. Built-in tools (Bash, Read, Edit...) are disabled and
filesystem settings aren't loaded, so the chat can only call the tools below.
"""

import asyncio
import json
import os

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    create_sdk_mcp_server,
    query,
    tool,
)

EFFORTS = ("low", "medium", "high", "xhigh", "max")


def _model_and_effort() -> tuple[str, str]:
    """Pinned so the chat doesn't silently follow the CLI/account default model.
    Override with CHAT_MODEL / CHAT_EFFORT in backend/.env. Read per call: main
    imports this module before it runs load_dotenv()."""
    model = os.getenv("CHAT_MODEL", "claude-sonnet-5-5")
    effort = os.getenv("CHAT_EFFORT", "medium")
    if effort not in EFFORTS:
        raise ValueError(f"CHAT_EFFORT must be one of {'|'.join(EFFORTS)}, got {effort!r}")
    return model, effort

SYSTEM_PROMPT = """You are the assistant inside QuantPa, a personal stock-portfolio dashboard.
Answer in the user's language (usually Thai). Be concise; use short lists or tables for numbers.
Use the tools to fetch live data instead of guessing. Portfolio money values are in USD;
usd_thb_rate converts to baht. You are read-only: you cannot place orders or change anything.
If a tool fails (e.g. Webull auth), say what failed and what the user should check."""


def _endpoint(name: str):
    # Imported at call time: main imports this module, so a top-level import
    # would be circular. By the time a tool runs, main is fully loaded.
    import main
    return getattr(main, name)


async def _call(fn_name: str, *args):
    """Run a sync endpoint function off the event loop; errors become tool errors."""
    try:
        data = await asyncio.to_thread(_endpoint(fn_name), *args)
    except Exception as e:
        detail = getattr(e, "detail", None) or str(e)
        return {"content": [{"type": "text", "text": f"Error: {detail}"}], "is_error": True}
    return {"content": [{"type": "text", "text": json.dumps(data, default=str, ensure_ascii=False)}]}


@tool("get_portfolio", "Current positions, P/L, weights, portfolio totals and USD/THB rate.", {})
async def get_portfolio(args):
    return await _call("portfolio")


@tool("get_watchlists", "The user's Webull watchlists with live price and day change.", {})
async def get_watchlists(args):
    return await _call("watchlists")


@tool("get_news", "Market/econ headlines ranked by relevance to the portfolio.", {})
async def get_news(args):
    return await _call("get_news")


@tool("get_econ_calendar", "This week's high-impact economic events (ForexFactory).", {})
async def get_econ_calendar(args):
    return await _call("econ_calendar")


@tool("get_cashflow", "Deposit/withdrawal history and net cash flow.", {})
async def get_cashflow(args):
    return await _call("get_cashflow")


@tool("get_tax_summary", "Realized gains / dividends tax summary.", {})
async def get_tax_summary(args):
    return await _call("get_tax_summary")


@tool("get_fundamentals", "Valuation, profitability and health metrics for one ticker.", {"symbol": str})
async def get_fundamentals(args):
    return await _call("get_fundamentals", args["symbol"])


TOOLS = [get_portfolio, get_watchlists, get_news, get_econ_calendar,
         get_cashflow, get_tax_summary, get_fundamentals]
SERVER = create_sdk_mcp_server("quantpa", tools=TOOLS)
ALLOWED = [f"mcp__quantpa__{t.name}" for t in TOOLS]


async def ask(message: str, session_id: str | None = None) -> dict:
    """One chat turn. Pass the returned session_id back to continue the conversation."""
    model, effort = _model_and_effort()
    options = ClaudeAgentOptions(
        system_prompt=SYSTEM_PROMPT,
        model=model,
        effort=effort,
        mcp_servers={"quantpa": SERVER},
        tools=[],                 # no built-in tools: no Bash/Read/Edit on this machine
        allowed_tools=ALLOWED,
        permission_mode="dontAsk",  # anything not allowed is denied, never prompted
        setting_sources=[],       # ignore ~/.claude settings, hooks, CLAUDE.md
        resume=session_id,
        max_turns=10,
    )
    result, answered_by = None, None
    async for msg in query(prompt=message, options=options):
        if isinstance(msg, AssistantMessage):
            answered_by = msg.model  # what actually answered, not just what we asked for
        elif isinstance(msg, ResultMessage):
            result = msg
    if result is None:
        raise RuntimeError("Claude Code returned no result")
    if result.is_error:
        raise RuntimeError(result.result or result.subtype or "Claude Code error")
    return {"reply": result.result or "", "session_id": result.session_id,
            "model": answered_by, "effort": effort}
