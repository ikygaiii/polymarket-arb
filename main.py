import asyncio
import logging
import signal
import sys
import time
from typing import Dict, List, Optional

import config
from data_models import StandardizedEvent, Orderbook, MatchedPair, ArbitrageOpportunity
from database.storage import DatabaseStorage
from matcher.fuzzy_matcher import EventMatcher
from calculator.desync_engine import DesyncDetector
from parsers.polymarket_ws import PolymarketWSParser
from parsers.mock_bookmaker import MockBookmakerParser
from parsers.odds_api import OddsApiParser
from bot.telegram_bot import TelegramNotifier

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("polymarket_desync.log", encoding="utf-8")
    ]
)
logger = logging.getLogger("main")


class DesyncScannerApp:
    def __init__(self):
        self.storage = DatabaseStorage(config.DATABASE_PATH)
        self.matcher = EventMatcher()
        self.detector = DesyncDetector()
        self.notifier = TelegramNotifier()

        self.poly_ws = PolymarketWSParser()
        self.mock_bk = MockBookmakerParser()
        self.odds_api = OddsApiParser()

        self.matched_pairs: Dict[str, MatchedPair] = {}  # poly_event_id -> MatchedPair
        self.processed_signal_ids = set()
        self._running = False

    async def _on_poly_update(self, token_id: str, orderbook: Orderbook):
        """Low-latency callback triggered instantly when Polymarket orderbook updates."""
        if not self._running:
            return

        event_id = self.poly_ws.token_to_event.get(token_id)
        if not event_id:
            return

        poly_event = self.poly_ws.active_events.get(event_id)
        if not poly_event:
            return

        # Check matched BK events
        matched = self.matched_pairs.get(event_id)
        if not matched:
            return

        # Get BK event
        bk_event = self.mock_bk.events.get(matched.bk_event_id) or self.odds_api.events.get(matched.bk_event_id)
        if not bk_event:
            return

        # Evaluate desync
        signals = self.detector.evaluate_desync(
            poly_event=poly_event,
            bk_event=bk_event,
            poly_orderbooks=self.poly_ws.orderbooks,
            matched_pair=matched
        )

        for sig in signals:
            sig_key = f"{sig.poly_event_id}:{sig.poly_outcome_selected}:{sig.profit_pct:.1f}"
            if sig_key not in self.processed_signal_ids:
                self.processed_signal_ids.add(sig_key)
                logger.info(f"🚨 [{sig.signal_type.value.upper()}] Signal Detected: {sig.event_title} | ROI: +{sig.profit_pct}%")
                await self.storage.save_arb_signal(sig)
                await self.notifier.send_alert(sig)

    async def _on_bk_update(self, bk_event: StandardizedEvent):
        """Low-latency callback triggered instantly when Bookmaker odds update."""
        if not self._running:
            return

        # Find matching Polymarket event
        for poly_id, matched in self.matched_pairs.items():
            if matched.bk_event_id == bk_event.event_id:
                poly_event = self.poly_ws.active_events.get(poly_id)
                if not poly_event:
                    continue

                signals = self.detector.evaluate_desync(
                    poly_event=poly_event,
                    bk_event=bk_event,
                    poly_orderbooks=self.poly_ws.orderbooks,
                    matched_pair=matched
                )

                for sig in signals:
                    sig_key = f"{sig.poly_event_id}:{sig.poly_outcome_selected}:{sig.profit_pct:.1f}"
                    if sig_key not in self.processed_signal_ids:
                        self.processed_signal_ids.add(sig_key)
                        logger.info(f"🚨 [{sig.signal_type.value.upper()}] Signal Detected: {sig.event_title} | ROI: +{sig.profit_pct}%")
                        await self.storage.save_arb_signal(sig)
                        await self.notifier.send_alert(sig)

    async def _matching_loop(self):
        """Periodic loop to refresh event matching between platforms."""
        while self._running:
            try:
                poly_events = list(self.poly_ws.active_events.values())
                bk_events = list(self.mock_bk.events.values()) + list(self.odds_api.events.values())

                if poly_events and bk_events:
                    matches = self.matcher.match_events(bk_events, poly_events)
                    for m in matches:
                        self.matched_pairs[m.polymarket_event_id] = m
                        await self.storage.save_matched_pair(m)
                    logger.info(f"Refreshed event matcher: {len(self.matched_pairs)} active matched pairs")
            except Exception as e:
                logger.error(f"Error in matching loop: {e}")

            await asyncio.sleep(config.MATCHING_INTERVAL_SEC if hasattr(config, 'MATCHING_INTERVAL_SEC') else 60)

    async def start(self):
        logger.info("Initializing Polymarket Probability Desync System...")
        await self.storage.init_db()

        self._running = True

        # Register update callbacks
        self.poly_ws.register_update_callback(self._on_poly_update)
        self.mock_bk.register_update_callback(self._on_bk_update)
        self.odds_api.register_update_callback(self._on_bk_update)

        # Start components
        await self.notifier.start_bot(self.storage)
        await self.poly_ws.start()
        await self.mock_bk.start()
        await self.odds_api.start()

        # Start matching loop task
        asyncio.create_task(self._matching_loop())
        logger.info("System fully operational and actively scanning for probability desyncs!")

    async def stop(self):
        logger.info("Stopping system...")
        self._running = False
        await self.poly_ws.stop()
        await self.mock_bk.stop()
        await self.odds_api.stop()
        logger.info("System stopped gracefully.")


async def main():
    app = DesyncScannerApp()
    await app.start()

    stop_event = asyncio.Event()

    def handle_signal():
        stop_event.set()

    loop = asyncio.get_running_loop()
    for s in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(s, handle_signal)
        except NotImplementedError:
            pass

    try:
        await stop_event.wait()
    finally:
        await app.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
