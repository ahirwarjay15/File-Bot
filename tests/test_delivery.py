from app.services.delivery import _minutes, _notice, DEFAULT_NOTICE

def test_auto_delete_timer_accepts_blueprint_cycle():
    for minutes in (2, 5, 15, 30, 60, 180, 360, 720, 1440):
        assert _minutes({"minutes": minutes}) == minutes

def test_invalid_auto_delete_timer_falls_back_to_default():
    assert _minutes({"minutes": 7}) == 30
    assert _minutes({}) == 30

def test_auto_delete_notice_interpolates_timer():
    assert _notice({"notice": "Deleted in {auto_delete_time}", "minutes": 30}, 30) == "Deleted in 30 minutes"
    assert _notice({"notice": DEFAULT_NOTICE}, 60) == "Your files will be automatically deleted after 1 hour."
