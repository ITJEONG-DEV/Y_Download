"""config.py 영구 저장 로직 단위 테스트 (임시 폴더로 격리)."""


def test_settings_roundtrip(isolated_config):
    c = isolated_config
    assert c.get_download_dir("D:/기본") == "D:/기본"  # 없으면 기본값
    c.set_download_dir("D:/저장위치")
    assert c.get_download_dir("D:/기본") == "D:/저장위치"


def test_conflict_policy(isolated_config):
    c = isolated_config
    assert c.get_conflict_policy("number") == "number"
    c.set_conflict_policy("skip")
    assert c.get_conflict_policy("number") == "skip"


def test_item_defaults(isolated_config):
    c = isolated_config
    assert c.get_item_defaults() == {}
    c.set_item_defaults({"kind": "audio", "ext": "mp3", "quality": "192"})
    assert c.get_item_defaults()["kind"] == "audio"


def test_window(isolated_config):
    c = isolated_config
    assert c.get_window() is None
    c.set_window({"x": 10, "y": 20, "w": 800, "h": 600, "zoomed": False})
    assert c.get_window()["w"] == 800


def test_history_add_order_and_id(isolated_config):
    c = isolated_config
    c.add_history({"title": "첫째", "status": "성공"})
    c.add_history({"title": "둘째", "status": "실패"})
    hist = c.load_history()
    # 최신이 맨 앞
    assert hist[0]["title"] == "둘째"
    assert hist[1]["title"] == "첫째"
    # id 자동 부여
    assert all(e.get("id") for e in hist)


def test_history_delete(isolated_config):
    c = isolated_config
    c.add_history({"title": "지울 것", "status": "성공"})
    c.add_history({"title": "남길 것", "status": "성공"})
    hist = c.load_history()
    target_id = next(e["id"] for e in hist if e["title"] == "지울 것")
    c.delete_history(target_id)
    remaining = c.load_history()
    assert len(remaining) == 1 and remaining[0]["title"] == "남길 것"


def test_history_clear(isolated_config):
    c = isolated_config
    c.add_history({"title": "a"})
    c.add_history({"title": "b"})
    c.clear_history()
    assert c.load_history() == []


def test_history_limit(isolated_config, monkeypatch):
    c = isolated_config
    monkeypatch.setattr(c, "_HISTORY_LIMIT", 5)
    for i in range(8):
        c.add_history({"title": f"항목{i}"})
    hist = c.load_history()
    assert len(hist) == 5
    # 가장 최근 5개만 남음(최신이 앞)
    assert hist[0]["title"] == "항목7"
    assert hist[-1]["title"] == "항목3"
