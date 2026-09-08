import pytest

from core.session import derive_session

CHINA = [570, 571, 572, 580, 590, 600, 610, 620, 630, 640, 650, 660, 670, 680,
         690, 780, 790, 800, 810, 820, 830, 840, 850, 860, 870, 880, 890, 900]
US = list(range(570, 961, 10))


def test_lunch_break_detected():
    s = derive_session(CHINA, v_open_pm=2000.0)
    assert s.open_min == 570 and s.close_min == 900
    assert s.lunch == (690, 780)
    assert s.is_two_session and s.has_pm_auction and s.warnings == ()


def test_continuous_session_has_no_lunch():
    s = derive_session(US, v_open_pm=0.0)
    assert s.lunch is None and not s.is_two_session and not s.has_pm_auction
    assert s.warnings == ()


def test_pm_auction_without_gap_is_a_warning_not_a_crash():
    s = derive_session(US, v_open_pm=2000.0)
    assert s.lunch is None and s.has_pm_auction
    assert len(s.warnings) == 1 and "no lunch" in s.warnings[0].lower()


def test_too_few_buckets_raises():
    with pytest.raises(ValueError):
        derive_session([570], v_open_pm=0.0)
