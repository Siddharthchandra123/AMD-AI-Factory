import random
import pytest
from app.scheduler import (
    Candidate, QueueCandidate, PLACEMENT_POLICIES, QUEUE_POLICIES,
    select_node, rank_queue,
)


def nodes():
    return [
        Candidate('a', 192, 100, 75, 1, temperature_c=75, power_watts=500,
                  performance_weight=1, cached_models=('model-7b',)),
        Candidate('b', 192, 30, 20, 0, temperature_c=45, power_watts=220,
                  performance_weight=2, cached_models=('model-8b',)),
        Candidate('c', 192, 70, 50, 1, temperature_c=60, power_watts=350,
                  performance_weight=1.5),
    ]


@pytest.mark.parametrize('policy', list(PLACEMENT_POLICIES))
def test_every_placement_returns_eligible_node(policy):
    selected, _ = select_node(nodes(), 18, policy, cursor=0, model='model-7b',
                              job_key='stable', rng=random.Random(11))
    assert selected in nodes()
    assert selected.can_accept(18)


@pytest.mark.parametrize('policy', list(PLACEMENT_POLICIES))
def test_never_allocates_full_or_oversubscribed_node(policy):
    candidates = [
        Candidate('full', 192, 190, 0, 0),
        Candidate('busy', 192, 6, 0, 2),
        Candidate('free', 192, 6, 0, 0),
    ]
    selected, _ = select_node(candidates, 18, policy, rng=random.Random(7))
    assert selected is not None and selected.id == 'free'


def test_no_node_eligible_all_policies():
    for policy in PLACEMENT_POLICIES:
        got, _ = select_node([Candidate('busy', 192, 3, 10, 2)], 18, policy)
        assert got is None


def test_known_specific_placement_decisions():
    assert select_node(nodes(), 18, 'least_loaded')[0].id == 'b'
    assert select_node(nodes(), 18, 'most_free_memory')[0].id == 'b'
    assert select_node(nodes(), 18, 'thermal_aware')[0].id == 'b'
    assert select_node(nodes(), 18, 'power_aware')[0].id == 'b'
    assert select_node(nodes(), 18, 'locality_aware', model='model-7b')[0].id == 'a'
    assert select_node(nodes(), 18, 'best_fit_memory')[0].id == 'a'


def test_rendezvous_hash_stable_and_random_seeded():
    r1, _ = select_node(nodes(), 18, 'rendezvous_hash', job_key='model-7b')
    r2, _ = select_node(nodes(), 18, 'rendezvous_hash', job_key='model-7b')
    assert r1.id == r2.id
    a, _ = select_node(nodes(), 18, 'random', rng=random.Random(42))
    b, _ = select_node(nodes(), 18, 'random', rng=random.Random(42))
    assert a == b


def queued():
    return [
        QueueCandidate('first', 'low', 100, 30, tenant='team-a'),
        QueueCandidate('urgent', 'high', 110, 12, tenant='team-b', deadline_timestamp=123),
        QueueCandidate('short', 'normal', 120, 3, tenant='team-c', deadline_timestamp=130),
    ]


@pytest.mark.parametrize('policy', list(QUEUE_POLICIES))
def test_every_queue_policy_returns_all_jobs(policy):
    ranked = rank_queue(queued(), policy, now_timestamp=150,
                        active_by_tenant={'team-a': 2, 'team-b': 0, 'team-c': 1}, rng=random.Random(42))
    assert len(ranked) == 3
    assert {j.id for j in ranked} == {'first', 'urgent', 'short'}


def test_classical_job_orderings():
    assert rank_queue(queued(), 'fcfs', now_timestamp=150)[0].id == 'first'
    assert rank_queue(queued(), 'priority_fifo', now_timestamp=150)[0].id == 'urgent'
    assert rank_queue(queued(), 'shortest_job_first', now_timestamp=150)[0].id == 'short'
    assert rank_queue(queued(), 'longest_job_first', now_timestamp=150)[0].id == 'first'
    assert rank_queue(queued(), 'earliest_deadline_first', now_timestamp=150)[0].id == 'urgent'
    assert rank_queue(queued(), 'fair_share', now_timestamp=150,
                      active_by_tenant={'team-a': 2, 'team-b': 0, 'team-c': 1})[0].id == 'urgent'


def test_priority_aging_prevents_low_priority_starvation():
    items = [QueueCandidate('old', 'low', 0, 5), QueueCandidate('new', 'high', 300, 5)]
    assert rank_queue(items, 'priority_aging', now_timestamp=300)[0].id == 'old'


def test_invalid_placements_and_queues_rejected():
    with pytest.raises(ValueError):
        select_node(nodes(), 18, 'not_a_policy')
    with pytest.raises(ValueError):
        rank_queue(queued(), 'not_a_policy', now_timestamp=20)
