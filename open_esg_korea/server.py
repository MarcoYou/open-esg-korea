"""open-esg-korea MCP 서버 — MCPServer 진입점.

OPM(open-proxy-mcp) 과 같은 골격: `build_mcp()` 가 도구 표면을, `build_app()` 이 **프로덕션이 실제로
서빙하는 ASGI 앱**을 만든다. 테스트는 `build_app()` 에 대고 잰다.
"""

from __future__ import annotations

import argparse
import os

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

from open_esg_korea.resources import register_all_resources
from open_esg_korea.tools import register_all_tools


def _version() -> str:
    try:
        from importlib.metadata import version
        return version("open-esg-korea")
    except Exception:
        return ""


def build_mcp() -> MCPServer:
    mcp = MCPServer(
        "open-esg-korea",
        version=_version(),
        # 도구를 가로지르는 규칙만. 도구 하나로 표현되는 것은 그 도구의 description 에 있다.
        instructions=(
            "Korean-listed company ESG information from the KRX ESG Portal (esg.krx.co.kr). "
            "Natural-language questions work — you don't need tool names. Answer in the user's language.\n\n"
            "Resolve a company once with `company` (or pass a 6-digit ticker) and reuse the ticker downstream.\n\n"
            "Ratings come from five agencies with different scales (KCGS S~D, MSCI AAA~CCC, S&P 0-100 score, "
            "Sustinvest AA~E). Never compare grades across agencies as if they were one scale; always state the "
            "agency and the year next to a grade. A `-`/null grade means \"not rated by that agency\", never "
            "\"bad\". Read `status` and `warnings` before answering. State only values that appear in the response.\n\n"
            "Ratings are copyrighted by each agency and published on the KRX portal for non-commercial internal "
            "use; keep the `source` and `license` lines when you relay them.\n\n"
            "GHG emissions (`ghg_emissions`, `ghg_industry`, `ghg_national_inventory`) come from the Greenhouse Gas "
            "Inventory and Research Center (GIR): verified regulatory figures (direct + indirect) for companies under "
            "the ETS / target-management scheme, in tCO2eq. They differ from Scope 1/2/3 figures in sustainability "
            "reports; a company absent from GIR is not \"zero emissions\", it is simply below the reporting threshold."
        ),
    )
    register_all_tools(mcp)
    register_all_resources(mcp)

    @mcp.custom_route("/health", methods=["GET"])
    async def _health(_request):
        from starlette.responses import JSONResponse
        from open_esg_korea.dart.corp_codes import get_index
        from open_esg_korea.gir.client import get_gir_client
        from open_esg_korea.krx.client import get_client
        from open_esg_korea.krx.kind import get_kind_client
        from open_esg_korea.services.report_text import cache_stats
        return JSONResponse({"status": "ok", "tools": len(await mcp.list_tools()), "krx": get_client().stats(),
                             "dart": get_index().stats(), "gir": get_gir_client().stats(),
                             "kind": get_kind_client().stats(), "pdf_text_cache": cache_stats()})

    return mcp


def bind_host() -> str:
    return os.environ.get("FASTMCP_HOST", "0.0.0.0")


def bind_port() -> int:
    return int(os.environ.get("FASTMCP_PORT", "8000"))


def allowed_hosts() -> list[str]:
    """호스트 허용 목록. 포트는 **`bind_port()` 에서 온다** — 박아 두면 안 된다.

    8000 을 적어 두었더니 `FASTMCP_PORT` 를 바꾼 순간 `/mcp` 만 조용히 막혔다(실측 2026-09-09:
    `/health` 는 200 인데 `/mcp` 는 「Invalid Host header」). 뜨기는 떠서 포트 문제로 보이지 않고,
    막는 쪽이 `transport_security()` 라는 것도 응답에 안 나온다 — 원인을 찾는 데 오래 걸린다.
    """
    port = bind_port()
    hosts = [f"localhost:{port}", f"127.0.0.1:{port}", f"0.0.0.0:{port}"]
    extra = os.environ.get("FASTMCP_ALLOWED_HOSTS", "").strip()
    if extra:
        hosts.extend(h.strip() for h in extra.split(",") if h.strip())
    return hosts


def transport_security() -> TransportSecuritySettings:
    """호스트 보호를 **명시적으로** 켠다 — bind 가 0.0.0.0 이면 SDK 기본값은 조용히 꺼진다."""
    return TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=allowed_hosts())


def build_app(server: MCPServer | None = None):
    server = server or build_mcp()
    return server.streamable_http_app(
        stateless_http=True,
        json_response=True,
        transport_security=transport_security(),
        host=bind_host(),
        max_request_body_size=4 * 1024 * 1024,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    # 기본은 streamable-http(OPM 과 같다). stdio 는 Claude Desktop 로컬 연결용으로만 남긴다.
    parser.add_argument("--transport", choices=["streamable-http", "stdio"], default="streamable-http")
    args = parser.parse_args()
    server = build_mcp()
    if args.transport == "stdio":
        server.run(transport="stdio")
        return
    import uvicorn
    uvicorn.run(build_app(server), host=bind_host(), port=bind_port())


if __name__ == "__main__":
    main()
