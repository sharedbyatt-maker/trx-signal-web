import pytest
from drawings_persistence import _sanitize_drawings

def drawing(point):
    return [{"id":"future", "type":"vline", "points":[{"p":0,"t":410,"anchorLb":"20261012103010853","offset":50,**point}]}]

def test_future_time_survives_server_backup_format():
    result=_sanitize_drawings(drawing({"futureTime":29_000_000}))
    assert result[0]["points"][0]["futureTime"]==29_000_000
    assert result[0]["points"][0]["offset"]==50

def test_legacy_future_points_remain_compatible():
    assert "futureTime" not in _sanitize_drawings(drawing({}))[0]["points"][0]

@pytest.mark.parametrize("value", [True,-1,0,1.25,100_000_001,"nan",float("inf"),{}])
def test_invalid_future_times_are_rejected(value):
    with pytest.raises(ValueError,match="invalid future time"):
        _sanitize_drawings(drawing({"futureTime":value}))
