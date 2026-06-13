# ZK Attendance Agent

On-premise attendance agent for ZKTeco devices. Collects attendance from SDK (LAN) and ADMS (WiFi push) devices and syncs to Biometric ERP.

## Setup

```bash
pip install -r requirements.txt
cp config.example.json config.json
# Edit config.json — set your ERP base_url and token
python main.py
```

Open **http://localhost:5837** in your browser.

## Architecture

```
ERP Cloud (Biometric)
    ↑  attendance sync (HTTP POST)
    ↑  heartbeat
    ↓  commands (enable/disable users)

ZK Agent  ←  this software
├── Web UI         port 5837   browser management interface
├── ADMS receiver  port 5836   ZKTeco WiFi devices push here
└── SDK poller     pyzk        pulls from LAN devices on demand / schedule

Devices
├── SDK devices   — LAN/TCP, agent connects and pulls
└── ADMS devices  — WiFi, device pushes to agent's HTTP server
```

## Features

- **Dashboard** — device count, attendance stats, recent syncs & logs
- **Devices** — add/edit/remove SDK and ADMS devices
  - Test connection (SDK)
  - Manual pull (SDK)
  - ADMS devices auto-register on first punch
- **Attendance** — view all records, filter by sync status
- **Sync** — manual trigger, auto-sync toggle, full history
- **Logs** — live agent log viewer
- **Settings** — ERP credentials, ports, sync interval, batch size

## Ports

| Port | Purpose |
|------|---------|
| 5836 | ADMS receiver — configure this as the server URL on ZKTeco WiFi devices |
| 5837 | Web UI — open in browser |

Both ports are configurable in `config.json` or Settings page.

## ADMS Device Setup

On the ZKTeco device, set:
- **Server address**: `http://<agent-machine-ip>:5836`
- **Server path**: `/iclock/cdata`

The device will register automatically on its first check-in.

## SDK Device Setup

Add the device via the web UI. You need:
- IP address of the device on your LAN
- Port (default: 4370)
- Password (0 if none set)
