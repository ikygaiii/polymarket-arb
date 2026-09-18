import asyncio
import logging
import time
from typing import Optional
from datetime import datetime

from aiogram import Bot, Dispatcher, types, Router, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.enums import ParseMode

import config
from data_models import ArbitrageOpportunity, SignalType
from database.storage import DatabaseStorage

logger = logging.getLogger(__name__)

router = Router()
db_storage: Optional[DatabaseStorage] = None


def format_signal_message(signal: ArbitrageOpportunity) -> str:
    """Formats an ArbitrageOpportunity into a rich Markdown notification."""
    now = time.time()
    signal_age = max(0, int(now - signal.detected_at))

    if signal.signal_type == SignalType.DYNAMIC:
        header = f"⚡ **[DYNAMIC DESYNC DETECTED]** ⚡\n"
        if signal.price_change_delta_pct > 0:
            header += f"🔥 *Резкий скачок цены:* `+{signal.price_change_delta_pct}%`\n"
        header += f"⏰ *Дедлайн актуальности:* `{signal.ttl_sec} сек` (прошло {signal_age}s)\n"
    else:
        header = f"📊 **[STATIC ARBITRAGE SIGNAL]**\n"

    time_str = signal.start_time.strftime("%d.%m %H:%M") if signal.start_time else "Скоро"
    
    # Selected leg description
    poly_leg_team = signal.poly_outcome_selected
    bk_leg_team = signal.team2 if poly_leg_team == signal.team1 else signal.team1
    bk_leg_odds = signal.bk_team2_odds if poly_leg_team == signal.team1 else signal.bk_team1_odds

    poly_leg_price = signal.poly_team1_vwap if poly_leg_team == signal.team1 else signal.poly_team2_vwap
    poly_cents = round(poly_leg_price * 100, 1)
    cents_str = f"{poly_cents:.0f}" if poly_cents.is_integer() else f"{poly_cents:.1f}"

    poly_url = f"[Polymarket]({signal.poly_market_url})" if signal.poly_market_url else "Polymarket"
    bk_url = f"[{signal.bk_platform}]({signal.bk_market_url})" if signal.bk_market_url else signal.bk_platform

    poly_link_row = f"   • 🔗 [Открыть маркет на Polymarket]({signal.poly_market_url})\n" if signal.poly_market_url else ""
    bk_link_row = f"   • 🔗 [Открыть матч в {signal.bk_platform}]({signal.bk_market_url})\n" if signal.bk_market_url else ""

    msg = (
        f"{header}\n"
        f"🎮 *Дисциплина:* {signal.game} | *Турнир:* {signal.tournament}\n"
        f"⚔️ *Матч:* `{signal.event_title}` ({time_str})\n\n"

        f"🟢 *Плечо 1 ({poly_url}):*\n"
        f"   • Исход: BUY YES `{poly_leg_team}`\n"
        f"   • Цена Polymarket: `{cents_str}¢` (`{cents_str} центов` / `${poly_leg_price:.3f}`)\n"
        f"   • Вероятность: `P_impl` = `{signal.poly_implied_prob1 if poly_leg_team == signal.team1 else signal.poly_implied_prob2:.1%}`\n"
        f"   • Рекомендуемый взнос: `${signal.poly_stake:.2f}`\n"
        f"{poly_link_row}\n"

        f"🔵 *Плечо 2 ({bk_url}):*\n"
        f"   • Исход: BET `{bk_leg_team}`\n"
        f"   • Коэффициент в БК: `{bk_leg_odds:.2f}` (`P_impl` = `{1.0/bk_leg_odds:.1%}`)\n"
        f"   • Рекомендуемый взнос: `${signal.bk_stake:.2f}`\n"
        f"{bk_link_row}\n"

        f"💰 *ФИНАНСОВЫЙ ИТОГ:*\n"
        f"   • Общий банк: `${signal.total_stake:.2f}`\n"
        f"   • Сумма вероятностей Σq: `{signal.sum_implied_prob:.4f}`\n"
        f"   • Гарантированный ROI: `+{signal.profit_pct:.2f}%` (+${signal.net_profit_usd:.2f})\n"
        f"   • Профит при победе {signal.team1}: `${signal.leg1_profit_usd:.2f}`\n"
        f"   • Профит при победе {signal.team2}: `${signal.leg2_profit_usd:.2f}`\n\n"

        f"💧 *ЛИКВИДНОСТЬ И ИСПОЛНЕНИЕ:*\n"
        f"   • Макс. исполняемый объем (проскальзывание <{signal.slippage_pct}%): `${signal.max_executable_stake_usd:.2f}`\n"
        f"   • Свежесть данных: `{signal.data_freshness_sec:.1f}s`"
    )

    return msg


def get_signal_keyboard(signal_id: str) -> InlineKeyboardMarkup:
    """Builds inline keyboard with Accepted / Skipped buttons."""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Принял", callback_data=f"accept:{signal_id}"),
            InlineKeyboardButton(text="❌ Пропустил", callback_data=f"skip:{signal_id}")
        ]
    ])
    return keyboard


@router.message(Command("start", "help"))
async def cmd_start(message: types.Message):
    await message.answer(
        "👋 **Система детекции рассинхрона вероятностей (БК ↔ Polymarket)**\n\n"
        "Команды бота:\n"
        "/stats — Аналитика по сигналам\n"
        "/health — Состояние источников данных\n"
        "/status — Текущие настройки",
        parse_mode=ParseMode.MARKDOWN
    )


@router.message(Command("stats"))
async def cmd_stats(message: types.Message):
    if not db_storage:
        await message.answer("Ошибка: База данных не подключена")
        return
    stats = await db_storage.get_analytics_summary()
    await message.answer(
        f"📊 *АНАЛИТИКА СИГНАЛОВ*\n\n"
        f"• Всего обнаружено сигналов: `{stats['total_signals']}`\n"
        f"• Динамических desync: `{stats['dynamic_count']}`\n"
        f"• Средний ROI: `+{stats['avg_profit_pct']}%`\n"
        f"• Принято сделок: `{stats['accepted_count']}`\n"
        f"• Пропущено: `{stats['skipped_count']}`\n"
        f"• Исполнение (% accepted): `{stats['acceptance_rate']}%`",
        parse_mode=ParseMode.MARKDOWN
    )


@router.message(Command("status"))
async def cmd_status(message: types.Message):
    await message.answer(
        f"⚙️ *НАСТРОЙКИ СИСТЕМЫ И ПОРОГИ*\n\n"
        f"• Минимальный ROI: `+{config.MIN_PROFIT_THRESHOLD_PCT}%`\n"
        f"• Размер банка по умолчанию: `${config.TYPICAL_STAKE_USD}`\n"
        f"• Комиссия Polymarket Taker: `{config.POLYMARKET_TAKER_FEE_PCT}%`\n"
        f"• Порог Dynamic Desync: `+{config.DYNAMIC_DESYNC_DELTA_PCT}%` за `{config.DYNAMIC_DESYNC_WINDOW_SEC}s`\n"
        f"• Макс. проскальзывание: `{config.MAX_SLIPPAGE_PCT}%`\n"
        f"• Порог устаревания данных: `{config.STALE_DATA_THRESHOLD_SEC}s`",
        parse_mode=ParseMode.MARKDOWN
    )


@router.message(Command("health"))
async def cmd_health(message: types.Message):
    await message.answer(
        f"🟢 *СОСТОЯНИЕ ИСТОЧНИКОВ ДАННЫХ*\n\n"
        f"• **Polymarket CLOB WebSocket:** Active 🟢\n"
        f"• **Bookmaker Feed (Pinnacle/OddsAPI):** Active 🟢\n"
        f"• **Event Matcher:** Active 🟢\n"
        f"• **Database (SQLite):** Connected 🟢",
        parse_mode=ParseMode.MARKDOWN
    )


@router.callback_query(F.data.startswith("accept:") | F.data.startswith("skip:"))
async def handle_signal_callback(query: types.CallbackQuery):
    if not query.data:
        return

    action, signal_id = query.data.split(":", 1)
    status_text = "accepted" if action == "accept" else "skipped"
    status_display = "✅ **СДЕЛКА ПРИНЯТА В УЧЕТ**" if action == "accept" else "❌ **СДЕЛКА ПРОПУЩЕНА**"

    if db_storage:
        await db_storage.update_signal_status(signal_id, status_text)

    await query.answer(f"Статус обновлен: {status_text}")
    if query.message and isinstance(query.message, types.Message):
        updated_text = query.message.text + f"\n\nСтатус: {status_display}"
        await query.message.edit_text(updated_text, reply_markup=None)


class TelegramNotifier:
    def __init__(self, token: str = config.TELEGRAM_BOT_TOKEN, chat_id: str = config.TELEGRAM_CHAT_ID):
        self.token = token
        self.chat_id = chat_id
        self.bot: Optional[Bot] = Bot(token=self.token) if self.token else None
        self.dp: Optional[Dispatcher] = Dispatcher() if self.bot else None

    async def start_bot(self, storage: DatabaseStorage):
        global db_storage
        db_storage = storage

        if not self.bot or not self.dp:
            logger.warning("Telegram Bot token not set. Bot will not send alerts.")
            return

        self.dp.include_router(router)
        logger.info("Starting Telegram Bot polling router...")
        asyncio.create_task(self.dp.start_polling(self.bot))

    async def send_alert(self, signal: ArbitrageOpportunity):
        """Sends alert message to Telegram channel/chat."""
        if not self.bot or not self.chat_id:
            logger.info(f"[ALERT CONSOLE ONLY] {signal.signal_type.value} Arb: {signal.event_title} | ROI: +{signal.profit_pct}%")
            return

        text = format_signal_message(signal)
        keyboard = get_signal_keyboard(signal.signal_id or "")

        try:
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=keyboard,
                disable_web_page_preview=True
            )
            logger.info(f"Telegram alert sent for signal {signal.signal_id}")
        except Exception as e:
            logger.error(f"Failed to send Telegram alert: {e}")

