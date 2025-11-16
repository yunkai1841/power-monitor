# Power Monitor (Intel CPU + NVIDIA GPU)

Linux上でIntel RAPLによるCPU電力、NVIDIA NVMLによるGPU電力/利用率、および任意プロセスのCPU/GPU/メモリ指標を継続的に取得し、CSVまたはJSONLで保存するツールです。外部コマンドを実行しながら同時に測定できます。

## 特徴
- Intel RAPLドメイン毎の平均電力 (W)
- NVIDIA GPU: 電力 (W), GPU利用率%, メモリ利用率%, 使用/総メモリ(MB)
- 対象プロセス: CPU使用率%, RSSメモリ(MB), (対応GPU上の) プロセスメモリ使用量(MB)
- サンプリング間隔を任意指定 (`--interval`)
- 総測定時間を指定可能 (`--duration` 0で無限)
- CSV / JSON Lines 出力 (`--format`)
- 標準出力またはファイルへ継続書き込み
- 外部コマンドをラップしてその稼働期間のみ測定 (`-- command ...`)
- 既存PID指定で監視 (`--pid <PID>`)
- CPU/GPU計測を個別無効化 (`--no-cpu`, `--no-gpu`)

## 依存関係のインストール
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 使い方 (基本例)
CPU+GPUを1秒間隔で無限監視 (Ctrl-Cで停止):
```bash
python monitor.py --interval 1.0
```

30秒間監視してCSV保存:
```bash
python monitor.py --interval 0.5 --duration 30 --output power.csv --format csv
```

外部プログラム(例: `./my_app --opt`)実行中のみ監視しJSONL出力:
```bash
python monitor.py --interval 0.5 --output run.jsonl --format jsonl -- -- ./my_app --opt
```
(`--` の後が対象コマンドです)

既存PIDを監視 (GPU無し):
```bash
python monitor.py --interval 1 --pid 12345 --no-gpu
```

CPUのみ:
```bash
python monitor.py --no-gpu
```

GPUのみ:
```bash
python monitor.py --no-cpu
```

## 出力列 (CSV例)
最初の行はヘッダ。代表例:
```
timestamp,cpu_package-0_power_w,gpu0_power_w,gpu0_gpu_util_percent,gpu0_mem_util_percent,gpu0_mem_used_mb,gpu0_mem_total_mb,proc_cpu_percent,proc_mem_rss_mb,gpu0_gpu_proc_mem_used_mb
```
利用可能なRAPLドメインやGPU数によって列は変動します。

## 注意点
- RAPL値は差分から平均電力を計算するため初回サンプルはNULL扱いで出力されません。
- NVMLが利用できない環境では `pynvml` がインポートできずGPU計測は自動無効化されます。
- プロセスCPU使用率は初回取得時は0に近い値になる場合があります。
- プロセスGPUメモリ使用量は利用可能なAPIで取得できた場合のみ出力されます。

## 拡張アイデア
- Prometheusエクスポートエンドポイント追加
- 平均/最大統計の集計
- RAID / NIC 等他デバイス電力対応

## ライセンス
(必要なら後で追加)
