FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY open_esg_korea/ open_esg_korea/
COPY --from=ghcr.io/astral-sh/uv:0.8.17 /uv /usr/local/bin/uv
# --locked: lock 과 pyproject 가 어긋나면 빌드를 실패시킨다(조용히 다른 버전 설치 금지)
RUN uv sync --locked --no-dev --no-editable && uv cache clean
RUN useradd -r -s /bin/false appuser
USER appuser
EXPOSE 8000
ENV FASTMCP_HOST=0.0.0.0 FASTMCP_PORT=8000
CMD ["/app/.venv/bin/python", "-m", "open_esg_korea", "--transport", "streamable-http"]
