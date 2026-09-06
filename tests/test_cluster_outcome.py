from __future__ import annotations

import pytest

from growthevo.evolution.cluster_outcome import (
    ClusterAggregationMode,
    ClusterOutcomeAccumulator,
    ClusterOutcomeSpec,
)
from growthevo.evolution.online_promotion import CanaryRoute
from growthevo.evolution.sequential_causal import HighPowerExposureTicket


def _mean_spec() -> ClusterOutcomeSpec:
    return ClusterOutcomeSpec(
        metric_name="cluster_value",
        aggregation=ClusterAggregationMode.MEAN,
        window_seconds=100,
        event_min=0.0,
        event_max=1.0,
        outcome_min=0.0,
        outcome_max=1.0,
        max_events=8,
        empty_value=0.0,
    )


def test_cluster_spec_fingerprint_binds_aggregation_semantics() -> None:
    mean = _mean_spec()
    binary = ClusterOutcomeSpec(
        metric_name="cluster_value",
        aggregation=ClusterAggregationMode.BINARY_ANY,
        window_seconds=100,
        event_min=0.0,
        event_max=1.0,
        outcome_min=0.0,
        outcome_max=1.0,
        max_events=8,
        empty_value=0.0,
    )
    assert mean.fingerprint != binary.fingerprint


def test_repeated_events_emit_one_cluster_level_mean() -> None:
    accumulator = ClusterOutcomeAccumulator(experiment_id="exp", spec=_mean_spec())
    ticket = accumulator.register_cluster(
        "user-1", assigned_to_challenger=True, exposure_at=10
    )
    accumulator.ingest_event("user-1", event_id="e1", event_at=20, value=0.2)
    accumulator.ingest_event("user-1", event_id="e2", event_at=30, value=0.8)
    accumulator.ingest_event("user-1", event_id="e3", event_at=40, value=0.5)
    result = accumulator.finalize("user-1", as_of=ticket.window_end)
    assert result.event_count == 3
    assert result.value == pytest.approx(0.5)
    assert result.cluster_id == "user-1"
    assert accumulator.event_count("user-1") == 3


def test_duplicate_event_id_cannot_inflate_cluster_sample_content() -> None:
    accumulator = ClusterOutcomeAccumulator(experiment_id="exp", spec=_mean_spec())
    accumulator.register_cluster("user-1", assigned_to_challenger=False, exposure_at=0)
    accumulator.ingest_event("user-1", event_id="same", event_at=1, value=0.5)
    with pytest.raises(ValueError, match="already been ingested"):
        accumulator.ingest_event("user-1", event_id="same", event_at=2, value=0.7)
    assert accumulator.event_count("user-1") == 1


def test_cluster_window_is_frozen_and_finalize_waits_for_maturity() -> None:
    accumulator = ClusterOutcomeAccumulator(experiment_id="exp", spec=_mean_spec())
    ticket = accumulator.register_cluster("user-1", assigned_to_challenger=True, exposure_at=10)
    with pytest.raises(ValueError, match="outside preregistered"):
        accumulator.ingest_event(
            "user-1", event_id="early", event_at=9, value=0.5
        )
    with pytest.raises(ValueError, match="window is not mature"):
        accumulator.finalize("user-1", as_of=ticket.window_end - 1)
    result = accumulator.finalize("user-1", as_of=ticket.window_end)
    assert result.value == 0.0
    with pytest.raises(RuntimeError, match="already finalized"):
        accumulator.ingest_event(
            "user-1", event_id="late", event_at=ticket.window_end, value=0.5
        )


def test_max_events_is_a_hard_preregistered_bound() -> None:
    spec = ClusterOutcomeSpec(
        metric_name="cluster_sum",
        aggregation=ClusterAggregationMode.SUM,
        window_seconds=100,
        event_min=0.0,
        event_max=2.0,
        outcome_min=0.0,
        outcome_max=4.0,
        max_events=2,
        empty_value=0.0,
    )
    accumulator = ClusterOutcomeAccumulator(experiment_id="exp", spec=spec)
    accumulator.register_cluster("account", assigned_to_challenger=True, exposure_at=0)
    accumulator.ingest_event("account", event_id="e1", event_at=1, value=2.0)
    accumulator.ingest_event("account", event_id="e2", event_at=2, value=2.0)
    with pytest.raises(ValueError, match="max_events"):
        accumulator.ingest_event("account", event_id="e3", event_at=3, value=0.0)
    result = accumulator.finalize("account", as_of=100)
    assert result.value == 4.0


def test_sum_bounds_must_cover_all_allowed_event_counts() -> None:
    with pytest.raises(ValueError, match="all preregistered event-count sums"):
        ClusterOutcomeSpec(
            metric_name="bad_sum",
            aggregation=ClusterAggregationMode.SUM,
            window_seconds=10,
            event_min=0.0,
            event_max=2.0,
            outcome_min=0.0,
            outcome_max=3.0,
            max_events=2,
            empty_value=0.0,
        )


def test_binary_any_has_explicit_empty_cluster_semantics() -> None:
    spec = ClusterOutcomeSpec(
        metric_name="converted",
        aggregation=ClusterAggregationMode.BINARY_ANY,
        window_seconds=10,
        event_min=0.0,
        event_max=1.0,
        outcome_min=0.0,
        outcome_max=1.0,
        max_events=4,
        empty_value=0.0,
    )
    accumulator = ClusterOutcomeAccumulator(experiment_id="exp", spec=spec)
    accumulator.register_cluster("empty", assigned_to_challenger=False, exposure_at=0)
    assert accumulator.finalize("empty", as_of=10).value == 0.0

    accumulator.register_cluster("hit", assigned_to_challenger=True, exposure_at=0)
    accumulator.ingest_event("hit", event_id="a", event_at=1, value=0.0)
    accumulator.ingest_event("hit", event_id="b", event_at=2, value=1.0)
    assert accumulator.finalize("hit", as_of=10).value == 1.0


def test_finalized_cluster_converts_to_exactly_one_canary_observation() -> None:
    accumulator = ClusterOutcomeAccumulator(experiment_id="exp", spec=_mean_spec())
    ticket = accumulator.register_cluster("user-1", assigned_to_challenger=True, exposure_at=0)
    accumulator.ingest_event("user-1", event_id="a", event_at=1, value=0.4)
    accumulator.ingest_event("user-1", event_id="b", event_at=2, value=0.8)
    result = accumulator.finalize("user-1", as_of=ticket.window_end)
    route = CanaryRoute(
        analysis_unit_id="user-1",
        in_canary=True,
        assigned_to_challenger=True,
        traffic_fraction=0.1,
        challenger_probability=0.5,
    )
    observation = result.as_canary_observation(route)
    assert observation.analysis_unit_id == "user-1"
    assert observation.metrics == {"cluster_value": pytest.approx(0.6)}


def test_high_power_conversion_preserves_original_stage_and_assignment() -> None:
    accumulator = ClusterOutcomeAccumulator(experiment_id="exp", spec=_mean_spec())
    ticket = accumulator.register_cluster("workspace", assigned_to_challenger=False, exposure_at=0)
    accumulator.ingest_event("workspace", event_id="a", event_at=1, value=0.25)
    result = accumulator.finalize("workspace", as_of=ticket.window_end)
    exposure = HighPowerExposureTicket(
        analysis_unit_id="workspace",
        routing_stage_index=2,
        in_canary=True,
        assigned_to_challenger=False,
        traffic_fraction=0.10,
        challenger_probability=0.5,
    )
    observation = result.as_high_power_observation(exposure, covariates={"pre": 1.0})
    assert observation.routing_stage_index == 2
    assert observation.metrics == {"cluster_value": 0.25}
    assert observation.covariates == {"pre": 1.0}


def test_route_identity_or_arm_mismatch_fails_closed() -> None:
    accumulator = ClusterOutcomeAccumulator(experiment_id="exp", spec=_mean_spec())
    ticket = accumulator.register_cluster("user-1", assigned_to_challenger=True, exposure_at=0)
    result = accumulator.finalize("user-1", as_of=ticket.window_end)
    bad_route = CanaryRoute(
        analysis_unit_id="other",
        in_canary=True,
        assigned_to_challenger=True,
        traffic_fraction=1.0,
        challenger_probability=0.5,
    )
    with pytest.raises(ValueError, match="route cluster differs"):
        result.as_canary_observation(bad_route)


def test_internal_state_retains_only_hashed_cluster_and_event_ids() -> None:
    accumulator = ClusterOutcomeAccumulator(experiment_id="exp", spec=_mean_spec())
    accumulator.register_cluster(
        "secret-cluster-id", assigned_to_challenger=True, exposure_at=0
    )
    accumulator.ingest_event(
        "secret-cluster-id",
        event_id="secret-event-id",
        event_at=1,
        value=0.5,
    )
    accumulator.finalize("secret-cluster-id", as_of=100)
    internal = repr(accumulator._records)
    assert "secret-cluster-id" not in internal
    assert "secret-event-id" not in internal
