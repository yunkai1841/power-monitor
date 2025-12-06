#!/usr/bin/env python3
import os
import time
import argparse
import csv
import json
import subprocess
import sys
from datetime import datetime
from typing import List, Dict, Optional, Any

import psutil
from loguru import logger

try:
    from pynvml import (
        nvmlInit,
        nvmlShutdown,
        nvmlDeviceGetCount,
        nvmlDeviceGetHandleByIndex,
        nvmlDeviceGetPowerUsage,
        nvmlDeviceGetName,
        nvmlDeviceGetUtilizationRates,
        nvmlDeviceGetMemoryInfo,
        nvmlSystemGetDriverVersion,
        nvmlDeviceGetGraphicsRunningProcesses_v3,
        nvmlDeviceGetClockInfo,
        NVML_CLOCK_GRAPHICS,
    )

    NVML_AVAILABLE = True
except Exception:
    NVML_AVAILABLE = False

RAPL_PATH = "/sys/class/powercap"


class RaplDomain:
    def __init__(self, path: str, name: str):
        self.path = path
        self.name = name
        self.last_energy_uj: Optional[int] = None
        self.last_timestamp: Optional[float] = None

    def read_energy_uj(self) -> Optional[int]:
        try:
            with open(os.path.join(self.path, "energy_uj"), "r") as f:
                return int(f.read().strip())
        except PermissionError:
            return None
        except Exception:
            return None

    def sample_power_w(self) -> Optional[float]:
        energy = self.read_energy_uj()
        now = time.time()
        if energy is None:
            return None
        if self.last_energy_uj is None:
            self.last_energy_uj = energy
            self.last_timestamp = now
            return None
        delta_e = energy - self.last_energy_uj
        delta_t = now - self.last_timestamp if self.last_timestamp else 0
        self.last_energy_uj = energy
        self.last_timestamp = now
        if delta_t <= 0:
            return None
        return (delta_e / 1_000_000.0) / delta_t


def discover_rapl_domains() -> List[RaplDomain]:
    domains: List[RaplDomain] = []
    if not os.path.isdir(RAPL_PATH):
        return domains
    for entry in os.listdir(RAPL_PATH):
        if entry.startswith("intel-rapl"):
            domain_path = os.path.join(RAPL_PATH, entry)
            name_file = os.path.join(domain_path, "name")
            name = entry
            if os.path.isfile(name_file):
                try:
                    with open(name_file, "r") as f:
                        name = f.read().strip()
                except Exception:
                    pass
            domains.append(RaplDomain(domain_path, name))
    return domains


class GpuDevice:
    def __init__(self, index: int, handle: Any, name: str):
        self.index = index
        self.handle = handle
        self.name = name


def init_nvml_devices() -> List[GpuDevice]:
    devices: List[GpuDevice] = []
    if not NVML_AVAILABLE:
        return devices
    try:
        nvmlInit()
        count = nvmlDeviceGetCount()
        for i in range(count):
            h = nvmlDeviceGetHandleByIndex(i)
            name = (
                nvmlDeviceGetName(h).decode("utf-8")
                if isinstance(nvmlDeviceGetName(h), bytes)
                else nvmlDeviceGetName(h)
            )
            devices.append(GpuDevice(i, h, name))
    except Exception:
        return []
    return devices


def sample_gpu_power(dev: GpuDevice) -> Optional[float]:
    try:
        return nvmlDeviceGetPowerUsage(dev.handle) / 1000.0
    except Exception:
        return None


def sample_gpu_util(dev: GpuDevice) -> Dict[str, Any]:
    data: Dict[str, Any] = {}
    try:
        util = nvmlDeviceGetUtilizationRates(dev.handle)
        mem = nvmlDeviceGetMemoryInfo(dev.handle)
        data["gpu_util_percent"] = util.gpu
        data["mem_util_percent"] = util.memory
        data["mem_used_mb"] = mem.used / (1024 * 1024)
        data["mem_total_mb"] = mem.total / (1024 * 1024)
        return data
    except Exception:
        return data


def sample_gpu_process_util(
    dev: GpuDevice, target_pid: int
) -> Optional[Dict[str, Any]]:
    try:
        procs = nvmlDeviceGetGraphicsRunningProcesses_v3(dev.handle)
        for p in procs:
            if p.pid == target_pid:
                return {"gpu_proc_mem_used_mb": p.usedGpuMemory / (1024 * 1024)}
    except Exception:
        return None
    return None


def sample_gpu_frequency(dev: GpuDevice) -> Optional[int]:
    try:
        freq = nvmlDeviceGetClockInfo(dev.handle, NVML_CLOCK_GRAPHICS)
        return freq
    except Exception:
        return None


def format_row(row: Dict[str, Any], fmt: str) -> str:
    if fmt == "jsonl":
        return json.dumps(row, ensure_ascii=False)
    return ",".join(str(row.get(k, "")) for k in row.keys())


def write_csv_header(writer: csv.writer, keys: List[str]):
    writer.writerow(keys)


def run_command(command: List[str]) -> subprocess.Popen:
    return subprocess.Popen(command)


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Intel CPU (RAPL) + NVIDIA GPU Power Monitor"
    )
    p.add_argument(
        "--interval", type=float, default=1.0, help="Sampling interval in seconds"
    )
    p.add_argument(
        "--duration",
        type=float,
        default=0.0,
        help="Total monitoring duration in seconds (0=infinite)",
    )
    p.add_argument(
        "--output", type=str, default="", help="Output file path (empty for stdout)"
    )
    p.add_argument(
        "--format", choices=["csv", "jsonl"], default="csv", help="Output format"
    )
    p.add_argument(
        "--command",
        type=str,
        nargs=argparse.REMAINDER,
        help='External command to run while monitoring (specify after "--")',
    )
    p.add_argument(
        "--pid",
        type=int,
        default=0,
        help="Monitor existing process PID (when command is not specified)",
    )
    p.add_argument("--no-gpu", action="store_true", help="Disable GPU monitoring")
    p.add_argument(
        "--no-cpu", action="store_true", help="Disable CPU (RAPL) monitoring"
    )
    p.add_argument(
        "--log-level",
        default="INFO",
        choices=["TRACE", "DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR", "CRITICAL"],
        help="Log level",
    )
    return p


def main():
    parser = build_arg_parser()
    args = parser.parse_args()

    # Logger setup
    logger.remove()
    logger.add(sys.stderr, level=args.log_level, enqueue=True, colorize=True)
    logger.info("Start interval={:.3f}s format={}", args.interval, args.format)

    rapl_domains = discover_rapl_domains() if not args.no_cpu else []
    gpu_devices = init_nvml_devices() if (not args.no_gpu and NVML_AVAILABLE) else []

    target_process: Optional[psutil.Process] = None
    popen: Optional[subprocess.Popen] = None
    if args.command:
        # Strip leading -- if present in REMAINDER
        cmd = args.command
        if cmd and cmd[0] == "--":
            cmd = cmd[1:]
        if not cmd:
            logger.error("External command is not specified")
            return
        popen = run_command(cmd)
        target_process = psutil.Process(popen.pid)
    elif args.pid:
        try:
            target_process = psutil.Process(args.pid)
        except Exception:
            logger.error("Cannot access PID {}", args.pid)

    start_time = time.time()
    csv_writer = None
    file_handle = None
    keys_order: List[str] = []

    if args.output:
        mode = "w"
        file_handle = open(args.output, mode, buffering=1)
        if args.format == "csv":
            csv_writer = csv.writer(file_handle)

    if rapl_domains:
        accessible_domains = []
        for d in rapl_domains:
            e = d.read_energy_uj()
            if e is not None:
                accessible_domains.append(d)
        if accessible_domains:
            logger.info(
                "RAPL domains: {}", ", ".join(d.name for d in accessible_domains)
            )
            rapl_domains = accessible_domains
        else:
            logger.warning("RAPL domain detected but not readable (CPU power requires sudo)")
            logger.info("Example: sudo uv run monitor.py")
            rapl_domains = []
    if gpu_devices:
        try:
            drv = nvmlSystemGetDriverVersion().decode()
        except Exception:
            drv = "unknown"
        logger.info(
            "NVIDIA GPUs: {} (driver {})",
            ", ".join(f"{g.index}:{g.name}" for g in gpu_devices),
            drv,
        )
    elif not args.no_gpu and not NVML_AVAILABLE:
        logger.warning("pynvml is not available, GPU monitoring disabled")

    header_printed = False
    for d in rapl_domains:
        d.sample_power_w()

    try:
        while True:
            ts = time.time()
            elapsed = ts - start_time
            if args.duration and elapsed >= args.duration:
                break
            row: Dict[str, Any] = {
                "timestamp": ts,
                "datetime": datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S.%f")[
                    :-3
                ],
            }
            # System-wide CPU metrics
            row["cpu_usage_percent"] = round(psutil.cpu_percent(interval=None), 1)
            cpu_freq = psutil.cpu_freq()
            if cpu_freq is not None:
                row["cpu_freq_mhz"] = round(cpu_freq.current, 0)
            for d in rapl_domains:
                pw = d.sample_power_w()
                if pw is not None:
                    row[f"cpu_{d.name}_power_w"] = round(pw, 3)
            for g in gpu_devices:
                gpw = sample_gpu_power(g)
                if gpw is not None:
                    row[f"gpu{g.index}_power_w"] = round(gpw, 1)
                util = sample_gpu_util(g)
                for k, v in util.items():
                    row[f"gpu{g.index}_{k}"] = v
                gpu_freq = sample_gpu_frequency(g)
                if gpu_freq is not None:
                    row[f"gpu{g.index}_freq_mhz"] = gpu_freq
                if target_process:
                    proc_util = sample_gpu_process_util(g, target_process.pid)
                    if proc_util:
                        for k, v in proc_util.items():
                            row[f"gpu{g.index}_{k}"] = v
            if target_process:
                try:
                    cpu_pct = target_process.cpu_percent(interval=None)
                    mem_info = target_process.memory_info()
                    row["proc_cpu_percent"] = cpu_pct
                    row["proc_mem_rss_mb"] = mem_info.rss / (1024 * 1024)
                except Exception:
                    row["proc_ended"] = True
                    target_process = None
            if args.format == "csv":
                if not header_printed:
                    keys_order = list(row.keys())
                    if csv_writer:
                        write_csv_header(csv_writer, keys_order)
                    else:
                        print("#" + ",".join(keys_order))
                    header_printed = True
                line_values = [row.get(k, "") for k in keys_order]
                line = ",".join(str(v) for v in line_values)
                if file_handle:
                    file_handle.write(line + "\n")
                else:
                    print(line)
            else:  # jsonl
                if file_handle:
                    file_handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                else:
                    print(json.dumps(row, ensure_ascii=False))

            if popen and popen.poll() is not None and not target_process:
                # command finished
                break

            time.sleep(args.interval)
    except KeyboardInterrupt:
        pass
    finally:
        if file_handle:
            file_handle.close()
        if NVML_AVAILABLE:
            try:
                nvmlShutdown()
            except Exception:
                pass


if __name__ == "__main__":
    main()
