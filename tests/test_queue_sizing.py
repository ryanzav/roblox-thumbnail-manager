from src.queue import candidates_needed


def test_full_active_set_generates_nothing():
    assert candidates_needed(active_count=5, queued_count=0, target_active=5) == 0


def test_one_open_slot_generates_one():
    assert candidates_needed(active_count=4, queued_count=0, target_active=5) == 1


def test_queued_candidates_count_against_open_slots():
    # Two slots open but two candidates already waiting: nothing to pay for.
    assert candidates_needed(active_count=3, queued_count=2, target_active=5) == 0


def test_generates_only_the_shortfall():
    assert candidates_needed(active_count=3, queued_count=1, target_active=5) == 1


def test_empty_active_set_fills_every_slot():
    assert candidates_needed(active_count=0, queued_count=0, target_active=5) == 5


def test_surplus_queue_never_goes_negative():
    # The current situation: 10 leftover candidates, one open slot.
    assert candidates_needed(active_count=4, queued_count=10, target_active=5) == 0


def test_over_target_active_set_generates_nothing():
    # Roblox reporting more active thumbnails than the target must not
    # produce a negative request.
    assert candidates_needed(active_count=7, queued_count=0, target_active=5) == 0
