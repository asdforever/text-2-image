from backend.app.application.generation_concurrency import AdaptiveConcurrency


def test_adaptive_concurrency_starts_at_configured_default_and_backs_off_after_failures() -> None:
    controller = AdaptiveConcurrency(3)

    assert controller.current == 3
    controller.record(False)
    assert controller.current == 2
    controller.record(False)
    assert controller.current == 1


def test_adaptive_concurrency_recovers_after_three_successes() -> None:
    controller = AdaptiveConcurrency(3)
    controller.record(False)

    controller.record(True)
    controller.record(True)
    assert controller.current == 2
    controller.record(True)
    assert controller.current == 3
