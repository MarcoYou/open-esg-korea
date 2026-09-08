#!/usr/bin/env python3
"""Claude Desktop 확장(.mcpb) 빌드 — 더블클릭 한 번으로 설치되게 만든다.

Why: 「설정 파일에 경로를 적고 uv 를 깔라」는 안내는 기술을 아는 사람만 통과한다. 확장은 파일을 끌어다
놓으면 끝이고, 켜고 끄는 것도 UI 에서 한다. 그래서 **받는 쪽에 아무것도 없어도 되게** 세 가지를 다 넣는다:

    runtime/   python.org 임베드 배포판(11MB) — 파이썬이 안 깔린 PC 에서도 돈다
    lib/       의존성(mcp·httpx·pypdfium2·pdfplumber)과 open_esg_korea 자신
    manifest.json

`runtime/python3xx._pth` 로 `lib` 을 경로에 넣는다 — 임베드 배포판은 PYTHONPATH 를 무시하므로
환경변수가 아니라 이 파일이라야 한다.

의존성은 **호스트 파이썬 버전이 아니라 번들 런타임 버전에 맞춰** 받는다(`--python-version`).
이걸 빼먹으면 cp314 휠이 3.12 런타임에 들어가 `ModuleNotFoundError` 로 조용히 죽는다.

사용:  uv run python scripts/build_mcpb.py            # dist/open-esg-korea-<pyproject 버전>.mcpb
       uv run python scripts/build_mcpb.py --check    # 만든 뒤 풀어서 실제로 stdio 핸드셰이크까지 해본다

확장자는 **.mcpb 하나만** 낸다. 한때 어느 쪽을 받는지 몰라 .dxt 도 같이 냈는데, 설치해 보니 앱이
`Claude Extensions/local.mcpb.<author>.<name>/` 로 풀었다 — MCPB 가 이 클라이언트의 형식이다.
다만 매니페스트 **안의** 키 이름은 여전히 `dxt_version` 이고 값은 "0.2" 라야 한다(이름과 형식이 따로 논다).

윈도우(win_amd64) 전용이다 — 임베드 배포판과 이진 휠이 플랫폼별이다. macOS 용은 런타임만 갈아끼우면 된다.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DIST = ROOT / "dist"
BUILD = ROOT / "build" / "mcpb"
CACHE = ROOT / "build" / "cache"

#: 저장소 주소 한 벌 — 매니페스트의 여러 칸이 다 여기서 나온다.
REPO_URL = "https://github.com/MarcoYou/open-esg-korea"

#: 확장 아이콘. 있으면 번들에 넣고 매니페스트에 건다 — 없으면 그 칸을 아예 안 만든다
#: (빈 문자열을 넣으면 스키마가 거부할 수 있고, 앱은 기본 아이콘을 쓴다).
ICON_SRC = ROOT / "assets" / "icon.png"
ICON_SIZE = 512          # 설치 화면·목록에서 쓰는 크기. 원본이 크면 줄여 넣는다(용량과 선명도 절충).
ICON_FILL = 0.94         # 로고가 정사각 변의 몇 할을 차지할지. 0.88 은 설치 화면에서 작아 보였다(실측 2026-09-08).


def project_version() -> str:
    """버전은 `pyproject.toml` 이 유일한 출처다 — 매니페스트·파일이름에 손으로 적으면 어긋난다."""
    for line in (ROOT / "pyproject.toml").read_text(encoding="utf-8").splitlines():
        if line.startswith("version"):
            return line.split("=", 1)[1].strip().strip('"')
    raise SystemExit("pyproject.toml 에서 version 을 찾지 못했습니다.")


def build_stamp() -> str:
    """이 번들이 **어느 커밋에서 나왔는지** 남긴다 — 나중에 「이 파일 뭐지?」를 풀 수 있게."""
    try:
        sha = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, timeout=30).stdout.strip()
        dirty = subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain"],
                               capture_output=True, text=True, timeout=30).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        sha, dirty = "", ""
    return (sha or "(git 아님)") + (" +수정본" if dirty else "")


PY_VERSION = "3.12.8"
PY_TAG = "312"
PY_URL = f"https://www.python.org/ftp/python/{PY_VERSION}/python-{PY_VERSION}-embed-amd64.zip"

#: 런타임 의존성. pyproject 의 `[project].dependencies` 와 같아야 한다 — `mcp[cli]` 의 CLI 추가분은
#: 서버 실행에 필요 없고 17MB 를 더 얹는다(pygments·typer 등)이므로 여기서는 뺀다.
DEPS = ["mcp>=2.0.0,<3", "httpx>=0.28.1", "pypdfium2>=4.30", "pdfplumber>=0.11"]


def log(msg: str) -> None:
    # 윈도우 기본 콘솔은 cp949 라 「—」 하나에 빌드가 통째로 죽는다. 한글도 깨져 나온다.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    print(msg, flush=True)


def fetch_runtime() -> pathlib.Path:
    """python.org 임베드 배포판을 받아 둔다(한 번만)."""
    CACHE.mkdir(parents=True, exist_ok=True)
    zip_path = CACHE / f"python-{PY_VERSION}-embed-amd64.zip"
    if not zip_path.exists():
        log(f"런타임 내려받는 중 … {PY_URL}")
        with urllib.request.urlopen(PY_URL, timeout=300) as r, zip_path.open("wb") as fh:
            shutil.copyfileobj(r, fh)
    return zip_path


def build_runtime(dest: pathlib.Path, lib: pathlib.Path) -> None:
    with zipfile.ZipFile(fetch_runtime()) as z:
        z.extractall(dest)
    # 임베드 배포판은 격리 모드라 PYTHONPATH 를 보지 않는다 — 경로를 이 파일에 직접 적는다.
    # 경로는 python.exe 가 있는 폴더 기준 상대경로다.
    #
    # pywin32 는 `--target` 으로 깔면 세 군데로 흩어진다(win32 · win32\lib · pythonwin). 보통은
    # `pywin32.pth` 가 이어주는데 임베드 배포판은 그걸 처리하지 않는다. 빠뜨리면 `mcp.server.stdio` 가
    # `pywintypes` 를 못 찾아 **stdio 서버가 아예 안 뜬다**(빌드는 성공하고 설치 후에야 드러난다).
    paths = [f"python{PY_TAG}.zip", ".", "..\\lib"]
    for extra in ("win32", "win32\\lib", "pythonwin"):
        if (lib / extra.replace("\\", "/")).is_dir():
            paths.append(f"..\\lib\\{extra}")
    (dest / f"python{PY_TAG}._pth").write_text("\n".join([*paths, "import site"]) + "\n",
                                               encoding="utf-8")

    # pywintypes 는 DLL 을 `sys.prefix` 아래에서도 찾는다 — 임베드 배포판의 prefix 는 이 폴더다.
    src = lib / "pywin32_system32"
    if src.is_dir():
        shutil.copytree(src, dest / "pywin32_system32", dirs_exist_ok=True)


def build_lib(dest: pathlib.Path) -> None:
    """의존성 + 우리 패키지. **번들 런타임 버전에 맞춰** 휠을 받는다.

    `uv pip` 을 쓴다 — 이 저장소의 venv 에는 pip 이 없다(uv 가 만든 것이라). 호스트가 3.13/3.14 여도
    `--python-version`·`--python-platform` 으로 cp312·win_amd64 휠을 받아온다.
    """
    base = ["uv", "pip", "install", "--quiet", "--target", str(dest)]
    target = ["--python-version", PY_VERSION.rsplit(".", 1)[0],
              "--only-binary", ":all:", "--python-platform", "x86_64-pc-windows-msvc"]
    log(f"의존성 받는 중 … (cp{PY_TAG} / win_amd64)")
    subprocess.run(base + target + DEPS, check=True)
    log("open_esg_korea 넣는 중 …")
    subprocess.run(base + ["--no-deps", str(ROOT)], check=True)


def trim_box(im, bg, tol: int = 12):
    """배경색과 다른 픽셀의 경계. 원본에 붙은 여백을 걷어내려고 쓴다."""
    from PIL import Image, ImageChops
    diff = ImageChops.difference(im, Image.new("RGB", im.size, bg)).convert("L")
    return diff.point(lambda v: 255 if v > tol else 0).getbbox()


def copy_icon(src: pathlib.Path, dest: pathlib.Path) -> None:
    """정사각 PNG 로 맞춰 넣는다. Pillow 가 있으면 크기를 줄이고, 없으면 원본을 그대로 쓴다.

    Pillow 는 pdfplumber 가 이미 끌고 오므로 대개 있다 — 없다고 빌드를 멈출 이유는 없다.
    """
    try:
        from PIL import Image
    except ImportError:
        shutil.copyfile(src, dest)
        log(f"아이콘: 원본 그대로 넣음 ({src.name}) — Pillow 가 없어 크기를 못 맞췄습니다")
        return
    with Image.open(src) as raw:
        im = raw.convert("RGB")
        bg = im.getpixel((0, 0))                 # 모서리 색을 배경으로 본다
        box = trim_box(im, bg)
        if box is None:
            log("아이콘: 배경만 있어 그대로 넣습니다")
            im.save(dest, "PNG", optimize=True)
            return
        im = im.crop(box)
        # 앱이 아이콘에 **자기 둥근 프레임**을 씌운다 — 원본 여백을 그대로 두면 여백이 두 겹이 돼
        # 로고가 작아 보인다(실측 2026-09-08: 글자가 세로 35% 밖에 안 찼다). 잘라내고 다시 채운다.
        side = round(max(im.size) / ICON_FILL)
        canvas = Image.new("RGB", (side, side), bg)
        canvas.paste(im, ((side - im.width) // 2, (side - im.height) // 2))
        canvas = canvas.resize((ICON_SIZE, ICON_SIZE), Image.LANCZOS)
        canvas.save(dest, "PNG", optimize=True)
    fill = max(box[2] - box[0], box[3] - box[1]) / side * 100
    log(f"아이콘: {dest.name} {ICON_SIZE}x{ICON_SIZE} (여백 잘라내고 {fill:.0f}% 채움)")


def tool_entries() -> list[dict[str, str]]:
    """도구 목록 — 설치 화면에 「무엇을 하는 확장인가」로 보인다. 서버에서 그대로 읽는다."""
    from open_esg_korea.server import build_mcp
    out = []
    for name, fn in sorted(build_mcp()._tool_manager._tools.items()):
        first = (fn.description or "").strip().splitlines()[0] if fn.description else ""
        out.append({"name": name, "description": first.removeprefix("desc:").strip()})
    return out


def manifest() -> dict:
    return {
        # Claude Desktop 은 `dxt_version` 을 읽고 **"0.2" 만** 받는다(실측 2026-09-08: "0.1" 이면
        # 「Invalid literal value, expected "0.2"」로 미리보기부터 막힌다). 신형 리더용 `manifest_version`
        # 도 같이 둔다 — 검증기가 이 키는 문제 삼지 않았다.
        "dxt_version": "0.2",
        "manifest_version": "0.2",
        "name": "open-esg-korea",
        "display_name": "한국 상장사 ESG 정보",
        "version": project_version(),
        "description": "KRX ESG 포털·GIR·KIND 에서 한국 상장사의 ESG 등급·온실가스·지배구조 원문을 읽어옵니다.",
        "long_description": (
            "회사 이름만 말하면 됩니다 — 「삼성전자 ESG 등급 어때?」\n\n"
            "· 기관별 ESG 등급(KCGS·MSCI·한국ESG연구소·S&P·서스틴베스트)과 같은 기관 안에서의 위치\n"
            "· 온실가스 배출량(GIR 명세서·배출권거래제·국가 인벤토리)\n"
            "· 기업지배구조보고서·지속가능경영보고서 **원문**\n"
            "· GICS 산업군별 조회\n\n"
            "등급은 각 평가기관의 저작물입니다. 이 확장은 값을 저장하지 않고 조회할 때마다 실시간으로 "
            "가져오며, 값마다 그 기관의 이용 조건과 원문 주소를 함께 보여줍니다. "
            "**개인의 내부 용도로만** 쓸 수 있고, 대외 공개·재배포에는 각 기관의 사전 승낙이 필요합니다."
        ),
        # 설치 화면이 「개발자 정보는 Anthropic 에서 확인하지 않았습니다」라고 경고한다 — 심사받은 확장이
        # 아니라는 뜻이다. 그러니 **어디서 왔는지 스스로 밝히는 칸**을 비워두지 않는다.
        "author": {"name": "MarcoYou", "url": "https://github.com/MarcoYou"},
        "repository": {"type": "git", "url": REPO_URL},
        "homepage": REPO_URL,
        "documentation": f"{REPO_URL}#readme",
        "support": f"{REPO_URL}/issues",
        "license": "LicenseRef-PolyForm-Noncommercial-1.0.0",
        "keywords": ["ESG", "KRX", "한국", "상장사", "온실가스", "지배구조"],
        "server": {
            "type": "python",
            "entry_point": "lib/open_esg_korea/__main__.py",
            "mcp_config": {
                "command": "${__dirname}/runtime/python.exe",
                "args": ["-m", "open_esg_korea", "--transport", "stdio"],
            },
        },
        **({"icon": "icon.png"} if ICON_SRC.is_file() else {}),
        "tools": tool_entries(),
        # 스키마가 **모르는 키를 거부한다** — 예전에 `_notice` 로 고지를 넣었다가 매니페스트가 통째로
        # 반려됐다. 고지는 `long_description` 안에 둔다.
        #
        # `runtimes.python` 을 적지 않는다. 파이썬은 `runtime/` 에 넣어 보내므로 **시스템 파이썬이
        # 필요 없는데**, 이걸 적으면 설치 화면이 「Python >=3.12.8 ⚠」를 요구사항으로 띄운다.
        # 파이썬 없는 PC 에서 쓰라고 11MB 를 넣어놓고 「파이썬 까세요」라고 겁주는 꼴이었다(실측 2026-09-08).
        "compatibility": {"platforms": ["win32"]},
    }


def package() -> pathlib.Path:
    if BUILD.exists():
        shutil.rmtree(BUILD)
    BUILD.mkdir(parents=True)
    build_lib(BUILD / "lib")                 # 런타임 경로가 lib 배치에 달려 있어 이 순서라야 한다
    build_runtime(BUILD / "runtime", BUILD / "lib")
    (BUILD / "manifest.json").write_text(
        json.dumps(manifest(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # 매니페스트는 **모르는 키를 거부**하므로 빌드 출처를 그 안에 넣을 수 없다(예전에 `_notice` 로
    # 넣었다가 통째로 반려됐다). 파일로 넣는다 — zip 안의 파일은 검증 대상이 아니고, 압축을 풀면
    # 사람이 그냥 읽을 수 있다. 「이 파일 뭐지, 어디서 났지」를 나중에 풀 수 있게 하는 것이 목적이다.
    (BUILD / "BUILD_INFO.txt").write_text("\n".join([
        f"open-esg-korea {project_version()}",
        "",
        f"소스      {REPO_URL}",
        f"커밋      {build_stamp()}",
        f"빌드      {dt.datetime.now().astimezone().isoformat(timespec='seconds')}",
        f"만든 것   scripts/build_mcpb.py",
        "",
        f"런타임    python.org 임베드 배포판 {PY_VERSION} (win_amd64)",
        f"의존성    {' · '.join(DEPS)}",
        "",
        "이 확장은 Anthropic 이 심사한 것이 아닙니다. 무엇이 들어 있는지는 위 저장소의",
        "scripts/build_mcpb.py 에 전부 적혀 있고, lib/ 아래 파이썬 코드는 그대로 읽을 수 있습니다.",
        "",
        "등급은 각 평가기관의 저작물입니다 — 저장하지 않고 조회할 때마다 실시간으로 가져오며,",
        "개인의 내부 용도로만 쓸 수 있습니다. 조건은 응답에 값마다 붙어 나옵니다.",
    ]) + "\n", encoding="utf-8")
    if ICON_SRC.is_file():
        copy_icon(ICON_SRC, BUILD / "icon.png")
    for name in ("README.md", "LICENSE"):        # 있으면 같이 넣는다 — 받은 사람이 조건을 볼 수 있게
        src = ROOT / name
        if src.is_file():
            shutil.copyfile(src, BUILD / name)

    DIST.mkdir(exist_ok=True)
    out = DIST / f"open-esg-korea-{project_version()}.mcpb"
    log("압축하는 중 …")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for path in sorted(BUILD.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                z.write(path, path.relative_to(BUILD).as_posix())
    log(f"\n{out.name}  {out.stat().st_size / 1_048_576:.1f} MB")
    return out


def check(bundle: pathlib.Path) -> int:
    """만든 것을 실제로 풀어서 매니페스트의 명령 그대로 돌려본다 — 「빌드는 됐는데 안 열린다」를 막는다."""
    work = ROOT / "build" / "check"
    if work.exists():
        shutil.rmtree(work)
    with zipfile.ZipFile(bundle) as z:
        z.extractall(work)
    mf = json.loads((work / "manifest.json").read_text(encoding="utf-8"))
    cfg = mf["server"]["mcp_config"]
    cmd = [cfg["command"].replace("${__dirname}", str(work)), *cfg["args"]]
    log(f"\n확인: {' '.join(cmd)}")

    requests = "\n".join(json.dumps(r) for r in [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                    "clientInfo": {"name": "build-check", "version": "0"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
    ]) + "\n"
    # 세 요청을 쓰고 **stdin 을 닫으면 안 된다** — 서버가 initialize 만 답하고 EOF 를 보고 내려가는
    # 경쟁이 생긴다(실측: 같은 번들이 어떤 때는 도구 12개, 어떤 때는 id=2 응답 없이 종료코드 0).
    # 답을 받을 때까지 stdin 을 열어 두고 읽는다.
    # 인코딩을 명시하지 않으면 윈도우에서 cp949 로 읽다가 한글 도구 설명에서 터진다.
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    lines: list[str] = []
    tools = 0
    try:
        proc.stdin.write(requests)
        proc.stdin.flush()
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            line = proc.stdout.readline()
            if not line:                       # 서버가 먼저 내려갔다
                break
            lines.append(line)
            try:
                body = json.loads(line)
            except json.JSONDecodeError:
                continue
            if body.get("id") == 2:
                tools = len(body.get("result", {}).get("tools", []))
                break
    finally:
        proc.stdin.close()
        proc.terminate()
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()

    if tools:
        log(f"OK — 번들 런타임으로 도구 {tools}개 응답")
        return 0
    # 실패 이유를 안 보여주는 검사는 없느니만 못하다 — 종료코드·stdout·stderr 를 다 내놓는다.
    err = proc.stderr.read() if proc.stderr else ""
    log(f"FAIL — 도구 목록 응답이 없습니다 (종료코드 {proc.returncode})")
    log(f"  받은 줄 {len(lines)}개: {''.join(lines)[:600]!r}")
    log(f"  stderr: {err[-1500:]!r}")
    return 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Claude Desktop 확장(.mcpb)을 만듭니다.")
    ap.add_argument("--check", action="store_true", help="만든 뒤 풀어서 실제로 실행해 본다")
    args = ap.parse_args()
    bundle = package()
    return check(bundle) if args.check else 0


if __name__ == "__main__":
    raise SystemExit(main())
