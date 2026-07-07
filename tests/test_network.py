"""
통합 테스트 — 실제 유튜브에 접속한다. 느리고 외부 상태에 의존하므로
기본 실행에서 제외되며, 필요할 때만 다음으로 실행한다:

    pytest -m network

유튜브 응답/영상 존재 여부에 따라 실패할 수 있다(테스트 자체 결함 아님).
"""
import pytest

import downloader as d

pytestmark = pytest.mark.network


def test_fetch_info_real():
    # 오래 유지되어 온 안정적인 공개 영상
    info = d.fetch_info("https://www.youtube.com/watch?v=dQw4w9WgXcQ", timeout=15)
    assert info.title
    assert info.duration > 0
    assert info.available_heights  # 해상도 목록이 하나 이상


def test_fetch_playlist_real():
    result = d.fetch_playlist("https://www.youtube.com/playlist?list=PLFgquLnL59alCl_2TQvOiD5Vgm1hCaGSI")
    assert result is not None
    title, entries = result
    assert title
    assert len(entries) > 1
    assert all(e.url.startswith("http") for e in entries)
