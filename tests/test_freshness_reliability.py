from datetime import datetime, timedelta, timezone

import pytest

from src.services.recommendation_scoring import (
    FRESHNESS_NEUTRAL_SCORE,
    calculate_freshness_score,
    calculate_recommendation_score,
    resolve_freshness_timestamp,
)


NOW = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)


def test_real_posted_at_has_precedence_over_newer_source_update():
    posted = NOW - timedelta(days=7)
    selected = resolve_freshness_timestamp(posted, NOW - timedelta(hours=1), NOW)

    assert selected.source == "posted_at"
    assert selected.timestamp_utc == posted
    assert calculate_freshness_score(posted, NOW, source_updated_at=NOW) == 70.5


def test_source_update_is_used_when_publication_time_is_missing():
    updated = NOW - timedelta(days=1)
    selected = resolve_freshness_timestamp(None, updated)

    assert selected.source == "source_updated_at"
    assert selected.is_local_proxy is False
    assert calculate_freshness_score(None, NOW, source_updated_at=updated) == 95.1


def test_ingestion_time_is_a_capped_lower_confidence_proxy():
    selected = resolve_freshness_timestamp(None, None, NOW)

    assert selected.source == "ingested_at"
    assert selected.is_local_proxy is True
    # A listing ingested today with no source time must not look posted today.
    assert calculate_freshness_score(None, NOW, ingested_at=NOW) == FRESHNESS_NEUTRAL_SCORE
    # An old local ingestion can still lower freshness below neutral.
    assert calculate_freshness_score(None, NOW, ingested_at=NOW - timedelta(days=30)) == 22.3


def test_missing_or_invalid_timestamps_are_neutral():
    assert resolve_freshness_timestamp(None).source == "none"
    assert calculate_freshness_score(None, NOW) == FRESHNESS_NEUTRAL_SCORE
    assert calculate_freshness_score(None, NOW, source_updated_at="not-a-timestamp") == FRESHNESS_NEUTRAL_SCORE
    assert calculate_freshness_score("not-a-timestamp", NOW, source_updated_at=NOW - timedelta(days=1)) == 95.1
    assert calculate_freshness_score(
        None,
        NOW,
        source_updated_at="not-a-timestamp",
        ingested_at=NOW,
    ) == FRESHNESS_NEUTRAL_SCORE


def test_naive_and_aware_values_are_normalized_to_utc():
    naive = datetime(2026, 9, 28, 12, 0)
    aware = datetime(2026, 9, 28, 15, 0, tzinfo=timezone(timedelta(hours=3)))

    assert resolve_freshness_timestamp(naive).timestamp_utc == NOW - timedelta(days=1)
    assert resolve_freshness_timestamp(aware).timestamp_utc == NOW - timedelta(days=1)
    assert calculate_freshness_score(naive, NOW) == calculate_freshness_score(aware, NOW) == 95.1


def test_future_and_very_old_timestamps_remain_bounded():
    assert calculate_freshness_score(NOW + timedelta(days=3), NOW) == 100.0
    assert calculate_freshness_score(NOW - timedelta(days=10_000), NOW) == 0.0


@pytest.mark.parametrize(
    "posted_at,source_updated_at,ingested_at",
    [
        (NOW, None, None),
        (None, NOW - timedelta(days=2), None),
        (None, None, NOW - timedelta(days=2)),
        ("invalid", "also-invalid", "still-invalid"),
    ],
)
def test_freshness_is_always_within_valid_bounds(posted_at, source_updated_at, ingested_at):
    score = calculate_freshness_score(
        posted_at,
        NOW,
        source_updated_at=source_updated_at,
        ingested_at=ingested_at,
    )
    assert 0.0 <= score <= 100.0


def test_recommendation_formula_and_freshness_weight_are_unchanged():
    neutral_total, _ = calculate_recommendation_score(50, 50, 50, 50, 50)
    fresh_total, _ = calculate_recommendation_score(50, 50, 50, 100, 50)

    assert neutral_total == 50.0
    assert fresh_total == 55.0
    assert fresh_total - neutral_total == 5.0  # 10% of a 50-point freshness increase
