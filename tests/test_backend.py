from googledrive_sync.backend import q_and, epoch_to_rfc3339, _escape


def test_q_and_skips_empty():
    assert q_and("", "a = 1", "", "b = 2") == "a = 1 and b = 2"
    assert q_and("") == ""


def test_epoch_to_rfc3339_is_utc():
    # 0 == 1970-01-01T00:00:00 UTC
    assert epoch_to_rfc3339(0) == "1970-01-01T00:00:00"


def test_escape_quotes():
    assert _escape("o'brien") == "o\\'brien"
    assert _escape("a\\b") == "a\\\\b"
