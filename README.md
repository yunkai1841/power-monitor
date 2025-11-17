# Power Monitor (Intel CPU + NVIDIA GPU)

A tool to monitor power consumption of Intel CPUs and NVIDIA GPUs.
It continuously collects CPU power via Intel RAPL, GPU power/utilization via NVIDIA NVML,
and CPU/GPU/memory metrics of arbitrary processes, saving the data in CSV or JSONL formats.
It can also run external commands while measuring.

## Features
- Monitors CPU power (W) per Intel RAPL domain
- Monitors GPU power (W) and utilization (%) via NVIDIA NVML
- Monitors CPU/GPU/memory usage of specified processes
- Supports CSV and JSONL output formats
- Can run external commands while measuring
- Configurable sampling interval

## Installation
```bash
python -m venv .venv
source .venv/bin/activate
pip install .
```

or using uv:
```bash
uv sync
```

## Usage
```bash
python monitor.py --interval 1.0
```

## Important: Privileges Required for CPU Power Measurement
Measuring CPU power using Intel RAPL requires read permissions to files under `/sys/class/powercap/`. Typically, these files are only readable by the root user.

To measure CPU power, use one of the following methods:

**Method 1: Run with sudo (recommended)**
```bash
sudo python monitor.py --interval 1.0
```

**Method 2: Temporarily change permissions**
```bash
sudo chmod +r /sys/class/powercap/intel-rapl:*/energy_uj
sudo chmod +r /sys/class/powercap/intel-rapl:*/intel-rapl:*/energy_uj
python monitor.py --interval 1.0
```
Note: You will need to change the permissions again after a system reboot.

If you only want to measure GPU, you can run it with normal user privileges:
```bash
python monitor.py --no-cpu
```
