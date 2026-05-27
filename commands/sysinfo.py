"""
commands/sysinfo.py  –  мониторинг системы (CPU, RAM, GPU)

Зависимости:
    pip install psutil nvidia-ml-py

Команды:
    «системная информация» / «покажи систему» / «стат» / «температура»
"""

import logging
import threading

logger = logging.getLogger("worker.commands.sysinfo")


# ── CPU ───────────────────────────────────────────────────────────────────────

def get_cpu_usage() -> float:
    try:
        import psutil
        return psutil.cpu_percent(interval=0.1)
    except Exception as e:
        logger.error(f"CPU usage: {e}")
        return 0.0


def get_cpu_temp() -> float | None:
    """
    На Windows пробуем несколько источников:
    1. OpenHardwareMonitor WMI (если запущен)
    2. ThermalZone WMI
    3. psutil.sensors_temperatures()
    """
    try:
        import wmi
    except Exception as e:
        logger.debug(f"CPU temp import wmi error: {e}")
        wmi = None

    if wmi is not None:
        try:
            w = wmi.WMI(namespace="root\\OpenHardwareMonitor")
            for s in w.Sensor():
                if s.SensorType == "Temperature" and "CPU" in s.Name:
                    temp = float(s.Value)
                    logger.debug(f"CPU temp (OpenHardwareMonitor): {temp}°C")
                    return temp
        except Exception as e:
            logger.debug(f"CPU temp OpenHardwareMonitor error: {e}")

        try:
            c = wmi.WMI()
            for zone in c.Win32_PerfFormattedData_Counters_ThermalZoneInformation():
                name = getattr(zone, "Name", "") or ""
                temp = getattr(zone, "Temperature", None)
                if temp is None:
                    continue
                temp = float(temp)
                if temp > 150:
                    temp = temp / 10.0
                if "cpu" in name.lower() or name.lower().startswith("\\_tz"):
                    logger.debug(f"CPU temp (ThermalZone): {temp}°C from {name}")
                    return temp
            if c.Win32_PerfFormattedData_Counters_ThermalZoneInformation():
                zone = c.Win32_PerfFormattedData_Counters_ThermalZoneInformation()[0]
                temp = getattr(zone, "Temperature", None)
                if temp is not None:
                    temp = float(temp)
                    if temp > 150:
                        temp = temp / 10.0
                    logger.debug(f"CPU temp (ThermalZone fallback): {temp}°C")
                    return temp
        except Exception as e:
            logger.debug(f"CPU temp ThermalZone error: {e}")

    try:
        import psutil
        temps = psutil.sensors_temperatures()
        if temps:
            for sensor_list in temps.values():
                for entry in sensor_list:
                    if entry.current and entry.current > 0:
                        logger.debug(f"CPU temp (psutil): {entry.current}°C")
                        return float(entry.current)
    except Exception as e:
        logger.debug(f"CPU temp psutil error: {e}")

    return None


# ── RAM ───────────────────────────────────────────────────────────────────────

def get_ram_usage() -> dict:
    try:
        import psutil
        m = psutil.virtual_memory()
        return {
            "used_gb":  round(m.used  / 1024**3, 1),
            "total_gb": round(m.total / 1024**3, 1),
            "percent":  round(m.percent, 1),
        }
    except Exception as e:
        logger.error(f"RAM usage: {e}")
        return {"used_gb": 0.0, "total_gb": 0.0, "percent": 0.0}


# ── GPU ───────────────────────────────────────────────────────────────────────

def _get_gpu_name_wmi() -> str | None:
    try:
        import wmi
        c = wmi.WMI()
        video = c.Win32_VideoController()
        if video:
            name = getattr(video[0], "Name", None)
            if name:
                return str(name)
    except Exception as e:
        logger.debug(f"GPU name WMI error: {e}")
    return None


def _get_gpu_load_wmi() -> float | None:
    try:
        import wmi
        c = wmi.WMI()
        engines = c.Win32_PerfFormattedData_GPUPerformanceCounters_GPUEngine()
        values = []
        for engine in engines:
            val = getattr(engine, "UtilizationPercentage", None)
            if val is None:
                continue
            try:
                v = int(val)
            except Exception:
                continue
            values.append(v)
        if values:
            load = float(max(values))
            logger.debug(f"GPU load WMI: {load}%")
            return load
    except Exception as e:
        logger.debug(f"GPU load WMI error: {e}")
    return None


def _get_ohm_gpu_temps() -> tuple[float | None, float | None]:
    try:
        import wmi
        w = wmi.WMI(namespace="root\\OpenHardwareMonitor")
        temp = None
        hotspot = None
        for s in w.Sensor():
            if s.SensorType != "Temperature":
                continue
            name = (s.Name or "").lower()
            if not any(key in name for key in ("gpu", "hot spot", "hotspot", "edge", "junction", "core")):
                continue
            try:
                value = float(s.Value)
            except Exception:
                continue
            if "hot" in name and "spot" in name:
                hotspot = value
            elif temp is None:
                temp = value
        if temp is not None or hotspot is not None:
            logger.debug(f"GPU temps OHM: temp={temp}, hotspot={hotspot}")
            return temp, hotspot
    except Exception as e:
        logger.debug(f"GPU temps OHM error: {e}")
    return None, None


def _get_gpu_temp_psutil() -> tuple[float | None, float | None]:
    try:
        import psutil
        if not hasattr(psutil, "sensors_temperatures"):
            return None, None

        temps = psutil.sensors_temperatures()
        if not temps:
            return None, None

        temp = None
        hotspot = None
        for sensor_name, entries in temps.items():
            for entry in entries:
                if not entry.current or entry.current <= 0:
                    continue
                label = (entry.label or "").lower()
                name = (sensor_name or "").lower()
                if not any(key in label or key in name for key in ("gpu", "hot", "hotspot", "edge", "junction", "core")):
                    continue
                if "hot" in label or "hot" in name:
                    hotspot = float(entry.current)
                elif temp is None:
                    temp = float(entry.current)
        if temp is None and hotspot is not None:
            temp = hotspot
        if temp is not None or hotspot is not None:
            logger.debug(f"GPU temps psutil: temp={temp}, hotspot={hotspot}")
        return temp, hotspot
    except Exception as e:
        logger.debug(f"GPU temp psutil error: {e}")
    return None, None


def get_gpu_info() -> dict:
    result = {
        "name": "GPU", "load": None,
        "temp": None,  "hotspot": None,
        "vram_used": None, "vram_total": None,
    }

    gpu_name = _get_gpu_name_wmi()
    if gpu_name:
        result["name"] = gpu_name

    # NVIDIA support
    is_amd = isinstance(gpu_name, str) and "amd" in gpu_name.lower()
    if not is_amd:
        try:
            from pynvml import (
                nvmlInit, nvmlShutdown, nvmlDeviceGetHandleByIndex,
                nvmlDeviceGetName, nvmlDeviceGetUtilizationRates,
                nvmlDeviceGetTemperature, nvmlDeviceGetMemoryInfo,
                NVML_TEMPERATURE_GPU,
            )
            nvmlInit()
            try:
                h = nvmlDeviceGetHandleByIndex(0)
                name = nvmlDeviceGetName(h)
                result["name"] = name.decode() if isinstance(name, bytes) else str(name)
                util = nvmlDeviceGetUtilizationRates(h)
                result["load"] = util.gpu
                result["temp"] = nvmlDeviceGetTemperature(h, NVML_TEMPERATURE_GPU)
                try:
                    hs = nvmlDeviceGetTemperature(h, 1)
                    if hs and hs > 0 and hs != result["temp"]:
                        result["hotspot"] = hs
                except Exception as e:
                    logger.debug(f"GPU hotspot error: {e}")
                mem = nvmlDeviceGetMemoryInfo(h)
                result["vram_used"]  = round(mem.used  / 1024**2)
                result["vram_total"] = round(mem.total / 1024**2)
                logger.debug(f"GPU NVML: {result}")
                return result
            finally:
                nvmlShutdown()
        except Exception as e:
            logger.debug(f"GPU NVML error: {e}")

    # GPUtil fallback
    try:
        import GPUtil
        gpus = GPUtil.getGPUs()
        if gpus:
            g = gpus[0]
            result["name"] = g.name
            result["load"] = round(g.load * 100)
            result["temp"] = g.temperature
            result["vram_used"] = round(g.memoryUsed)
            result["vram_total"] = round(g.memoryTotal)
            logger.debug(f"GPU GPUtil: {result}")
            return result
    except Exception as e:
        logger.debug(f"GPU GPUtil error: {e}")

    # psutil sensor fallback
    try:
        temp, hotspot = _get_gpu_temp_psutil()
        if temp is not None:
            result["temp"] = temp
        if hotspot is not None and hotspot != result.get("temp"):
            result["hotspot"] = hotspot
        if temp is not None or hotspot is not None:
            logger.debug(f"GPU psutil: {result}")
            return result
    except Exception as e:
        logger.debug(f"GPU psutil sensor error: {e}")

    # OpenHardwareMonitor fallback
    try:
        temp, hotspot = _get_ohm_gpu_temps()
        if temp is not None:
            result["temp"] = temp
        if hotspot is not None and hotspot != result.get("temp"):
            result["hotspot"] = hotspot
        if temp is not None or hotspot is not None:
            logger.debug(f"GPU OHM: {result}")
            return result
    except Exception as e:
        logger.debug(f"GPU OHM error: {e}")

    # AMD / other fallback via WMI
    # Note: AMD RX cards usually cannot expose temperature through NVML/GPUtil.
    # For RX 6000-series, pyadl / ADL or an external sensor provider such as
    # HWiNFO, GPU-Z, or OpenHardwareMonitor is required to read temperatures.
    try:
        load = _get_gpu_load_wmi()
        if load is not None:
            result["load"] = load
    except Exception:
        pass

    # Try AMD ADL (pyadl) to get temperatures (hotspot / GPU).
    try:
        # HWiNFO shared-memory heuristic fallback (if HWiNFO sensors are running with shared memory)
        def _get_hwinfo_shared_temps() -> tuple[float | None, float | None]:
            try:
                import ctypes
                from ctypes import wintypes
            except Exception:
                return None, None

            names = [
                "HWiNFO_SENS_SM2", "HWiNFO_SENS_SM1", "HWiNFO_SENSORS",
                "HWiNFO64_SENS_SM2", "HWiNFO64_SENS_SM1", "HWiNFO64_SENSORS",
            ]

            OPEN_EXISTING = 3
            FILE_MAP_READ = 0x0004
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

            for nm in names:
                try:
                    hmap = kernel32.OpenFileMappingW(FILE_MAP_READ, False, nm)
                    if not hmap:
                        continue
                    buf = kernel32.MapViewOfFile(hmap, FILE_MAP_READ, 0, 0, 65536)
                    if not buf:
                        kernel32.CloseHandle(hmap)
                        continue
                    # read bytes
                    data = (ctypes.c_char * 65536).from_address(buf)
                    raw = bytes(data)
                    try:
                        txt = raw.decode('utf-16le', errors='ignore')
                    except Exception:
                        try:
                            txt = raw.decode('utf-8', errors='ignore')
                        except Exception:
                            txt = raw.decode('latin1', errors='ignore')
                    kernel32.UnmapViewOfFile(buf)
                    kernel32.CloseHandle(hmap)

                    import re
                    # search for hotspot first
                    hs_match = re.search(r'(?i)hot[\s_-]*spot[^0-9\-\n\r]{0,30}([0-9]{1,2}(?:[\.,][0-9])?)', txt)
                    gpu_match = re.search(r'(?i)gpu[^0-9\-\n\r]{0,30}([0-9]{1,2}(?:[\.,][0-9])?)', txt)
                    # sometimes temperature appears as number followed by C
                    if not gpu_match:
                        g2 = re.search(r'([0-9]{2}(?:[\.,][0-9])?)\s?°\s?C', txt)
                        if g2:
                            gpu_match = g2

                    hs = None
                    gpu_t = None
                    if gpu_match:
                        try:
                            gpu_t = float(gpu_match.group(1).replace(',', '.'))
                        except Exception:
                            gpu_t = None
                    if hs_match:
                        try:
                            hs = float(hs_match.group(1).replace(',', '.'))
                        except Exception:
                            hs = None
                    if gpu_t is not None or hs is not None:
                        return gpu_t, hs
                except Exception:
                    continue
            return None, None

        def _get_amd_adl_temps() -> tuple[float | None, float | None]:
            try:
                import ctypes
                from ctypes import byref
                import pyadl.adl_api as adl_api
                import pyadl.adl_structures as adl_structures
            except Exception:
                return None, None

            temps: list[int] = []

            # ADL2 attempt
            ctx = adl_structures.ADL_CONTEXT_HANDLE()
            rc = adl_api.ADL2_Main_Control_Create(adl_api.ADL_Main_Memory_Alloc, 1, byref(ctx))
            if rc == 0:
                try:
                    n = ctypes.c_int()
                    if adl_api.ADL2_Adapter_NumberOfAdapters_Get(ctx, byref(n)) == 0 and n.value > 0:
                        adapters = (adl_structures.AdapterInfo * n.value)()
                        for a in adapters:
                            a.iSize = ctypes.sizeof(adl_structures.AdapterInfo)
                        # pass size in bytes as required by some ADL implementations
                        try:
                            adl_api.ADL2_Adapter_AdapterInfo_Get(ctx, adapters, ctypes.sizeof(adapters))
                        except Exception:
                            # fallback to count if bytes signature fails
                            adl_api.ADL2_Adapter_AdapterInfo_Get(ctx, adapters, n.value)

                        for ad in adapters:
                            # only consider present adapters
                            if getattr(ad, 'iPresent', 1) == 0:
                                continue
                            for idx in range(0, 8):
                                t = adl_structures.ADLTemperature()
                                t.iSize = ctypes.sizeof(adl_structures.ADLTemperature)
                                rc2 = adl_api.ADL2_Overdrive5_Temperature_Get(ctx, ad.iAdapterIndex, idx, byref(t))
                                if rc2 == 0 and getattr(t, 'iTemperature', 0):
                                    temps.append(int(t.iTemperature))
                finally:
                    try:
                        adl_api.ADL2_Main_Control_Destroy(ctx)
                    except Exception:
                        pass

            # ADL (legacy) attempt
            try:
                ctx2 = None
                rc = adl_api.ADL_Main_Control_Create(adl_api.ADL_Main_Memory_Alloc, 1)
                if rc == 0:
                    try:
                        n = ctypes.c_int()
                        if adl_api.ADL_Adapter_NumberOfAdapters_Get(byref(n)) == 0 and n.value > 0:
                            adapters = (adl_structures.AdapterInfo * n.value)()
                            for a in adapters:
                                a.iSize = ctypes.sizeof(adl_structures.AdapterInfo)
                            try:
                                adl_api.ADL_Adapter_AdapterInfo_Get(adapters, ctypes.sizeof(adapters))
                            except Exception:
                                adl_api.ADL_Adapter_AdapterInfo_Get(adapters, n.value)
                            for ad in adapters:
                                if getattr(ad, 'iPresent', 1) == 0:
                                    continue
                                for idx in range(0, 8):
                                    t = adl_structures.ADLTemperature()
                                    t.iSize = ctypes.sizeof(adl_structures.ADLTemperature)
                                    try:
                                        rc2 = adl_api.ADL_Overdrive5_Temperature_Get(ad.iAdapterIndex, idx, byref(t))
                                    except Exception:
                                        rc2 = -1
                                    if rc2 == 0 and getattr(t, 'iTemperature', 0):
                                        temps.append(int(t.iTemperature))
                    finally:
                        try:
                            adl_api.ADL_Main_Control_Destroy()
                        except Exception:
                            pass
            except Exception:
                pass

            if not temps:
                return None, None
            # Heuristic: hotspot is the max temperature, gpu temp is the min (or same if single)
            hotspot = float(max(temps))
            gpu_temp = float(min(temps)) if len(temps) > 1 else float(temps[0])
            return gpu_temp, hotspot

        t, hs = _get_amd_adl_temps()
        # if ADL didn't produce temps, try HWiNFO shared memory heuristic
        if t is None and hs is None:
            try:
                ht, hhs = _get_hwinfo_shared_temps()
                if ht is not None:
                    t = ht
                if hhs is not None:
                    hs = hhs
            except Exception:
                pass

        # GPU-Z shared-memory heuristic fallback (if GPU-Z is running with shared memory)
        if t is None and hs is None:
            def _get_gpuz_shared_temps() -> tuple[float | None, float | None]:
                try:
                    import ctypes
                except Exception:
                    return None, None
                names = [
                    "GPUZ_SENSORS", "GPUZ_SM", "GPUZ_SHARED", "GPUZ", "GPU-Z", "GPUZ_SENS",
                ]
                FILE_MAP_READ = 0x0004
                kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
                for nm in names:
                    try:
                        hmap = kernel32.OpenFileMappingW(FILE_MAP_READ, False, nm)
                        if not hmap:
                            continue
                        buf = kernel32.MapViewOfFile(hmap, FILE_MAP_READ, 0, 0, 65536)
                        if not buf:
                            kernel32.CloseHandle(hmap)
                            continue
                        data = (ctypes.c_char * 65536).from_address(buf)
                        raw = bytes(data)
                        try:
                            txt = raw.decode('utf-16le', errors='ignore')
                        except Exception:
                            try:
                                txt = raw.decode('utf-8', errors='ignore')
                            except Exception:
                                txt = raw.decode('latin1', errors='ignore')
                        kernel32.UnmapViewOfFile(buf)
                        kernel32.CloseHandle(hmap)
                        import re
                        hs_match = re.search(r'(?i)hot[\s_-]*spot[^0-9\-\n\r]{0,30}([0-9]{1,2}(?:[\.,][0-9])?)', txt)
                        gpu_match = re.search(r'(?i)gpu[^0-9\-\n\r]{0,30}([0-9]{1,2}(?:[\.,][0-9])?)', txt)
                        if not gpu_match:
                            g2 = re.search(r'([0-9]{2}(?:[\.,][0-9])?)\s?°\s?C', txt)
                            if g2:
                                gpu_match = g2
                        hs = None
                        gpu_t = None
                        if gpu_match:
                            try:
                                gpu_t = float(gpu_match.group(1).replace(',', '.'))
                            except Exception:
                                gpu_t = None
                        if hs_match:
                            try:
                                hs = float(hs_match.group(1).replace(',', '.'))
                            except Exception:
                                hs = None
                        if gpu_t is not None or hs is not None:
                            return gpu_t, hs
                    except Exception:
                        continue
                return None, None

            try:
                gt, ghs = _get_gpuz_shared_temps()
                if gt is not None:
                    t = gt
                if ghs is not None:
                    hs = ghs
            except Exception:
                pass

        if t is not None:
            result["temp"] = t
        if hs is not None and hs != result.get("temp"):
            result["hotspot"] = hs
    except Exception:
        pass

    logger.debug(f"GPU fallback: {result}")
    return result


# ── Всё вместе ────────────────────────────────────────────────────────────────

def get_all_stats() -> dict:
    return {
        "cpu_pct":  get_cpu_usage(),
        "cpu_temp": get_cpu_temp(),
        "ram":      get_ram_usage(),
        "gpu":      get_gpu_info(),
    }


# ── Голосовая команда отключена ────────────────────────────────────────────
# Системная информация теперь выводится статически в HWMonitorWidget
# (см. ui/app.py > HWMonitorWidget)