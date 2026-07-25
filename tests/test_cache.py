import tempfile

from eeweather.cache import KeyValueStore, _expired, key_value_store_proxy, set_path
from datetime import datetime, timedelta, timezone

import pytest



@pytest.fixture
def s():
    return KeyValueStore("sqlite:///{}/cache.db".format(tempfile.mkdtemp()))


def test_key_value_store(s):
    # key 'a' does not exist yet
    assert s.key_exists("a") is False
    assert s.retrieve_json("a") is None
    assert s.key_updated("a") is None

    # create key 'a'
    s.save_json("a", {"b": [1, "two", 3.0]})
    assert s.key_exists("a") is True
    data = s.retrieve_json("a")
    assert len(data["b"]) == 3
    assert data["b"][0] == 1
    assert data["b"][1] == "two"
    assert data["b"][2] == 3.0
    dt1 = s.key_updated("a")
    assert dt1.tzinfo is not None
    assert dt1.date() == datetime.now(timezone.utc).date()

    # update key 'a'
    s.save_json("a", ["updated"])
    data = s.retrieve_json("a")
    assert data[0] == "updated"

    # clear key 'a' (and everything)
    s.clear()
    assert s.key_exists("a") is False


def test_key_value_store_repr(s):
    assert repr(s) == 'KeyValueStore("{}")'.format(s.url)


def test_key_value_store_clear_single_key(s):
    # clear single key
    s.save_json("a", "b")
    s.save_json("b", "c")
    assert s.key_exists("a") is True
    assert s.key_exists("b") is True
    s.clear("b")
    assert s.key_exists("a") is True
    assert s.key_exists("b") is False


def test_key_value_store_rejects_non_sqlite_url():
    with pytest.raises(ValueError, match="sqlite:///"):
        KeyValueStore("postgresql://user@host/db")


def test_set_cache_path_points_shared_store(tmp_path):
    original = key_value_store_proxy._store
    try:
        path = "{}/custom.db".format(tmp_path)
        set_path(path)
        store = key_value_store_proxy.get_store()
        assert store.url == "sqlite:///{}".format(path)
        store.save_json("k", {"a": 1})
        assert key_value_store_proxy.get_store().retrieve_json("k") == {"a": 1}
    finally:
        key_value_store_proxy._store = original


def test_expired_when_never_updated():
    assert _expired(None, 2020) is True


def test_not_expired_when_updated_after_data_year():
    # data from a completed year never expires once publication settles
    last_updated = datetime(2021, 6, 1, tzinfo=timezone.utc)

    assert _expired(last_updated, 2020) is False


def test_expired_when_updated_within_the_year_end_grace_window():
    # a year cached days after it ends is still incomplete upstream
    last_updated = datetime(2021, 1, 2, tzinfo=timezone.utc)

    assert _expired(last_updated, 2020) is True


def test_not_expired_when_updated_after_the_grace_window():
    last_updated = datetime(2021, 1, 20, tzinfo=timezone.utc)

    assert _expired(last_updated, 2020) is False


def test_expired_when_updated_during_data_year_and_old():
    now = datetime.now(timezone.utc)
    last_updated = now - timedelta(days=2)

    assert _expired(last_updated, last_updated.year) is True


def test_not_expired_when_updated_during_data_year_and_fresh():
    now = datetime.now(timezone.utc)
    last_updated = now - timedelta(hours=1)

    assert _expired(last_updated, last_updated.year) is False
