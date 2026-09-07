"""MCP resources — 기능 안내(도구 목록에서 자동 구성)."""

from __future__ import annotations

import re

from mcp.server.mcpserver import MCPServer
from mcp.types import Annotations


def register_all_resources(mcp: MCPServer) -> None:
    @mcp.resource(
        "oek://tools_guide",
        name="tools_guide",
        title="open-esg-korea 기능 안내",
        description="현재 제공하는 ESG 도구 전체와 각 도구가 답하는 내용. 등록된 도구 설명에서 자동 구성된다.",
        mime_type="text/markdown",
        annotations=Annotations(audience=["user", "assistant"], priority=0.6),
    )
    async def tools_guide() -> str:
        tools = sorted(await mcp.list_tools(), key=lambda t: (t.name != "company", t.name))
        lines = ["# open-esg-korea 기능 안내", "",
                 "회사명이나 종목코드와 함께 ESG 질문을 자연어로 물어보세요. 도구 이름을 외울 필요는 없습니다.", "",
                 f"현재 제공하는 도구는 {len(tools)}개입니다. 아래 안내는 서버에 등록된 도구 설명에서 가져옵니다."]
        for tool in tools:
            desc = (tool.description or "설명이 등록되지 않았습니다.").strip()
            summary = re.split(r"\n\s*\n|\n\s*(?:when|rule|params|ref):", desc, maxsplit=1)[0]
            summary = re.sub(r"^desc:\s*", "", summary)
            lines.extend(["", f"## {tool.name}", "", " ".join(summary.split())])
        return "\n".join(lines)
