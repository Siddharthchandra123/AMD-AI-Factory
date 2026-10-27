"""Physical GPU telemetry via AMD SMI Python bindings on a ROCm Linux host.

This module never manufactures GPU readings. Missing sensors are represented as None.
AMD SMI typically ships with supported ROCm installations (not Windows CPU hosts).
"""
from __future__ import annotations
from typing import Any


def _value(fn, default=None):
    try:
        return fn()
    except Exception:
        return default


def _number(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def probe_gpus() -> list[dict[str, Any]]:
    import amdsmi  # Import only on the AMD GPU host.

    amdsmi.amdsmi_init()
    try:
        result = []
        handles = amdsmi.amdsmi_get_processor_handles()
        for idx, handle in enumerate(handles):
            vram = _value(lambda: amdsmi.amdsmi_get_gpu_vram_usage(handle), {}) or {}
            activity = _value(lambda: amdsmi.amdsmi_get_gpu_activity(handle), {}) or {}
            metrics = _value(lambda: amdsmi.amdsmi_get_gpu_metrics_info(handle), {}) or {}
            power = _value(lambda: amdsmi.amdsmi_get_power_info(handle), {}) or {}
            asic = _value(lambda: amdsmi.amdsmi_get_gpu_asic_info(handle), {}) or {}
            used = _number(vram.get('vram_used'))
            total = _number(vram.get('vram_total'))
            util = _number(activity.get('gfx_activity'))
            if util is None:
                util = _number(metrics.get('average_gfx_activity'))
            temp = _number(metrics.get('temperature_edge'))
            if temp is None:
                temp = _number(metrics.get('temperature_hotspot'))
            watts = _number(power.get('current_socket_power'))
            if watts is None:
                watts = _number(power.get('average_socket_power'))
            if watts is None:
                watts = _number(power.get('socket_power'))
            result.append({
                'id': str(idx),
                'model': str(asic.get('market_name') or asic.get('asic_name') or 'AMD GPU'),
                'memory_total_gb': round(total / 1024, 3) if total is not None else None,
                'memory_used_gb': round(used / 1024, 3) if used is not None else None,
                'utilization_percent': util,
                'temperature_c': temp,
                'power_watts': watts,
                'source': 'amd_smi',
            })
        return result
    finally:
        amdsmi.amdsmi_shut_down()
