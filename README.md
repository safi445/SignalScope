# SignalScope (Prototype)

Passive wireless **metadata** awareness system (Wi‑Fi + BLE), built to run:

- **On Windows/macOS/Linux** in **mock mode** (no hardware scanning required)
- **On Android (Termux)** using Termux:API commands when available

## What it does (MVP)

- Collects **Wi‑Fi scan** and **BLE scan** *metadata* (no sniffing, no decryption)
- Tracks devices over time (first/last seen, RSSI history)
- Computes a **suspicion score** + category (Normal / Interesting / Suspicious)
- Stores history in **SQLite**
- Serves a local API + a simple **radar dashboard**
- Generates a **debrief summary**

## Run (Windows mock mode)

1) Create venv and install deps:

```bash
python -m venv .venv
.venv\\Scripts\\activate
pip install -r requirements.txt
```

2) Start server:

```bash
python -m app
```

3) Open dashboard:

- `http://127.0.0.1:5000/`

## Run on Android (Termux)

Install:

- `pkg update && pkg install python`
- Termux:API app + `pkg install termux-api`

Then (inside project directory):

```bash
pip install -r requirements.txt
python -m app
```

The collectors will auto-detect Termux commands; if unavailable, it falls back to mock mode.

## API endpoints

- `GET /scan` → latest scan snapshot
- `GET /devices` → tracked devices (with scores)
- `GET /suspicious` → score >= 60
- `GET /history?device_id=...` → observations for a device
- `GET /debrief?minutes=5` → summary report

## Notes / constraints

- Passive metadata only: SSID/BSSID/RSSI/channel (Wi‑Fi), address/name/RSSI (BLE)
- RSSI distance is approximate and varies by hardware/environment

## Optional: real vendor lookup (OUI database)

By default the app has a tiny built-in vendor map. For **real manufacturer names**, download the IEEE OUI database:

```bash
python scripts/update_oui.py
```

This saves `data/oui.csv`. You can also point to a custom file:

- Set env var `RECON_OUI_DB` to the path of your OUI CSV.

