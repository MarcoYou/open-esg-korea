#!/usr/bin/env python3
"""Claude Desktop 확장(.mcpb) 빌드 — 더블클릭 한 번으로 설치되게 만든다.

Why: 「설정 파일에 경로를 적고 uv 를 깔라」는 안내는 기술을 아는 사람만 통과한다. 확장은 파일을 끌어다
놓으면 끝이고, 켜고 끄는 것도 UI 에서 한다. 그래서 **받는 쪽에 아무것도 없어도 되게** 세 가지를 다 넣는다:

    runtime/   파이썬 배포판 — 파이썬이 안 깔린 기계에서도 돈다
    lib/       의존성(mcp·httpx·pypdfium2·pdfplumber)과 open_esg_korea 자신
    manifest.json
    launch-macos.sh   (macOS 만) 칩이 어긋난 파일을 받았을 때 무엇을 받아야 하는지 알려 준다

의존성은 **호스트 파이썬 버전·아키텍처가 아니라 번들 런타임 것에 맞춰** 받는다(`--python-version`·
`--python-platform`). 이걸 빼먹으면 cp314 휠이 3.12 런타임에 들어가 `ModuleNotFoundError` 로 조용히 죽고,
arm64 기계에서 만든 x86_64 번들이 `mach-o file, but is an incompatible architecture` 로 죽는다.

사용:  uv run python scripts/build_mcpb.py                          # 지금 이 기계에 맞는 것 하나
       uv run python scripts/build_mcpb.py --target macos-arm64     # 하나 지정
       uv run python scripts/build_mcpb.py --target all             # 셋 다
       uv run python scripts/build_mcpb.py --check                  # 만든 뒤 풀어서 stdio 핸드셰이크까지
                                                                    # (--check 는 이 기계에서 돌 수 있는 것만)

확장자는 **.mcpb 하나만** 낸다. 한때 어느 쪽을 받는지 몰라 .dxt 도 같이 냈는데, 설치해 보니 앱이
`Claude Extensions/local.mcpb.<author>.<name>/` 로 풀었다 — MCPB 가 이 클라이언트의 형식이다.
다만 매니페스트 **안의** 키 이름은 여전히 `dxt_version` 이고 값은 "0.2" 라야 한다(이름과 형식이 따로 논다).

플랫폼마다 런타임 출처가 다르다:

    windows-x64   python.org 임베드 배포판(11MB). 격리 모드라 PYTHONPATH 를 무시하므로
                  `runtime/python3xx._pth` 파일로 `lib` 을 경로에 넣는다.
    macos-arm64   python-build-standalone(astral-sh) install_only 배포판. python.org 는 macOS 용
    macos-x64     임베드 zip 을 내지 않는다. 이쪽은 격리 모드가 아니라서 `site-packages` 에 넣는
                  `.pth` 한 줄로 `lib` 을 잇는다(경로는 `sys.prefix` 기준이라 어디에 풀어도 따라온다).

macOS 번들은 **아키텍처별로 따로** 낸다. 런타임도 이진 휠(pypdfium2·Pillow)도 arm64/x86_64 가 다르고,
둘을 한 파일에 담으면 90MB 가 된다 — 받는 쪽이 한 번 고르는 편이 낫다. 다만 매니페스트로는 그 선택을
**검사할 수 없어서**(`compatibility.platforms` 에 darwin 뿐, arch 개념이 없다) 어긋난 파일도 설치는 된다.
그래서 macOS 번들만 파이썬을 `launch-macos.sh` 로 감싼다 — `macos_launcher()` 참고.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import json
import os
import pathlib
import platform
import shutil
import stat
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
#: README 상단 로고(assets/icon.png)와는 별개다 — 확장 목록에 뜨는 아이콘만 바꾸고 싶을 때 이 파일만 간다.
ICON_SRC = ROOT / "assets" / "icon-mcpb.png"
ICON_SIZE = 512          # 설치 화면·목록에서 쓰는 크기. 원본이 크면 줄여 넣는다(용량과 선명도 절충).
ICON_FILL = 0.94         # 로고가 정사각 변의 몇 할을 차지할지. 0.88 은 설치 화면에서 작아 보였다(실측 2026-09-08).

#: 런타임 의존성. pyproject 의 `[project].dependencies` 와 같아야 한다 — `mcp[cli]` 의 CLI 추가분은
#: 서버 실행에 필요 없고 17MB 를 더 얹는다(pygments·typer 등)이므로 여기서는 뺀다.
DEPS = ["mcp>=2.0.0,<3", "httpx>=0.28.1", "pypdfium2>=4.30", "pdfplumber>=0.11"]

#: python-build-standalone 릴리스 태그(날짜). 런타임을 올릴 때 여기와 `py_version` 을 같이 바꾼다.
PBS_TAG = "20260901"

#: 있으면 애플실리콘에서도 x86_64 번들을 돌려볼 수 있다(`Target.runnable_here`).
ROSETTA = pathlib.Path("/Library/Apple/usr/libexec/oah")


@dataclasses.dataclass(frozen=True)
class Target:
    """번들 하나가 겨냥하는 기계. 런타임·휠·매니페스트가 전부 여기서 갈린다."""

    key: str                 # CLI 이름이자 파일이름 꼬리
    label: str               # 사람이 읽는 이름 (로그·BUILD_INFO)
    manifest_platform: str   # manifest.compatibility.platforms
    py_version: str          # 번들에 넣는 파이썬
    uv_platform: str         # uv --python-platform
    command: str             # manifest.server.mcp_config.command
    host_system: str         # 이 번들을 --check 로 돌려볼 수 있는 os
    host_machine: tuple[str, ...] = ()   # 비어 있으면 아키텍처는 안 따진다

    @property
    def py_minor(self) -> str:
        return self.py_version.rsplit(".", 1)[0]      # "3.12.14" → "3.12"

    @property
    def py_tag(self) -> str:
        return self.py_minor.replace(".", "")          # "3.12" → "312"

    @property
    def runtime_url(self) -> str:
        if self.manifest_platform == "win32":
            return (f"https://www.python.org/ftp/python/{self.py_version}/"
                    f"python-{self.py_version}-embed-amd64.zip")
        arch = self.uv_platform.split("-", 1)[0]       # aarch64 / x86_64
        return (f"https://github.com/astral-sh/python-build-standalone/releases/download/"
                f"{PBS_TAG}/cpython-{self.py_version}+{PBS_TAG}-{arch}-apple-darwin-install_only.tar.gz")

    @property
    def runtime_cache(self) -> pathlib.Path:
        return CACHE / self.runtime_url.rsplit("/", 1)[1]

    def runnable_here(self) -> bool:
        """이 기계에서 번들을 실제로 실행해 볼 수 있나 — `--check` 를 건너뛸지 정한다.

        애플실리콘에서 x86_64 번들은 **Rosetta 2 가 깔려 있으면 돈다**(실측 2026-09-08: 도구 12개
        응답). 그래서 아키텍처가 다르다고 바로 건너뛰지 않는다 — 인텔 맥이 없어도 검사가 된다.
        """
        if platform.system().lower() != self.host_system:
            return False
        if not self.host_machine or platform.machine().lower() in self.host_machine:
            return True
        return (self.host_system == "darwin" and self.host_machine == ("x86_64",)
                and platform.machine().lower() == "arm64" and ROSETTA.is_dir())


TARGETS: dict[str, Target] = {
    "windows-x64": Target(
        key="windows-x64", label="Windows (x86-64)", manifest_platform="win32",
        py_version="3.12.8", uv_platform="x86_64-pc-windows-msvc",
        command="${__dirname}/runtime/python.exe",
        host_system="windows", host_machine=("amd64", "x86_64"),
    ),
    "macos-arm64": Target(
        key="macos-arm64", label="macOS Apple Silicon (M1 이상)", manifest_platform="darwin",
        py_version="3.12.14", uv_platform="aarch64-apple-darwin",
        command="${__dirname}/launch-macos.sh",
        host_system="darwin", host_machine=("arm64", "aarch64"),
    ),
    "macos-x64": Target(
        key="macos-x64", label="macOS Intel (x86-64)", manifest_platform="darwin",
        py_version="3.12.14", uv_platform="x86_64-apple-darwin",
        command="${__dirname}/launch-macos.sh",
        host_system="darwin", host_machine=("x86_64",),
    ),
}

#: macOS 런타임에서 빼는 것들 — GUI(tcl/tk·idle·turtle)·패키징(pip·setuptools)·개발용 헤더는
#: 서버가 쓰지 않는다. 안 빼면 압축 전 63MB 다. 뺀 뒤에도 `--check` 가 stdio 핸드셰이크로 확인한다.
MACOS_TRIM = [
    "include", "share", "lib/pkgconfig",
    "lib/libtcl*", "lib/libtk*", "lib/tcl*", "lib/tk*", "lib/itcl*", "lib/thread*",
    "lib/tdbc*", "lib/sqlite3*",
    "lib/python*/tkinter", "lib/python*/idlelib", "lib/python*/turtledemo",
    "lib/python*/turtle.py", "lib/python*/ensurepip", "lib/python*/test",
    "lib/python*/lib2to3", "lib/python*/pydoc_data", "lib/python*/config-*",
    "lib/python*/lib-dynload/_tkinter*", "lib/python*/lib-dynload/_test*",
    "lib/python*/site-packages/pip", "lib/python*/site-packages/pip-*",
    "lib/python*/site-packages/setuptools", "lib/python*/site-packages/setuptools-*",
    "lib/python*/site-packages/pkg_resources", "lib/python*/site-packages/_distutils_hack",
]


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


def default_target() -> str:
    """아무것도 안 주면 지금 이 기계용을 만든다 — 만든 자리에서 바로 `--check` 가 되게.

    Rosetta 로 「돌기만」 하는 것은 기본값으로 고르지 않는다 — 아키텍처가 그대로 맞는 것만 본다.
    """
    system, machine = platform.system().lower(), platform.machine().lower()
    for t in TARGETS.values():
        if t.host_system == system and machine in t.host_machine:
            return t.key
    return "windows-x64"


def log(msg: str) -> None:
    # 윈도우 기본 콘솔은 cp949 라 「—」 하나에 빌드가 통째로 죽는다. 한글도 깨져 나온다.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    print(msg, flush=True)


def fetch_runtime(target: Target) -> pathlib.Path:
    """파이썬 배포판을 받아 둔다(플랫폼마다 한 번만)."""
    CACHE.mkdir(parents=True, exist_ok=True)
    path = target.runtime_cache
    if not path.exists():
        log(f"런타임 내려받는 중 … {target.runtime_url}")
        tmp = path.with_suffix(path.suffix + ".part")
        with urllib.request.urlopen(target.runtime_url, timeout=600) as r, tmp.open("wb") as fh:
            shutil.copyfileobj(r, fh)
        tmp.replace(path)          # 중간에 끊긴 파일을 캐시로 남기지 않는다
    return path


def build_runtime_windows(target: Target, dest: pathlib.Path, lib: pathlib.Path) -> None:
    with zipfile.ZipFile(fetch_runtime(target)) as z:
        z.extractall(dest)
    # 임베드 배포판은 격리 모드라 PYTHONPATH 를 보지 않는다 — 경로를 이 파일에 직접 적는다.
    # 경로는 python.exe 가 있는 폴더 기준 상대경로다.
    #
    # pywin32 는 `--target` 으로 깔면 세 군데로 흩어진다(win32 · win32\lib · pythonwin). 보통은
    # `pywin32.pth` 가 이어주는데 임베드 배포판은 그걸 처리하지 않는다. 빠뜨리면 `mcp.server.stdio` 가
    # `pywintypes` 를 못 찾아 **stdio 서버가 아예 안 뜬다**(빌드는 성공하고 설치 후에야 드러난다).
    paths = [f"python{target.py_tag}.zip", ".", "..\\lib"]
    for extra in ("win32", "win32\\lib", "pythonwin"):
        if (lib / extra.replace("\\", "/")).is_dir():
            paths.append(f"..\\lib\\{extra}")
    (dest / f"python{target.py_tag}._pth").write_text("\n".join([*paths, "import site"]) + "\n",
                                                      encoding="utf-8")

    # pywintypes 는 DLL 을 `sys.prefix` 아래에서도 찾는다 — 임베드 배포판의 prefix 는 이 폴더다.
    src = lib / "pywin32_system32"
    if src.is_dir():
        shutil.copytree(src, dest / "pywin32_system32", dirs_exist_ok=True)


def build_runtime_macos(target: Target, dest: pathlib.Path, lib: pathlib.Path) -> None:
    """python-build-standalone 을 풀고, 안 쓰는 것을 덜고, `lib` 을 경로에 잇는다."""
    import tarfile

    staging = dest.parent / "_runtime_src"
    if staging.exists():
        shutil.rmtree(staging)
    with tarfile.open(fetch_runtime(target)) as t:
        # `filter="tar"` 라야 실행 권한이 살아남는다 — `data` 는 모드를 손본다. 출처가 우리가
        # 고른 릴리스라 신뢰 범위 안이다.
        t.extractall(staging, filter="tar")
    shutil.move(str(staging / "python"), str(dest))     # 배포판은 `python/` 한 겹 안에 들어 있다
    shutil.rmtree(staging, ignore_errors=True)

    removed = 0
    for pattern in MACOS_TRIM:
        for path in sorted(dest.glob(pattern)):
            removed += 1
            shutil.rmtree(path) if path.is_dir() and not path.is_symlink() else path.unlink()
    # 심볼릭 링크는 zip 에 담지 않는다(푸는 쪽마다 처리가 다르다). `bin` 은 실행할 하나만 남긴다.
    real = dest / "bin" / f"python{target.py_minor}"
    if not real.is_file():
        raise SystemExit(f"런타임에 {real.name} 이 없습니다 — 배포판 구조가 바뀌었습니다.")
    for path in (dest / "bin").iterdir():
        if path.name != real.name:
            path.unlink()
            removed += 1
    log(f"런타임 정리: {removed}개 항목 제거 (GUI·pip·헤더)")

    # 격리 모드가 아니라서 `.pth` 한 줄이면 된다. 경로를 박아 넣지 않고 `sys.prefix` 에서 만든다 —
    # 앱이 어디에 풀든(`~/Library/Application Support/…/local.mcpb.…`) 따라온다.
    site = dest / "lib" / f"python{target.py_minor}" / "site-packages"
    site.mkdir(parents=True, exist_ok=True)
    (site / "_open_esg_korea_lib.pth").write_text(
        "import sys, os; sys.path.insert(0, os.path.abspath("
        "os.path.join(sys.prefix, os.pardir, 'lib')))\n", encoding="utf-8")

    if not lib.is_dir():
        raise SystemExit("lib/ 이 없습니다 — build_lib 을 먼저 부르세요.")


def build_lib(target: Target, dest: pathlib.Path) -> None:
    """의존성 + 우리 패키지. **번들 런타임 버전·아키텍처에 맞춰** 휠을 받는다.

    `uv pip` 을 쓴다 — 이 저장소의 venv 에는 pip 이 없다(uv 가 만든 것이라). 호스트가 3.13/3.14 여도,
    arm64 여도 `--python-version`·`--python-platform` 으로 목표 휠을 받아온다.
    """
    base = ["uv", "pip", "install", "--quiet", "--target", str(dest)]
    wheels = ["--python-version", target.py_minor,
              "--only-binary", ":all:", "--python-platform", target.uv_platform]
    log(f"의존성 받는 중 … (cp{target.py_tag} / {target.uv_platform})")
    subprocess.run(base + wheels + DEPS, check=True)
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


#: macOS 번들이 직접 파이썬을 부르지 않고 거치는 껍데기. 이름은 매니페스트 `command` 와 한 벌이다.
LAUNCHER_NAME = "launch-macos.sh"


def macos_launcher(target: Target) -> str:
    """칩이 어긋난 번들을 받았을 때 **무엇을 받아야 하는지** 말하고 죽는 껍데기.

    Why: MCPB 매니페스트의 `compatibility.platforms` 는 darwin·win32·linux 뿐이라 **arm64 와
    x86_64 를 구분하지 못한다**(사양 확인 2026-09-11). 그래서 애플실리콘 사용자가 인텔용 파일을
    받아도 설치 화면은 그냥 통과하고, 실행할 때 「Bad CPU type in executable」 같은 OS 오류만
    남는다 — 어느 파일을 받아야 하는지는 어디에도 안 나온다. 파일이 둘인 것은 런타임도 이진
    휠도 칩마다 다르기 때문이고, 하나로 합치면 90MB 가 된다(모듈 첫머리 참고).

    `uname -m` 을 먼저 비교해 막지 않는다 — **Rosetta 2 가 깔린 애플실리콘에서는 x86_64 번들이
    실제로 돈다**(실측 2026-09-08, 도구 12개 응답). 미리 막으면 잘 돌던 조합을 깨뜨린다.
    그래서 「일단 돌려 보고, 안 될 때만 안내한다」 순서다. 성공하면 `exec` 로 껍데기를 파이썬에
    넘겨 준다 — 중간에 셸이 남지 않아야 종료 신호가 그대로 전달된다.

    안내는 **stderr 로만** 쓴다. stdout 은 MCP 가 JSON-RPC 로 쓰는 통로라 한 줄이라도 섞이면
    프로토콜이 깨진다.
    """
    return (
        "#!/bin/sh\n"
        "# open-esg-korea — macOS 실행 껍데기.\n"
        "# 왜 파이썬을 직접 부르지 않는지는 scripts/build_mcpb.py 의 macos_launcher() 에 적혀 있습니다.\n"
        "set -u\n"
        'DIR=$(cd "$(dirname "$0")" && pwd)\n'
        'PY="$DIR/runtime/bin/python@@PYMINOR@@"\n'
        "\n"
        "# Rosetta 2 가 있으면 x86_64 번들도 돈다 — 칩을 비교하지 말고 실제로 돌려 본다.\n"
        'if "$PY" -c "" 2>/dev/null; then\n'
        '    exec "$PY" "$@"\n'
        "fi\n"
        "\n"
        'case "$(uname -m)" in\n'
        "    x86_64) need_key=macos-x64;   need_label='Intel'; need_en='Intel' ;;\n"
        "    *)      need_key=macos-arm64; need_label='Apple 실리콘(M1 이상)'; need_en='Apple Silicon' ;;\n"
        "esac\n"
        "\n"
        "cat >&2 <<EOF\n"
        "\n"
        "  이 확장은 이 Mac 에서 실행할 수 없습니다 — 칩에 맞지 않는 파일입니다.\n"
        "\n"
        "    받으신 파일 : @@LABEL@@\n"
        "    이 Mac      : $(uname -m) → $need_label 용 파일이 필요합니다\n"
        "\n"
        "  아래 파일을 받아 설치하세요. 설정 → 확장에서 지금 것을 삭제한 뒤 끌어다 놓으면 됩니다.\n"
        "\n"
        "    @@REPO@@/releases/latest/download/open-esg-korea-$need_key.mcpb\n"
        "\n"
        "  This build targets @@LABEL@@ and cannot run on this Mac. Download the\n"
        "  $need_en build from the link above and reinstall.\n"
        "\n"
        "EOF\n"
        "exit 1\n"
    ).replace("@@PYMINOR@@", target.py_minor).replace("@@LABEL@@", target.label).replace("@@REPO@@", REPO_URL)


def manifest(target: Target) -> dict:
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
            "이 확장의 코드는 Apache-2.0 입니다. 다만 **등급 데이터는 그 라이선스에 들어가지 않습니다** — "
            "각 평가기관의 저작물이고 다섯 곳 모두 대외 공개를 금지합니다. 확장은 값을 저장하지 않고 "
            "조회할 때마다 실시간으로 가져오며, 값마다 그 기관의 이용 조건과 원문 주소를 함께 보여줍니다. "
            "등급의 대외 공개·재배포에는 각 기관의 사전 승낙이 필요합니다."
        ),
        # 설치 화면이 「개발자 정보는 Anthropic 에서 확인하지 않았습니다」라고 경고한다 — 심사받은 확장이
        # 아니라는 뜻이다. 그러니 **어디서 왔는지 스스로 밝히는 칸**을 비워두지 않는다.
        "author": {"name": "MarcoYou", "url": "https://github.com/MarcoYou"},
        "repository": {"type": "git", "url": REPO_URL},
        "homepage": REPO_URL,
        "documentation": f"{REPO_URL}#readme",
        "support": f"{REPO_URL}/issues",
        "license": "Apache-2.0",
        "keywords": ["ESG", "KRX", "한국", "상장사", "온실가스", "지배구조"],
        "server": {
            "type": "python",
            "entry_point": "lib/open_esg_korea/__main__.py",
            "mcp_config": {
                "command": target.command,
                "args": ["-m", "open_esg_korea", "--transport", "stdio"],
            },
        },
        **({"icon": "icon.png"} if ICON_SRC.is_file() else {}),
        "tools": tool_entries(),
        # 스키마가 **모르는 키를 거부한다** — 예전에 `_notice` 로 고지를 넣었다가 매니페스트가 통째로
        # 반려됐다. 고지는 `long_description` 안에 둔다. 같은 이유로 `mcp_config.env` 도 쓰지 않는다 —
        # macOS 는 `.pth` 로 경로를 잇는다(build_runtime_macos).
        #
        # `runtimes.python` 을 적지 않는다. 파이썬은 `runtime/` 에 넣어 보내므로 **시스템 파이썬이
        # 필요 없는데**, 이걸 적으면 설치 화면이 「Python >=3.12.8 ⚠」를 요구사항으로 띄운다.
        # 파이썬 없는 PC 에서 쓰라고 11MB 를 넣어놓고 「파이썬 까세요」라고 겁주는 꼴이었다(실측 2026-09-08).
        "compatibility": {"platforms": [target.manifest_platform]},
    }


def package(target: Target) -> pathlib.Path:
    work = BUILD / target.key
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    log(f"\n=== {target.key} — {target.label} ===")
    build_lib(target, work / "lib")          # 런타임 경로가 lib 배치에 달려 있어 이 순서라야 한다
    if target.manifest_platform == "win32":
        build_runtime_windows(target, work / "runtime", work / "lib")
    else:
        build_runtime_macos(target, work / "runtime", work / "lib")
        launcher = work / LAUNCHER_NAME
        launcher.write_text(macos_launcher(target), encoding="utf-8")
        # zip 이 st_mode 를 담고 푸는 쪽이 되살린다(unpack 참고) — 여기서 +x 를 줘야 설치본이 실행된다.
        launcher.chmod(0o755)
    (work / "manifest.json").write_text(
        json.dumps(manifest(target), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # 매니페스트는 **모르는 키를 거부**하므로 빌드 출처를 그 안에 넣을 수 없다(예전에 `_notice` 로
    # 넣었다가 통째로 반려됐다). 파일로 넣는다 — zip 안의 파일은 검증 대상이 아니고, 압축을 풀면
    # 사람이 그냥 읽을 수 있다. 「이 파일 뭐지, 어디서 났지」를 나중에 풀 수 있게 하는 것이 목적이다.
    (work / "BUILD_INFO.txt").write_text("\n".join([
        f"open-esg-korea {project_version()}  ({target.key} — {target.label})",
        "",
        f"소스      {REPO_URL}",
        f"커밋      {build_stamp()}",
        f"빌드      {dt.datetime.now().astimezone().isoformat(timespec='seconds')}",
        f"만든 것   scripts/build_mcpb.py",
        "",
        f"런타임    {target.runtime_url}",
        f"의존성    {' · '.join(DEPS)}  (cp{target.py_tag} / {target.uv_platform})",
        "",
        "이 확장은 Anthropic 이 심사한 것이 아닙니다. 무엇이 들어 있는지는 위 저장소의",
        "scripts/build_mcpb.py 에 전부 적혀 있고, lib/ 아래 파이썬 코드는 그대로 읽을 수 있습니다.",
        "",
        "코드      Apache License 2.0 — 상업 이용 포함해 자유롭게, 출처만 밝히면 됩니다.",
        "          같이 들어 있는 LICENSE·NOTICE 를 보세요.",
        "데이터    Apache-2.0 에 **들어가지 않습니다.** 등급은 각 평가기관의 저작물이고 다섯 곳 모두",
        "          대외 공개를 금지합니다 — 저장하지 않고 조회할 때마다 실시간으로 가져오며,",
        "          조건은 응답에 값마다 붙어 나옵니다. 자세한 것은 NOTICE.",
        "",
        "번들 안 runtime/ 과 lib/ 은 제3자 배포물이며 각자의 라이선스를 따릅니다.",
    ]) + "\n", encoding="utf-8")
    if ICON_SRC.is_file():
        copy_icon(ICON_SRC, work / "icon.png")
    # LICENSE·NOTICE 는 **넣는 것이 조건**이다 — Apache-2.0 이 재배포본에 둘 다 두라고 요구한다.
    for name in ("README.md", "LICENSE", "NOTICE"):
        src = ROOT / name
        if src.is_file():
            shutil.copyfile(src, work / name)

    DIST.mkdir(exist_ok=True)
    # 파일이름에 **버전을 넣지 않는다.** 넣으면 릴리스마다 이름이 바뀌어
    # `releases/latest/download/<이름>` 직행 링크가 매번 썩는다 — README 의 다운로드 버튼이 그 링크다.
    # 버전은 `manifest.json`·`BUILD_INFO.txt` 안에 있고, 설치 후에는 앱의 확장 목록이 보여 준다.
    out = DIST / f"open-esg-korea-{target.key}.mcpb"
    log("압축하는 중 …")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for path in sorted(work.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                # `write()` 가 st_mode 를 external_attr 에 담는다 — macOS 는 python3.12 의 실행
                # 권한이 이 값으로 살아 나가야 한다(푸는 쪽이 모드를 복원하는 것을 전제한다).
                z.write(path, path.relative_to(work).as_posix())
    log(f"{out.name}  {out.stat().st_size / 1_048_576:.1f} MB")
    return out


def unpack(bundle: pathlib.Path, work: pathlib.Path) -> None:
    """zip 을 풀면서 **모드를 되살린다.** `extractall` 은 권한을 버려서 macOS 런타임이 실행되지 않는다
    — 설치 앱은 모드를 복원하므로, 검사도 같은 조건에서 해야 의미가 있다."""
    if work.exists():
        shutil.rmtree(work)
    with zipfile.ZipFile(bundle) as z:
        for info in z.infolist():
            path = pathlib.Path(z.extract(info, work))
            mode = info.external_attr >> 16
            if mode and path.is_file():
                os.chmod(path, stat.S_IMODE(mode))


def check(target: Target, bundle: pathlib.Path) -> int:
    """만든 것을 실제로 풀어서 매니페스트의 명령 그대로 돌려본다 — 「빌드는 됐는데 안 열린다」를 막는다."""
    if not target.runnable_here():
        log(f"확인 건너뜀 — {target.label} 번들은 이 기계에서 돌릴 수 없습니다")
        return 0
    work = ROOT / "build" / "check" / target.key
    unpack(bundle, work)
    mf = json.loads((work / "manifest.json").read_text(encoding="utf-8"))
    cfg = mf["server"]["mcp_config"]
    cmd = [cfg["command"].replace("${__dirname}", str(work)), *cfg["args"]]
    log(f"확인: {' '.join(cmd)}")

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
    ap.add_argument("--target", default=default_target(),
                    choices=[*TARGETS, "all"],
                    help=f"어느 기계용인가 (기본값: 지금 이 기계 = {default_target()})")
    ap.add_argument("--check", action="store_true", help="만든 뒤 풀어서 실제로 실행해 본다")
    args = ap.parse_args()

    keys = list(TARGETS) if args.target == "all" else [args.target]
    rc = 0
    made: list[pathlib.Path] = []
    for key in keys:
        target = TARGETS[key]
        bundle = package(target)
        made.append(bundle)
        if args.check:
            rc |= check(target, bundle)
    log("\n만든 것:")
    for path in made:
        log(f"  {path.relative_to(ROOT)}  {path.stat().st_size / 1_048_576:.1f} MB")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
