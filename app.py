import os
import logging
import threading
import time
from telegram_bot import run_bot
from price_monitor import PriceMonitor

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

def run_price_monitor():
    """Run the price monitor in a separate thread"""
    monitor = PriceMonitor()
    logger.info("Price monitoring started")
    
    try:
        while True:
            notifications = monitor.check_price_movements()
            if notifications:
                for notif in notifications:
                    # Different message format based on notification type
                    if notif["type"] == "absolute":
                        # Absolute change notification without time
                        direction = "up" if notif["price_change"] > 0 else "down"
                        message = (
                            f"{notif['coin_name']} ({notif['coin_symbol']}) {direction} by {abs(notif['price_change']):.2f}%\n"
                            f"Current price: ${notif['current_price']:.4f}"
                        )
                    else:
                        # Short-term or long-term notification with time
                        hours = notif["time_elapsed"].total_seconds() / 3600
                        time_str = (
                            f"{int(hours)} hours" if hours >= 1
                            else f"{int(notif['time_elapsed'].total_seconds() / 60)} minutes"
                        )
                        
                        direction = "up" if notif["price_change"] > 0 else "down"
                        
                        message = (
                            f"{notif['coin_name']} ({notif['coin_symbol']}) {direction} by {abs(notif['price_change']):.2f}% in {time_str}\n"
                            f"Current price: ${notif['current_price']:.4f}"
                        )
                    
                    # Send to Telegram
                    monitor.send_telegram_notification(message)
            
            # Sleep for the configured interval
            time.sleep(60)  # Check every minute
            
    except Exception as e:
        logger.error(f"💥❌⚠️ MONITOR ERROR ⚠️❌💥 Error in price monitor: {e}")

def main():
    """Main entry point for the application"""
    logger.info("Starting cryptocurrency price monitoring application")
    
    # Start price monitor in a separate thread
    price_thread = threading.Thread(target=run_price_monitor, daemon=True)
    price_thread.start()
    
    # Run the Telegram bot in the main thread
    run_bot()

if __name__ == "__main__":
    main()
