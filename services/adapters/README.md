# Adapters

Runtime collectors and bridges that connect external signals into Brainstem.

## State Collector

`state_collector.py` pushes ED/music/system state into Brainstem `POST /state`.

### Run

- `python services/adapters/state_collector.py`
- or `services/adapters/run_state_collector.ps1`

### Environment

- `WKV_BRAINSTEM_URL` default `http://127.0.0.1:8787`
- `WKV_PROFILE` default `watchkeeper`
- `WKV_COLLECTOR_SESSION` default `collector-main`
- `WKV_NOW_PLAYING_DIR` default `C:/ai/Watchkeeper/now-playing`
- `WKV_ED_PROCESS_NAMES` default `EliteDangerous64.exe,EliteDangerous.exe`
- `WKV_SYSTEM_INTERVAL_SEC` default `15`
- `WKV_ED_ACTIVE_INTERVAL_SEC` default `2`
- `WKV_ED_IDLE_INTERVAL_SEC` default `8`
- `WKV_MUSIC_ACTIVE_INTERVAL_SEC` default `2`
- `WKV_MUSIC_IDLE_INTERVAL_SEC` default `12`
