import os
import logging
import signal
import sys
import time
import threading
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.error import TelegramError, NetworkError, TimedOut
from dotenv import load_dotenv
from price_monitor import PriceMonitor, SHORT_TERM_THRESHOLDS, LONG_TERM_THRESHOLDS

# Configure logging but disable httpx logging
logging.basicConfig(
   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
   level=logging.INFO
)
logger = logging.getLogger(__name__)
# Disable HTTP request logging
logging.getLogger('httpx').setLevel(logging.WARNING)

load_dotenv()
TG_BOT_TOKEN = os.getenv('TG_BOT_TOKEN')

price_monitor = PriceMonitor()
# Global variable to track application status
app = None
reconnect_delay = 5  # seconds between reconnection attempts
connection_check_interval = 10  # seconds between connection checks
is_running = True

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
   welcome_message = (
       "Welcome to the Crypto Price Movement Monitor!\n\n"
       "Available commands:\n"
       "/add <coin_id> - Add a coin to monitor\n"
       "/remove <coin_id> - Remove a coin from monitoring\n"
       "/list - List all monitored coins\n"
       "/rules - Show current notification thresholds"
   )
   await update.message.reply_text(welcome_message)

async def add_coin(update: Update, context: ContextTypes.DEFAULT_TYPE):
   try:
       coin_id = int(context.args[0])
       if price_monitor.add_coin(coin_id):
           coin_info = price_monitor.get_coin_info(coin_id)
           await update.message.reply_text(
               f"Added {coin_info['name']} ({coin_info['symbol']}) to watchlist"
           )
       else:
           await update.message.reply_text("Failed to add coin. Please check the coin ID.")
   except (ValueError, IndexError):
       await update.message.reply_text("Please provide a valid coin ID: /add <coin_id>")

async def remove_coin(update: Update, context: ContextTypes.DEFAULT_TYPE):
   try:
       coin_id = int(context.args[0])
       if price_monitor.remove_coin(coin_id):
           await update.message.reply_text("Coin removed from watchlist")
       else:
           await update.message.reply_text("Failed to remove coin. Please check the coin ID.")
   except (ValueError, IndexError):
       await update.message.reply_text("Please provide a valid coin ID: /remove <coin_id>")

async def list_coins(update: Update, context: ContextTypes.DEFAULT_TYPE):
   coins = price_monitor.get_monitored_coins()
   if coins:
       message = "Monitored coins:\n" + "\n".join(
           f"{coin['name']} ({coin['symbol']}) - ID: {coin['id']}"
           for coin in coins
       )
   else:
       message = "No coins in watchlist"
   await update.message.reply_text(message)

async def show_rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Format short-term thresholds
    short_term_rules = "\n".join([
        f"• {threshold['percent']}% change within {threshold['minutes']} minutes"
        for threshold in SHORT_TERM_THRESHOLDS
    ])
    
    # Format long-term thresholds
    long_term_rules = []
    for threshold in LONG_TERM_THRESHOLDS:
        if threshold['minutes'] == float('inf'):
            long_term_rules.append(f"• {threshold['percent']}% change (all-time)")
        elif threshold['minutes'] >= 60:
            hours = threshold['minutes'] // 60
            long_term_rules.append(f"• {threshold['percent']}% change within {hours} hour{'s' if hours > 1 else ''}")
        else:
            long_term_rules.append(f"• {threshold['percent']}% change within {threshold['minutes']} minutes")
    
    long_term_rules_text = "\n".join(long_term_rules)
    
    # Additional note about absolute threshold
    absolute_note = "Additionally, any price change of 2.5% or more will trigger a notification, unless a short-term rule was already triggered."
    
    message = (
        "📊 *Current Notification Rules* 📊\n\n"
        "*Short-term Thresholds:*\n"
        f"{short_term_rules}\n\n"
        "*Long-term Thresholds:*\n"
        f"{long_term_rules_text}\n\n"
        f"{absolute_note}"
    )
    
    await update.message.reply_text(message, parse_mode='Markdown')

def signal_handler(sig, frame):
    """Handle graceful shutdown when Ctrl+C is pressed"""
    global is_running
    print("\nShutting down bot gracefully...")
    is_running = False
    # Perform any cleanup here if needed
    sys.exit(0)

async def error_handler(update, context):
    """Handle errors in the dispatcher"""
    try:
        if isinstance(context.error, NetworkError):
            logger.error(f"❌🔴⚠️ NETWORK ERROR ⚠️🔴❌ Network error occurred: {context.error}")
        elif isinstance(context.error, TimedOut):
            logger.error(f"⏱️❌⚠️ TIMEOUT ERROR ⚠️❌⏱️ Request timed out: {context.error}")
        else:
            logger.error(f"💥❌⚠️ BOT ERROR ⚠️❌💥 Error handling update {update}: {context.error}")
    except Exception as e:
        logger.error(f"💥❌⚠️ EXCEPTION ERROR ⚠️❌💥 Exception in error handler: {e}")

def check_connection_background():
    """Background thread to monitor connection"""
    global is_running
    
    logger.info("Starting connection monitoring thread")
    
    while is_running:
        try:
            # Simple HTTP request to Telegram API to check connection
            import requests
            response = requests.get(f"https://api.telegram.org/bot{TG_BOT_TOKEN}/getMe", timeout=5)
            
            if response.status_code == 200:
                data = response.json()
                if data.get('ok'):
                    logger.info(f"Connection to Telegram is active. Bot: {data['result']['username']}")
                else:
                    logger.warning(f"⚠️🟡 CONNECTION WARNING 🟡⚠️ Connection check returned non-OK status: {data}")
            else:
                logger.warning(f"⚠️🟡 CONNECTION WARNING 🟡⚠️ Connection check failed with status code: {response.status_code}")
                
        except requests.RequestException as e:
            logger.error(f"❌🔴⚠️ CONNECTION ERROR ⚠️🔴❌ Connection check failed: {str(e)}")
        except Exception as e:
            logger.error(f"💥❌⚠️ MONITOR ERROR ⚠️❌💥 Error in connection monitor: {str(e)}")
            
        # Wait before checking again
        time.sleep(connection_check_interval)

def run_bot():
    """Run the bot with automatic reconnection"""
    global is_running
    
    # Start connection monitoring in a separate thread
    monitor_thread = threading.Thread(target=check_connection_background, daemon=True)
    monitor_thread.start()
    
    while is_running:
        try:
            # Initialize the Application
            application = Application.builder().token(TG_BOT_TOKEN).build()
            
            # Add handlers
            application.add_handler(CommandHandler("start", start))
            application.add_handler(CommandHandler("add", add_coin))
            application.add_handler(CommandHandler("remove", remove_coin))
            application.add_handler(CommandHandler("list", list_coins))
            application.add_handler(CommandHandler("rules", show_rules))
            application.add_error_handler(error_handler)
            
            # Log that we're starting
            logger.info("Starting Telegram bot...")
            print("Bot started! Press Ctrl+C to stop.")
            
            # Start the bot
            application.run_polling(drop_pending_updates=True)
            
        except (NetworkError, TimedOut, ConnectionError) as e:
            logger.error(f"❌🔴⚠️ NETWORK ERROR ⚠️🔴❌ Network error: {str(e)}")
            logger.info(f"Attempting to reconnect in {reconnect_delay} seconds...")
            time.sleep(reconnect_delay)
            
        except Exception as e:
            logger.error(f"💥❌⚠️ UNEXPECTED ERROR ⚠️❌💥 Unexpected error: {str(e)}")
            logger.info(f"Attempting to restart in {reconnect_delay} seconds...")
            time.sleep(reconnect_delay)
            
        finally:
            if is_running:
                logger.info(f"Bot stopped. Restarting in {reconnect_delay} seconds...")
                time.sleep(reconnect_delay)
            else:
                logger.info("Bot has been stopped permanently.")

def main():
    # Set up signal handler for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    
    # Make is_running accessible in this scope
    global is_running
    
    # Run the bot
    run_bot()

if __name__ == "__main__":
   main()