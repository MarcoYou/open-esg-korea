# ChatGPT(Codex)에 연결하기

[← README 로 돌아가기](../README.md)

`.mcpb` 확장은 **Claude Desktop 전용 형식**입니다. ChatGPT 쪽에서 쓰려면 Codex 에 MCP 서버로
직접 물려야 하는데, 어렵지 않습니다 — 명령 한 줄입니다.

> [!NOTE]
> **ChatGPT 웹·앱에서는 안 됩니다.** 로컬 MCP 서버를 붙일 수 있는 것은 **Codex**(CLI · IDE 확장 ·
> Codex 앱)입니다. 셋 다 `~/.codex/config.toml` 하나를 같이 읽습니다.

## 0. 준비물

| | |
|---|---|
| **ChatGPT 계정** | Codex 는 Free · Go · Plus · Pro · Business · Edu · Enterprise 플랜에 **모두 포함**됩니다. 무료로도 시작할 수 있지만 무료 플랜은 「간단한 코딩 작업을 살펴보는」 수준이라 계속 쓰려면 Plus 이상이 편합니다 ([요금제](https://learn.chatgpt.com/docs/pricing)) |
| **Codex** | 아래 1번에서 설치합니다 |
| **[uv](https://docs.astral.sh/uv/)** | 서버를 띄우는 데 씁니다. `curl -LsSf https://astral.sh/uv/install.sh \| sh` (macOS·리눅스) |

파이썬은 따로 깔지 않아도 됩니다 — `uv` 가 알아서 맞춰 줍니다.
KRX·GIR·KIND 조회에는 **API 키가 필요 없습니다.**

## 1. Codex 설치

**macOS · 리눅스**

```bash
curl -fsSL https://chatgpt.com/codex/install.sh | sh
```

**Windows** (PowerShell)

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://chatgpt.com/codex/install.ps1 | iex"
```

패키지 매니저를 쓰셔도 됩니다.

```bash
npm install -g @openai/codex     # npm
brew install --cask codex        # Homebrew
```

설치했으면 `codex` 를 실행하고 **ChatGPT 계정으로 로그인**합니다.
데스크톱 앱을 쓰려면 `codex app`, 코드 편집기(VS Code · Cursor · Windsurf)에 넣으려면
[IDE 확장](https://developers.openai.com/codex/ide)을 설치하세요.

## 2. open-esg-korea 붙이기

명령 한 줄이면 끝입니다. **저장소를 내려받지 않아도 됩니다** — `uvx` 가 알아서 가져옵니다.

```bash
codex mcp add open-esg-korea -- uvx --from git+https://github.com/MarcoYou/open-esg-korea open-esg-korea --transport stdio
```

<details>
<summary><b>손으로 적고 싶다면</b> — <code>~/.codex/config.toml</code></summary>

<br>

```toml
[mcp_servers.open-esg-korea]
command = "uvx"
args = [
  "--from", "git+https://github.com/MarcoYou/open-esg-korea",
  "open-esg-korea", "--transport", "stdio",
]
```

이 저장소 안에서만 쓰고 싶으면 프로젝트 폴더의 `.codex/config.toml` 에 같은 내용을 넣으면 됩니다.

</details>

<details>
<summary><b>저장소를 이미 받아 뒀다면</b></summary>

<br>

```bash
codex mcp add open-esg-korea -- uv run --directory /path/to/open-esg-korea python -m open_esg_korea --transport stdio
```

</details>

## 3. 확인

```bash
codex mcp list
```

`open-esg-korea` 가 보이면 됩니다. Codex 를 띄운 뒤 TUI 안에서 `/mcp` 를 쳐도 붙은 서버가 나옵니다.

이제 물어보세요.

> **삼성전자 ESG 등급 알려줘**

5개 기관 등급표가 출처·연도·이용조건과 함께 나오면 연결된 것입니다.
무엇을 물을 수 있는지는 [README 의 「이렇게 물어보세요」](../README.md#-이렇게-물어보세요)에 있습니다.

## 안 될 때

| 증상 | 어떻게 하나 |
|---|---|
| `codex: command not found` | 설치 뒤 터미널을 새로 여세요. npm 으로 깔았다면 `npm bin -g` 경로가 `PATH` 에 있는지 확인 |
| `uvx: command not found` | uv 를 설치하세요 — `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| **처음 한 번이 느림** | `uvx` 가 저장소를 받아 환경을 만드느라 그렇습니다(1~2분). 두 번째부터는 캐시로 바로 뜹니다 |
| **도구가 안 보임** | `codex mcp get open-esg-korea` 로 등록 내용을 확인하고, Codex 를 껐다 켜세요 |
| **회사 이름을 물으면 오류** | 사내망이 KRX 를 막고 있을 수 있습니다. 브라우저로 [esg.krx.co.kr](https://esg.krx.co.kr) 이 열리는지 먼저 확인 |
| **최신 버전으로 갱신** | `uv cache clean` 후 Codex 재시작 — `uvx` 가 저장소를 다시 받습니다 |

## HTTP 로 붙이기 (선택)

stdio 대신 서버를 띄워 두고 붙일 수도 있습니다.

```bash
uv run python -m open_esg_korea          # http://localhost:8000/mcp
codex mcp add open-esg-korea --url http://localhost:8000/mcp
```

> [!WARNING]
> **포트를 바꾸려면 `FASTMCP_ALLOWED_HOSTS` 도 같이 주세요.** DNS 리바인딩 보호가 켜져 있어
> 허용 목록에 없는 host 헤더는 거부합니다 — `/health` 는 열리는데 `/mcp` 만
> `Invalid Host header` 로 막혀 원인을 찾기 어렵습니다.
>
> ```bash
> FASTMCP_PORT=8123 FASTMCP_ALLOWED_HOSTS=localhost:8123,127.0.0.1:8123 uv run python -m open_esg_korea
> ```

기본 포트(8000)를 쓰면 그냥 됩니다.

## 떼어내기

```bash
codex mcp remove open-esg-korea
```

---

## 읽을 때 주의

Codex 로 붙이든 Claude Desktop 으로 붙이든 **데이터를 읽는 규칙은 같습니다** —
기관 간 등급을 나란히 두지 않기, `-` 는 미평가, 「상위 N%」는 만들지 않기, 업종 체계 셋을 섞지 않기.
[README 의 「읽을 때 주의」](../README.md#읽을-때-주의)를 보세요.

**라이선스도 같습니다.** 코드는 Apache-2.0 이지만 **등급 데이터는 그 라이선스에 들어가지 않습니다** —
다섯 평가기관 모두 대외 공개를 금지합니다. [NOTICE](../NOTICE) 를 읽어 주세요.

## 출처

- [Codex — MCP 설정](https://learn.chatgpt.com/docs/extend/mcp?surface=cli) (`~/.codex/config.toml`, `codex mcp add`)
- [Codex 요금제](https://learn.chatgpt.com/docs/pricing) (플랜별 포함 범위)
- [openai/codex README](https://github.com/openai/codex) (설치 명령)

<sub>2026-09-09 확인. `codex mcp add` 문법은 codex-cli 0.135.0 에서, 위 `uvx` 명령은 실제로 붙여
도구 12개가 응답하는 것까지 확인했습니다.</sub>
