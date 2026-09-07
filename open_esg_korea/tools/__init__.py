"""Public MCP tool facades — 자동 발견 + 공통 예외 경계."""

from __future__ import annotations

import functools
import importlib
import pkgutil

from mcp.server.mcpserver.exceptions import ToolError

from open_esg_korea.services.safety import EXTERNAL_ERRORS, degrade_response


def _wrap_tool_errors(fn):
    @functools.wraps(fn)
    async def inner(*args, **kwargs):
        try:
            return await fn(*args, **kwargs)
        except EXTERNAL_ERRORS as exc:                       # 외부 → graceful degrade
            return degrade_response(getattr(fn, "__name__", "tool"), kwargs.get("format", "md"), exc)
        except Exception as exc:                             # noqa: BLE001 — 코드버그는 그대로
            raise ToolError(f"[ekind=crash] {exc}") from exc
    return inner


def register_all_tools(mcp) -> None:
    import open_esg_korea.tools as tools_pkg

    orig_tool = mcp.tool

    def wrapping_tool(*d_args, **d_kwargs):
        real = orig_tool(*d_args, **d_kwargs)

        def deco(fn):
            return real(_wrap_tool_errors(fn))
        return deco

    mcp.tool = wrapping_tool
    try:
        for _imp, modname, _pkg in pkgutil.iter_modules(tools_pkg.__path__):
            if modname.startswith("_"):
                continue
            module = importlib.import_module(f"open_esg_korea.tools.{modname}")
            if hasattr(module, "register_tools"):
                module.register_tools(mcp)
    finally:
        mcp.tool = orig_tool
