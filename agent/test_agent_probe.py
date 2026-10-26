"""Sensor parser test using a fake amdsmi module; no real GPU measurement implied."""
import sys
from types import SimpleNamespace
from amdsmi_probe import probe_gpus


def test_probe_preserves_real_sensor_units_and_missing_values(monkeypatch):
    fake = SimpleNamespace(
        amdsmi_init=lambda: None,
        amdsmi_shut_down=lambda: None,
        amdsmi_get_processor_handles=lambda: ['gpu0'],
        amdsmi_get_gpu_vram_usage=lambda h: {'vram_total': 192 * 2**30, 'vram_used': 16 * 2**30},
        amdsmi_get_gpu_activity=lambda h: {'gfx_activity': 63},
        amdsmi_get_gpu_metrics_info=lambda h: {'temperature_edge': 61},
        amdsmi_get_power_info=lambda h: {'current_socket_power': 410},
        amdsmi_get_gpu_asic_info=lambda h: {'market_name': 'AMD Instinct MI300X'},
    )
    monkeypatch.setitem(sys.modules, 'amdsmi', fake)
    result = probe_gpus()
    assert len(result) == 1
    assert result[0]['memory_total_gb'] == 192
    assert result[0]['memory_used_gb'] == 16
    assert result[0]['utilization_percent'] == 63
    assert result[0]['power_watts'] == 410
