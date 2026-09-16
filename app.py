import asyncio
import threading
import time
import gradio as gr

import config
from data_models import SourceHealth
from database.storage import DatabaseStorage
from main import DesyncScannerApp

scanner_app: DesyncScannerApp = None


def start_scanner_in_thread():
    """Runs the main async scanner and Telegram bot loop in a background thread."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    async def _run():
        global scanner_app
        scanner_app = DesyncScannerApp()
        await scanner_app.start()
        while True:
            await asyncio.sleep(3600)

    try:
        loop.run_until_complete(_run())
    except Exception as e:
        print(f"Error in scanner thread: {e}")


# Start bot background thread automatically on startup
scanner_thread = threading.Thread(target=start_scanner_in_thread, daemon=True)
scanner_thread.start()


async def get_dashboard_stats():
    """Fetches stats from database for Gradio UI dashboard."""
    try:
        storage = DatabaseStorage(config.DATABASE_PATH)
        await storage.init_db()
        stats = await storage.get_analytics_summary()
        
        md_text = (
            f"### 🟢 Бота запущен и работает 24/7!\n\n"
            f"• **Всего сигналов найдено:** `{stats['total_signals']}`\n"
            f"• **Динамических рассинхронов (Dynamic):** `{stats['dynamic_count']}`\n"
            f"• **Средний ROI:** `+{stats['avg_profit_pct']}%`\n"
            f"• **Принято пользователем:** `{stats['accepted_count']}`\n"
            f"• **Пропущено:** `{stats['skipped_count']}`\n\n"
            f"_Обновлено: {time.strftime('%H:%M:%S')}_"
        )
        return md_text
    except Exception as e:
        return f"Ошибка получения статистики: {e}"


# Create Gradio UI Dashboard
with gr.Blocks(title="Polymarket Desync Bot Dashboard") as demo:
    gr.Markdown("# 🚀 Polymarket Probability Desync Bot Dashboard")
    gr.Markdown("Мониторинг фоновой работы Telegram-бота и парсера Polymarket.")
    
    stats_markdown = gr.Markdown("Загрузка статистики...")
    refresh_btn = gr.Button("🔄 Обновить статистику", variant="primary")
    
    refresh_btn.click(fn=get_dashboard_stats, outputs=stats_markdown)
    demo.load(fn=get_dashboard_stats, outputs=status_markdown)

if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7860)
