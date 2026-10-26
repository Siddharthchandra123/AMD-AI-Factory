"""Independent tests: no ROCm machine or network connection is required."""
import asyncio
import time

from app.live_runtime import LiveNode, LiveRegistry
from app.simulator import VirtualCluster
from app.scheduler import Candidate, select_node


def sample_gpu(num, used=70, utilization=55):
    return {'id': str(num), 'model': 'AMD Instinct MI300X', 'memory_total_gb': 192,
            'memory_used_gb': used, 'utilization_percent': utilization,
            'temperature_c': 63, 'power_watts': 400, 'source': 'amd_smi'}


def make_node():
    return LiveNode('agent/tp8', 'http://agent:9877', 'agent', 'tp8',
        [str(x) for x in range(8)], ['model-name'], True, 3, 0,
        [sample_gpu(x) for x in range(8)], time.monotonic())


def test_tp8_worker_is_one_schedulable_node():
    n = make_node()
    registry = LiveRegistry()
    registry.nodes = {n.id: n}
    assert len(registry.snapshots()) == 1
    assert len(registry.candidates('model-name', set())) == 1
    assert registry.snapshots()[0]['gpu_ids'] == [str(i) for i in range(8)]
    assert registry.snapshots()[0]['power_watts'] == 3200


def test_fresh_vs_stale_detection_fails_closed():
    n = make_node()
    n.sampled_at -= 60
    assert n.snapshot(time.monotonic())['health'] == 'stale'
    assert n.candidate(time.monotonic()) is None


def test_missing_amd_smi_values_not_invented():
    n = make_node()
    n.gpu_samples[1]['utilization_percent'] = None
    for sample in n.gpu_samples:
        sample['memory_total_gb'] = None
    result = n.snapshot(time.monotonic())
    assert result['memory_total_gb'] is None
    assert n.candidate(time.monotonic()) is None


def test_model_specific_routing_and_draining():
    n = make_node()
    reg = LiveRegistry()
    reg.nodes = {n.id: n}
    assert not reg.candidates('another-model', set())
    assert not reg.candidates('model-name', {n.id})
    assert reg.candidates('model-name', set())


def test_max_concurrency_limit_is_enforced():
    n = make_node()
    n.active.update({'a', 'b', 'c'})
    assert not n.candidate(time.monotonic()).can_accept(0)


def test_dynamic_simulator_scaling_and_safe_removal():
    sim = VirtualCluster(count=1)
    n = sim.add(total_memory_gb=64, max_concurrent_jobs=5)
    assert sim.snapshot()[1]['memory_total_gb'] == 64
    assert sim.snapshot()[1]['max_concurrent_jobs'] == 5
    assert sim.remove(n.id) is True
    assert len(sim.nodes) == 1
    assert sim.remove(sim.nodes[0].id) is False


def test_real_workers_are_live_not_static_capacity():
    n = make_node()
    before = n.candidate(time.monotonic())
    n.gpu_samples[0]['utilization_percent'] = 98
    after = n.candidate(time.monotonic())
    assert before.gpu_utilization == 55
    assert after.gpu_utilization == 98


def test_auto_scheduler_policy_supported():
    candidates = [Candidate('gpu0', 192, 16, 10, 0), Candidate('gpu1', 192, 16, 80, 0)]
    selected, _ = select_node(candidates, 1, 'auto')
    assert selected.id == 'gpu0'


def test_thermal_policy_does_not_fabricate_missing_sensor_values():
    n = make_node()
    for gpu in n.gpu_samples:
        gpu['temperature_c'] = None
    reg = LiveRegistry()
    reg.nodes = {n.id: n}
    assert not reg.candidates('model-name', set(), 'thermal_aware')
    assert reg.candidates('model-name', set(), 'least_connections')
