"""A_chatter 频率函数测试。"""

from a_chatter.frequency import compute_trigger_probability


def test_frequency_higher_means_higher_probability() -> None:
    low = compute_trigger_probability(
        global_frequency=0.5,
        target_frequency=1.0,
        source_frequency=1.0,
        quiet_factor=1.0,
        elapsed_seconds=3600,
        base_interval_seconds=3600,
        min_interval_seconds=300,
        max_probability=0.85,
        intent_score=1.0,
    )
    high = compute_trigger_probability(
        global_frequency=2.0,
        target_frequency=1.0,
        source_frequency=1.0,
        quiet_factor=1.0,
        elapsed_seconds=3600,
        base_interval_seconds=3600,
        min_interval_seconds=300,
        max_probability=0.85,
        intent_score=1.0,
    )

    assert high > low


def test_min_interval_blocks_probability() -> None:
    probability = compute_trigger_probability(
        global_frequency=10.0,
        target_frequency=10.0,
        source_frequency=10.0,
        quiet_factor=1.0,
        elapsed_seconds=299,
        base_interval_seconds=3600,
        min_interval_seconds=300,
        max_probability=0.85,
        intent_score=1.0,
    )

    assert probability == 0.0


def test_zero_frequency_disables_auto_trigger() -> None:
    probability = compute_trigger_probability(
        global_frequency=1.0,
        target_frequency=0.0,
        source_frequency=1.0,
        quiet_factor=1.0,
        elapsed_seconds=3600,
        base_interval_seconds=3600,
        min_interval_seconds=300,
        max_probability=0.85,
        intent_score=1.0,
    )

    assert probability == 0.0

