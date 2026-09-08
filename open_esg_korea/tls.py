"""TLS 컨텍스트 — **한 벌만**. 네 클라이언트(KRX·KIND·GIR·DART)가 같은 것을 쓴다.

왜 필요한가: httpx 는 기본으로 **certifi 묶음**만 신뢰하고 OS 인증서 저장소를 보지 않는다.
TLS 를 가로채는 사내망 뒤에서는 그 묶음에 없는 사설 루트 CA 로 인증서가 다시 서명돼 오기 때문에
`CERTIFICATE_VERIFY_FAILED: self-signed certificate in certificate chain` 로 **모든 호출이 죽는다**.
같은 망에서 브라우저는 되는데 서버만 안 되던 이유가 이것이다(2026-09-08 실측).

파이썬 기본 컨텍스트는 OS 저장소를 읽으므로 그걸 넘겨주기만 하면 된다. 실측(윈도우 사내망):

    certifi 묶음                    121장 → 연결 실패
    ssl.create_default_context()    384장 → 302 OK

**검증을 끄지 않는다.** 이 머신이 이미 믿는 CA 를 쓸 뿐이라, 가로채기가 없는 망에서는 동작이 같다.
직접 저장소를 열거해 얹어봐야 한 장도 늘지 않는다 — 기본 컨텍스트가 이미 한 일이다.
"""

from __future__ import annotations

import ssl


def ssl_context() -> ssl.SSLContext:
    """검증을 켠 채로, 이 머신의 OS 인증서 저장소를 신뢰하는 컨텍스트.

    `SSL_CERT_FILE`·`SSL_CERT_DIR` 이 있으면 파이썬이 알아서 그쪽을 쓴다 — 사내 표준 번들을
    쓰는 환경을 우리가 따로 덮어쓰지 않는다.
    """
    return ssl.create_default_context()
