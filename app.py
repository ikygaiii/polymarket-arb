import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager
from typing import Dict, List, Optional, Set

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import config
from data_models import ArbitrageOpportunity
from database.storage import DatabaseStorage
from main import DesyncScannerApp

logger = logging.getLogger("web_app")

# Global scanner instance
scanner: Optional[DesyncScannerApp] = None

# Active WebSocket connections
class ConnectionManager:
    def __init__(self):
        self.active_connections: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.add(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.discard(websocket)

    async def broadcast(self, message: dict):
        dead = []
        for connection in list(self.active_connections):
            try:
                await connection.send_json(message)
            except Exception:
                dead.append(connection)
        for d in dead:
            self.disconnect(d)

manager = ConnectionManager()


async def on_new_signal(signal: ArbitrageOpportunity):
    """Broadcasts newly detected arbitrage opportunity to all connected Web clients."""
    try:
        sig_dict = signal.model_dump()
        # Format datetime or timestamps if needed
        if "start_time" in sig_dict and sig_dict["start_time"]:
            sig_dict["start_time"] = sig_dict["start_time"].isoformat()
        await manager.broadcast({
            "type": "new_signal",
            "data": sig_dict
        })
    except Exception as e:
        logger.error(f"Error broadcasting new signal via WS: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global scanner
    logger.info("Starting PolyArb Scanner within Web App Lifespan...")
    scanner = DesyncScannerApp()
    scanner.add_signal_listener(on_new_signal)
    
    # Start scanner background tasks
    await scanner.start()
    
    yield
    
    logger.info("Shutting down PolyArb Scanner...")
    if scanner:
        await scanner.stop()


app = FastAPI(title="PolyArb Terminal", lifespan=lifespan)


@app.get("/", response_class=HTMLResponse)
async def get_dashboard():
    """Serves the main single-page trading terminal."""
    try:
        with open("templates/index.html", "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Dashboard template error: {e}")


@app.websocket("/ws/live")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        # Send initial signals and matches state
        if scanner:
            initial_signals = [s.model_dump() for s in scanner.active_signals[:30]]
            for s in initial_signals:
                if "start_time" in s and s["start_time"]:
                    s["start_time"] = s["start_time"].isoformat()

            await websocket.send_json({
                "type": "signals_update",
                "data": initial_signals
            })
            
            matches_data = []
            for p_id, m in scanner.matched_pairs.items():
                p_ev = scanner.poly_ws.active_events.get(p_id)
                b_ev = scanner.mock_bk.events.get(m.bk_event_id) or scanner.odds_api.events.get(m.bk_event_id)
                if p_ev and b_ev:
                    matches_data.append({
                        "bk_id": m.bk_event_id,
                        "poly_id": m.polymarket_event_id,
                        "game": p_ev.game,
                        "tournament": p_ev.tournament,
                        "bk_title": f"{b_ev.team1} vs {b_ev.team2}",
                        "bk_platform": b_ev.platform,
                        "poly_title": f"{p_ev.team1} vs {p_ev.team2}",
                        "confidence": m.confidence,
                        "match_type": m.match_type
                    })
            await websocket.send_json({
                "type": "matches_update",
                "data": matches_data
            })

        while True:
            # Keepalive listener
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:
        manager.disconnect(websocket)


@app.get("/api/status")
async def get_status():
    """Returns general health status of the scanner."""
    return {
        "status": "online" if scanner and scanner._running else "offline",
        "timestamp": time.time(),
        "active_signals_count": len(scanner.active_signals) if scanner else 0,
        "matched_pairs_count": len(scanner.matched_pairs) if scanner else 0,
        "connected_web_clients": len(manager.active_connections),
        "polymarket_events_count": len(scanner.poly_ws.active_events) if scanner else 0,
        "odds_api_configured": bool(config.ODDS_API_KEY and config.ODDS_API_KEY != "your_odds_api_key_here")
    }


@app.get("/api/signals")
async def get_signals():
    """Returns the list of detected arbitrage opportunities."""
    if not scanner:
        return {"signals": []}
    
    res = []
    for s in scanner.active_signals:
        d = s.model_dump()
        if "start_time" in d and d["start_time"]:
            d["start_time"] = d["start_time"].isoformat()
        res.append(d)
    return {"signals": res}


class SignalActionRequest(BaseModel):
    action: str  # 'accept' or 'skip'


@app.post("/api/signals/{signal_id}/action")
async def update_signal_action(signal_id: str, req: SignalActionRequest):
    """Updates user decision (accept / skip) on an arbitrage opportunity."""
    if not scanner:
        raise HTTPException(status_code=503, detail="Scanner not initialized")

    status = "accepted" if req.action == "accept" else "skipped"
    await scanner.storage.update_signal_status(signal_id, status)
    
    # Update in memory
    for s in scanner.active_signals:
        if s.signal_id == signal_id:
            s.status = status
            break
            
    return {"status": "ok", "signal_id": signal_id, "action": status}


@app.get("/api/matches")
async def get_matches():
    """Returns list of currently paired events between Polymarket and bookmakers."""
    if not scanner:
        return {"matches": []}

    matches_data = []
    for p_id, m in scanner.matched_pairs.items():
        p_ev = scanner.poly_ws.active_events.get(p_id)
        b_ev = scanner.mock_bk.events.get(m.bk_event_id) or scanner.odds_api.events.get(m.bk_event_id)
        if p_ev and b_ev:
            matches_data.append({
                "bk_id": m.bk_event_id,
                "poly_id": m.polymarket_event_id,
                "game": p_ev.game,
                "tournament": p_ev.tournament,
                "bk_title": f"{b_ev.team1} vs {b_ev.team2}",
                "bk_platform": b_ev.platform,
                "poly_title": f"{p_ev.team1} vs {p_ev.team2}",
                "confidence": m.confidence,
                "match_type": m.match_type
            })

    return {"matches": matches_data}


@app.get("/api/analytics")
async def get_analytics():
    """Fetches performance stats and recent history from database."""
    if not scanner:
        return {}
    summary = await scanner.storage.get_analytics_summary()
    return summary


@app.get("/api/config")
async def get_config():
    """Returns current detection settings."""
    return {
        "odds_api_key": config.ODDS_API_KEY,
        "typical_stake_usd": config.TYPICAL_STAKE_USD,
        "min_profit_threshold_pct": config.MIN_PROFIT_THRESHOLD_PCT,
        "polymarket_taker_fee_pct": config.POLYMARKET_TAKER_FEE_PCT,
        "max_slippage_pct": config.MAX_SLIPPAGE_PCT,
        "dynamic_desync_delta_pct": config.DYNAMIC_DESYNC_DELTA_PCT,
        "dynamic_desync_window_sec": config.DYNAMIC_DESYNC_WINDOW_SEC,
    }


class ConfigUpdateRequest(BaseModel):
    odds_api_key: Optional[str] = None
    typical_stake_usd: Optional[float] = None
    min_profit_threshold_pct: Optional[float] = None
    polymarket_taker_fee_pct: Optional[float] = None
    max_slippage_pct: Optional[float] = None
    dynamic_desync_delta_pct: Optional[float] = None
    dynamic_desync_window_sec: Optional[float] = None


@app.post("/api/config")
async def update_config(req: ConfigUpdateRequest):
    """Updates runtime configuration in memory and in .env file."""
    env_updates = {}
    
    if req.odds_api_key is not None:
        config.ODDS_API_KEY = req.odds_api_key
        env_updates["ODDS_API_KEY"] = req.odds_api_key
        if scanner:
            scanner.odds_api.api_key = req.odds_api_key

    if req.typical_stake_usd is not None:
        config.TYPICAL_STAKE_USD = req.typical_stake_usd
        env_updates["TYPICAL_STAKE_USD"] = str(req.typical_stake_usd)
        if scanner:
            scanner.detector.typical_stake_usd = req.typical_stake_usd

    if req.min_profit_threshold_pct is not None:
        config.MIN_PROFIT_THRESHOLD_PCT = req.min_profit_threshold_pct
        env_updates["MIN_PROFIT_THRESHOLD_PCT"] = str(req.min_profit_threshold_pct)
        if scanner:
            scanner.detector.min_profit_pct = req.min_profit_threshold_pct

    if req.polymarket_taker_fee_pct is not None:
        config.POLYMARKET_TAKER_FEE_PCT = req.polymarket_taker_fee_pct
        env_updates["POLYMARKET_TAKER_FEE_PCT"] = str(req.polymarket_taker_fee_pct)
        if scanner:
            scanner.detector.fee_factor = 1.0 - (req.polymarket_taker_fee_pct / 100.0)

    if req.max_slippage_pct is not None:
        config.MAX_SLIPPAGE_PCT = req.max_slippage_pct
        env_updates["MAX_SLIPPAGE_PCT"] = str(req.max_slippage_pct)
        if scanner:
            scanner.detector.max_slippage_pct = req.max_slippage_pct

    if req.dynamic_desync_delta_pct is not None:
        config.DYNAMIC_DESYNC_DELTA_PCT = req.dynamic_desync_delta_pct
        env_updates["DYNAMIC_DESYNC_DELTA_PCT"] = str(req.dynamic_desync_delta_pct)
        if scanner:
            scanner.detector.desync_delta_pct = req.dynamic_desync_delta_pct

    if req.dynamic_desync_window_sec is not None:
        config.DYNAMIC_DESYNC_WINDOW_SEC = req.dynamic_desync_window_sec
        env_updates["DYNAMIC_DESYNC_WINDOW_SEC"] = str(req.dynamic_desync_window_sec)
        if scanner:
            scanner.detector.desync_window_sec = req.dynamic_desync_window_sec

    # Update .env file on disk if possible
    try:
        env_file = config.env_path
        if env_file.exists():
            lines = env_file.read_text(encoding="utf-8").splitlines()
            new_lines = []
            seen_keys = set()
            for line in lines:
                if "=" in line and not line.strip().startswith("#"):
                    k, v = line.split("=", 1)
                    k = k.strip()
                    if k in env_updates:
                        new_lines.append(f"{k}={env_updates[k]}")
                        seen_keys.add(k)
                        continue
                new_lines.append(line)
            for k, v in env_updates.items():
                if k not in seen_keys:
                    new_lines.append(f"{k}={v}")
            env_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    except Exception as ex:
        logger.warning(f"Could not persist config to .env: {ex}")

    return {"status": "ok", "message": "Settings updated"}


@app.post("/api/simulate/jump")
async def simulate_jump():
    """Simulates a rapid odds jump in Mock Bookmaker to instantly test Dynamic Desync signal generation."""
    if not scanner:
        raise HTTPException(status_code=503, detail="Scanner not initialized")

    # Pick an active matched event or mock event
    event_id = "bk_mouz_navi_1" if "bk_mouz_navi_1" in scanner.mock_bk.events else "bk_navi_faze_1"
    
    # Trigger odds move
    await scanner.mock_bk.trigger_price_jump(event_id, new_odds1=3.10, new_odds2=1.35)
    return {"status": "ok", "event_id": event_id, "message": "Triggered simulated odds jump"}


if __name__ == "__main__":
    uvicorn.run(
        "app:app",
        host=config.WEB_HOST,
        port=config.WEB_PORT,
        reload=False,
        log_level="info"
    )
