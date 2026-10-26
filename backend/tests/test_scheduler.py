from app.scheduler import Candidate, estimated_simulation_seconds, select_node
from app.simulator import VirtualCluster


def node(name, gpu=10, used=6, jobs=0):
    return Candidate(name, 192, used, gpu, jobs)


def test_least_loaded():
    picked, cursor = select_node([node("A", 30), node("B", 5)], 18, "least_loaded")
    assert picked.id == "B" and cursor == 0


def test_round_robin_rotates():
    nodes = [node("A"), node("B"), node("C")]
    x, cursor = select_node(nodes, 18, "round_robin")
    y, cursor = select_node(nodes, 18, "round_robin", cursor)
    assert (x.id, y.id) == ("A", "B")


def test_scheduler_respects_hbm_and_concurrency():
    nodes = [node("A", used=180), node("B", jobs=2), node("C")]
    picked, _ = select_node(nodes, 18, "least_loaded")
    assert picked.id == "C"


def test_no_eligible_gpu():
    picked, _ = select_node([node("A", used=188)], 20, "round_robin")
    assert picked is None


def test_all_telemetry_is_explicitly_simulated():
    cluster = VirtualCluster(count=2)
    samples = cluster.snapshot()
    assert len(samples) == 2
    assert all(s["source"] == "simulation" and "SIMULATED" in s["model"] for s in samples)


def test_synthetic_duration_positive_and_bounded():
    assert 3 <= estimated_simulation_seconds(200, 100, 18) <= 40
