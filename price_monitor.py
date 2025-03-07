import os
import json
import time
import logging
import requests
from datetime import datetime, timedelta
from typing import Dict, List
from dotenv import load_dotenv
from filelock import FileLock
import struct

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

load_dotenv()
CMC_API_KEY = os.getenv('CMC_API_KEY')
TG_BOT_TOKEN = os.getenv('TG_BOT_TOKEN')
TG_CHAT_ID = os.getenv('TG_CHAT_ID')

CMC_BASE_URL = "https://pro-api.coinmarketcap.com/v1"
PRICE_CHECK_INTERVAL = 60
BATCH_SIZE = 100

SHORT_TERM_THRESHOLDS = [
    {"percent": 0.2, "minutes": 2},
    {"percent": 0.5, "minutes": 5},
    {"percent": 1.0, "minutes": 10},
    {"percent": 2.0, "minutes": 30},
]

LONG_TERM_THRESHOLDS = [
    {"percent": 3.0, "minutes": 60},
    {"percent": 5.0, "minutes": 360},
    {"percent": 8.0, "minutes": 720},
    {"percent": 12.0, "minutes": 1440},
    {"percent": 15.0, "minutes": float('inf')}
]

class PriceMonitor:
    def __init__(self):
        self.tokens = {}
        # Load tokens
        self.load_tokens()
        
        # Initialize watchlist.json if it doesn't exist
        if not os.path.exists('watchlist.json') or os.path.getsize('watchlist.json') == 0:
            with open('watchlist.json', 'w') as f:
                json.dump({}, f, indent=2)
            logger.info("Created empty watchlist.json file")

    def load_tokens(self):
        try:
            if os.path.exists('tokens.json'):
                with open('tokens.json', 'r') as f:
                    self.tokens = {int(k): v for k, v in json.load(f).items()}
                    logger.info(f"Loaded {len(self.tokens)} tokens from tokens.json")
            else:
                logger.info("No tokens.json found, starting with empty token list")
                self.save_tokens()
        except Exception as e:
            logger.error(f"Error loading tokens: {e}")
            self.tokens = {}

    def save_tokens(self):
        try:
            data = {str(k): v for k, v in self.tokens.items()}
            with open('tokens.json', 'w') as f:
                json.dump(data, f, indent=2)
            logger.info(f"Saved {len(self.tokens)} tokens to tokens.json")
        except Exception as e:
            logger.error(f"Error saving tokens: {e}")

    def add_coin(self, coin_id: int) -> bool:
        try:
            # Check if coin already exists in the watchlist file directly
            watchlist_data = {}
            if os.path.exists("watchlist.json") and os.path.getsize("watchlist.json") > 0:
                with open("watchlist.json", "r") as f:
                    watchlist_data = json.load(f)
                    
                    # Check if coin already exists
                    if str(coin_id) in watchlist_data:
                        logger.info(f"Coin ID {coin_id} already exists in watchlist")
                        return True
            
            # Get coin info from API
            headers = {
                'X-CMC_PRO_API_KEY': CMC_API_KEY,
                'Accept': 'application/json'
            }
            response = requests.get(
                f"{CMC_BASE_URL}/cryptocurrency/info",
                headers=headers,
                params={'id': str(coin_id)}
            )
            data = response.json()
            
            # Check if the API returned an error
            if 'status' in data and data['status']['error_code'] != 0:
                logger.error(f"API Error: {data['status']['error_message']}")
                return False
                
            # Check if the coin ID exists in the response
            if 'data' not in data or str(coin_id) not in data['data']:
                logger.error(f"Coin ID {coin_id} not found in API response")
                return False
                
            coin_data = data['data'][str(coin_id)]
            
            # Add to tokens list
            self.tokens[coin_id] = {
                "name": coin_data["name"],
                "symbol": coin_data["symbol"]
            }
            self.save_tokens()
            
            # Add to watchlist with current time
            current_time = datetime.now()
            
            # Create new entry for this coin only
            new_entry = {
                "short_term": {
                    "last_price": None,
                    "last_notification_time": current_time.isoformat()
                },
                "long_term": {
                    "last_price": None,
                    "last_notification_time": current_time.isoformat()
                },
                "name": coin_data["name"],
                "symbol": coin_data["symbol"]
            }
            
            # Update only this coin in the watchlist file
            watchlist_data[str(coin_id)] = new_entry
            
            # Use file locking to prevent conflicts
            with FileLock("watchlist.json.lock"):
                with open("watchlist.json", "w") as f:
                    json.dump(watchlist_data, f, indent=2, sort_keys=True)
            
            logger.info(f"Added {coin_data['name']} ({coin_data['symbol']}) to tokens list and watchlist")
            return True
        except Exception as e:
            logger.error(f"Error adding coin {coin_id}: {e}")
            logger.error(f"Full error: {str(e)}")
            return False
            
    def remove_coin(self, coin_id: int) -> bool:
        try:
            # Check if coin exists in the watchlist file directly
            watchlist_data = {}
            if os.path.exists("watchlist.json") and os.path.getsize("watchlist.json") > 0:
                with open("watchlist.json", "r") as f:
                    watchlist_data = json.load(f)
                    
                    # Check if coin exists
                    if str(coin_id) not in watchlist_data:
                        logger.info(f"Coin ID {coin_id} not found in watchlist")
                        return False
            else:
                logger.info("Watchlist file doesn't exist or is empty")
                return False
            
            # Remove only this coin from the watchlist file
            coin_info = watchlist_data.pop(str(coin_id), None)
            
            if not coin_info:
                logger.info(f"Coin ID {coin_id} not found in watchlist")
                return False
            
            # Use file locking to prevent conflicts
            with FileLock("watchlist.json.lock"):
                with open("watchlist.json", "w") as f:
                    json.dump(watchlist_data, f, indent=2, sort_keys=True)
            
            # Also remove from tokens if it exists
            if coin_id in self.tokens:
                del self.tokens[coin_id]
                self.save_tokens()
            
            logger.info(f"Removed coin ID {coin_id} from watchlist")
            return True
        except Exception as e:
            logger.error(f"Error removing coin {coin_id}: {e}")
            return False

    def load_watchlist(self):
        try:
            if os.path.exists("watchlist.json") and os.path.getsize("watchlist.json") > 0:
                with open("watchlist.json", "r") as f:
                    data = json.load(f)
                    
                    # Start with an empty watchlist
                    watchlist = {}
                    
                    # Process each coin in the data
                    for coin_id_str, info in data.items():
                        try:
                            coin_id = int(coin_id_str)
                            
                            # Validate required fields
                            if not all(k in info for k in ["short_term", "long_term", "name", "symbol"]):
                                logger.warning(f"Skipping coin {coin_id_str} due to missing required fields")
                                continue
                                
                            # Convert datetime strings to datetime objects
                            short_term_time = info["short_term"]["last_notification_time"]
                            long_term_time = info["long_term"]["last_notification_time"]
                            
                            watchlist[coin_id] = {
                                "short_term": {
                                    "last_price": info["short_term"]["last_price"],
                                    "last_notification_time": datetime.fromisoformat(short_term_time)
                                },
                                "long_term": {
                                    "last_price": info["long_term"]["last_price"],
                                    "last_notification_time": datetime.fromisoformat(long_term_time)
                                },
                                "name": info["name"],
                                "symbol": info["symbol"]
                            }
                        except Exception as e:
                            logger.error(f"Error processing coin {coin_id_str} in watchlist: {e}")
                            # Skip this coin but continue processing others
                            continue
                            
                logger.info(f"Loaded watchlist with {len(watchlist)} coins")
                return watchlist
            else:
                logger.info("No existing watchlist found or file is empty")
                return {}
        except FileNotFoundError:
            logger.info("No existing watchlist found, using empty watchlist")
            return {}
        except json.JSONDecodeError:
            logger.error("Watchlist file exists but is not valid JSON, using empty watchlist")
            return {}
        except Exception as e:
            logger.error(f"Error loading watchlist: {e}")
            return {}

    def save_watchlist(self, watchlist):
        try:
            data = {}
            for coin_id, info in watchlist.items():
                data[str(coin_id)] = {
                    "symbol": info["symbol"],
                    "name": info["name"],
                    "short_term": {
                        "last_price": info["short_term"]["last_price"],
                        "last_notification_time": info["short_term"]["last_notification_time"].isoformat()
                    },
                    "long_term": {
                        "last_price": info["long_term"]["last_price"],
                        "last_notification_time": info["long_term"]["last_notification_time"].isoformat()
                    }
                }
            
            # Use file locking to prevent conflicts
            with FileLock("watchlist.json.lock"):
                with open("watchlist.json", "w") as f:
                    json.dump(data, f, indent=2, sort_keys=True)
                    
            logger.info("Watchlist updated with new prices")
        except Exception as e:
            logger.error(f"Error saving watchlist: {e}")

    def get_coin_price(self, coin_ids: List[int]) -> Dict[int, float]:
        max_retries = 3
        retry_count = 0
        
        while retry_count < max_retries:
            try:
                batches = [coin_ids[i:i + BATCH_SIZE] for i in range(0, len(coin_ids), BATCH_SIZE)]
                total_batches = len(batches)
                logger.info(f"Sending {total_batches} batch{'es' if total_batches > 1 else ''} to CoinMarketCap API (attempt {retry_count + 1}/{max_retries})")
                
                all_prices = {}
                for i, batch in enumerate(batches, 1):
                    logger.info(f"Processing batch {i}/{total_batches} with {len(batch)} coins")
                    headers = {
                        'X-CMC_PRO_API_KEY': CMC_API_KEY,
                        'Accept': 'application/json'
                    }
                    params = {
                        'id': ','.join(map(str, batch)),
                        'convert': 'USD'
                    }
                    response = requests.get(f"{CMC_BASE_URL}/cryptocurrency/quotes/latest", headers=headers, params=params)
                    data = response.json()
                    batch_prices = {int(k): float(v['quote']['USD']['price']) for k, v in data['data'].items()}
                    all_prices.update(batch_prices)
                
                return all_prices
            except Exception as e:
                retry_count += 1
                logger.error(f"Error fetching prices (attempt {retry_count}/{max_retries}): {e}")
                if retry_count >= max_retries:
                    logger.error(f"Failed to fetch prices after {max_retries} attempts")
                    return {}
                time.sleep(2)  # Wait 2 seconds before retrying

    def send_telegram_notification(self, message: str):
        try:
            url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
            data = {
                "chat_id": TG_CHAT_ID,
                "text": message,
                "parse_mode": "HTML"
            }
            response = requests.post(url, json=data)
            if not response.json().get('ok'):
                logger.error(f"❌🔴⚠️ TELEGRAM ERROR ⚠️🔴❌ Failed to send Telegram notification: {response.text}")
        except Exception as e:
            logger.error(f"❌🔴⚠️ TELEGRAM ERROR ⚠️🔴❌ Error sending Telegram notification: {e}")

    def check_price_movements(self) -> List[Dict]:
        watchlist = self.load_watchlist()
        if not watchlist:
            return []

        notifications = []
        watchlist_updated = False
        current_time = datetime.now()
        
        short_term_matches = []
        long_term_matches = []
        absolute_matches = []
        significant_changes = []
        absolute_notifications = []

        try:
            # Get current prices from API
            coin_ids = list(watchlist.keys())
            current_prices = self.get_coin_price(coin_ids)
            
        except Exception as e:
            logger.error(f"Failed to get current prices: {e}")
            return []

        # Process all coins in the watchlist
        for coin_id in list(watchlist.keys()):
            try:
                coin_info = watchlist[coin_id]
                
                # If we didn't get a price for this coin, log it but don't skip
                if coin_id not in current_prices:
                    logger.warning(f"No price data available for coin ID {coin_id} ({coin_info.get('symbol', 'Unknown')})")
                    # Continue with the next coin since we can't process this one without a price
                    continue
                
                current_price = current_prices[coin_id]
                
                # Check if this is a new coin (with blank/None price data)
                if watchlist[coin_id]["short_term"]["last_price"] is None or watchlist[coin_id]["long_term"]["last_price"] is None:
                    logger.info(f"Initializing price data for {coin_info['symbol']} (ID: {coin_id}) at ${current_price:.4f}")
                    watchlist[coin_id]["short_term"]["last_price"] = current_price
                    watchlist[coin_id]["long_term"]["last_price"] = current_price
                    watchlist[coin_id]["short_term"]["last_notification_time"] = current_time
                    watchlist[coin_id]["long_term"]["last_notification_time"] = current_time
                    significant_changes.append(f"{coin_info['symbol']}: Initial price ${current_price:.4f}")
                    watchlist_updated = True
                    continue

                short_term_price = watchlist[coin_id]["short_term"]["last_price"]
                long_term_price = watchlist[coin_id]["long_term"]["last_price"]
                
                short_term_change_percent = ((current_price - short_term_price) / short_term_price) * 100
                long_term_change_percent = ((current_price - long_term_price) / long_term_price) * 100

                # Always log all price changes regardless of significance
                significant_changes.append(
                    f"{coin_info['symbol']}: ${current_price:.4f} "
                    f"ST: {short_term_change_percent:.2f}% "
                    f"LT: {long_term_change_percent:.2f}% "
                    f"ABS: {abs(short_term_change_percent):.2f}%"
                )

                if abs(short_term_change_percent) >= 2.0:
                    absolute_matches.append(f"{coin_info['symbol']}({abs(short_term_change_percent):.1f}%)")
                    # Create absolute notification object
                    absolute_notification = {
                        "coin_name": coin_info["name"],
                        "coin_symbol": coin_info["symbol"],
                        "current_price": current_price,
                        "price_change": short_term_change_percent,
                        "type": "absolute",
                        "coin_id": coin_id
                    }
                    # Add to a separate list for now, will check for overlaps later
                    absolute_notifications.append(absolute_notification)
                    
                short_term_matched = False
                for threshold in SHORT_TERM_THRESHOLDS:
                    short_term_time = watchlist[coin_id]["short_term"]["last_notification_time"]
                    if isinstance(short_term_time, str):
                        short_term_time = datetime.fromisoformat(short_term_time)
                    short_term_time_elapsed = current_time - short_term_time
                    
                    if (abs(short_term_change_percent) >= threshold["percent"] and 
                          short_term_time_elapsed <= timedelta(minutes=threshold["minutes"])):
                        short_term_matches.append(f"{coin_info['symbol']}({abs(short_term_change_percent):.1f}%)")
                        notification = {
                            "coin_name": coin_info["name"],
                            "coin_symbol": coin_info["symbol"],
                            "current_price": current_price,
                            "price_change": short_term_change_percent,
                            "time_elapsed": short_term_time_elapsed,
                            "type": "short_term",
                            "coin_id": coin_id
                        }
                        notifications.append(notification)
                        short_term_matched = True
                        break

                for threshold in LONG_TERM_THRESHOLDS:
                    long_term_time = watchlist[coin_id]["long_term"]["last_notification_time"]
                    if isinstance(long_term_time, str):
                        long_term_time = datetime.fromisoformat(long_term_time)
                    long_term_time_elapsed = current_time - long_term_time
                    
                    if (abs(long_term_change_percent) >= threshold["percent"] and 
                          long_term_time_elapsed <= timedelta(minutes=threshold["minutes"])):
                        long_term_matches.append(f"{coin_info['symbol']}({abs(long_term_change_percent):.1f}%)")
                        notification = {
                            "coin_name": coin_info["name"],
                            "coin_symbol": coin_info["symbol"],
                            "current_price": current_price,
                            "price_change": long_term_change_percent,
                            "time_elapsed": long_term_time_elapsed,
                            "type": "long_term",
                            "coin_id": coin_id
                        }
                        notifications.append(notification)
                        
                        # Update the long-term price in the watchlist
                        watchlist[coin_id]["long_term"] = {
                            "last_price": current_price,
                            "last_notification_time": current_time
                        }
                        watchlist_updated = True
                        break

            except Exception as e:
                logger.error(f"Error processing coin {coin_id}: {e}")

        if significant_changes:
            logger.info("Price changes: " + " | ".join(significant_changes))
            
        # Always log threshold matches, even if empty
        logger.info(f"Short-term threshold matches ({len(short_term_matches)}): {', '.join(short_term_matches) if short_term_matches else 'None'}")
        logger.info(f"Long-term threshold matches ({len(long_term_matches)}): {', '.join(long_term_matches) if long_term_matches else 'None'}")
        logger.info(f"Absolute 2.5% changes ({len(absolute_matches)}): {', '.join(absolute_matches) if absolute_matches else 'None'}")

        # Check for overlaps between short-term and absolute notifications
        logger.info("Checking for overlaps between short-term and absolute notifications...")
        overlaps = []
        for abs_notif in absolute_notifications:
            # If there's already a short-term notification for this coin, skip the absolute one
            if any(notif["coin_symbol"] == abs_notif["coin_symbol"] and notif["type"] == "short_term" for notif in notifications):
                overlaps.append(abs_notif["coin_symbol"])
            else:
                notifications.append(abs_notif)
        
        if overlaps:
            logger.info(f"Ignoring absolute notifications due to short-term overlap: {', '.join(overlaps)}")
        else:
            logger.info("No overlaps found between short-term and absolute notifications")

        # Log notification details before updating prices
        for notification in notifications:
            if notification["type"] == "absolute":
                direction = "up" if notification["price_change"] > 0 else "down"
                logger.info(f"{notification['coin_name']} ({notification['coin_symbol']}) {direction} by {abs(notification['price_change']):.2f}%")
            elif notification["type"] == "short_term":
                hours = notification["time_elapsed"].total_seconds() / 3600
                time_str = (f"{int(hours)} hours" if hours >= 1 else f"{int(notification['time_elapsed'].total_seconds() / 60)} minutes")
                direction = "up" if notification["price_change"] > 0 else "down"
                logger.info(f"{notification['coin_name']} ({notification['coin_symbol']}) {direction} by {abs(notification['price_change']):.2f}% in {time_str}")
            elif notification["type"] == "long_term":
                hours = notification["time_elapsed"].total_seconds() / 3600
                time_str = (f"{int(hours)} hours" if hours >= 1 else f"{int(notification['time_elapsed'].total_seconds() / 60)} minutes")
                direction = "up" if notification["price_change"] > 0 else "down"
                logger.info(f"{notification['coin_name']} ({notification['coin_symbol']}) {direction} by {abs(notification['price_change']):.2f}% in {time_str}")

        # Update prices for all coins that triggered notifications
        for notification in notifications:
            if notification["type"] == "short_term" or notification["type"] == "absolute":
                coin_id = notification["coin_id"]
                watchlist[coin_id]["short_term"] = {
                    "last_price": notification["current_price"],
                    "last_notification_time": current_time
                }
                logger.info(f"Updated short-term price for {notification['coin_symbol']} due to {notification['type']} notification")
                watchlist_updated = True

        if watchlist_updated:
            self.save_watchlist(watchlist)

        return notifications

    def get_monitored_coins(self) -> List[Dict]:
        watchlist = self.load_watchlist()
        coins = []
        for coin_id, coin_data in watchlist.items():
            # Get coin info directly from watchlist as it now contains name and symbol
            coins.append({
                "id": coin_id,
                "name": coin_data.get("name", "Unknown"),
                "symbol": coin_data.get("symbol", "Unknown")
            })
        return coins

    def get_coin_info(self, coin_id: int) -> Dict:
        """Get information about a specific coin from either watchlist or tokens"""
        # First check if coin is in watchlist
        watchlist = self.load_watchlist()
        if coin_id in watchlist:
            return {
                "id": coin_id,
                "name": watchlist[coin_id].get("name", "Unknown"),
                "symbol": watchlist[coin_id].get("symbol", "Unknown")
            }
        # If not in watchlist, check tokens
        elif coin_id in self.tokens:
            return {
                "id": coin_id,
                "name": self.tokens[coin_id]["name"],
                "symbol": self.tokens[coin_id]["symbol"]
            }
        # Not found in either
        return None

def main():
    monitor = PriceMonitor()
    logger.info("Price monitoring started")
    
    try:
        last_check_time = datetime.now()
        last_sync_time = datetime.now()
        
        while True:
            current_time = datetime.now()
            
            # Sync tokens to watchlist every 10 seconds
            if (current_time - last_sync_time).total_seconds() >= 10:
                # Get the current tokens directly from the file, not from memory
                current_tokens = {}
                if os.path.exists('tokens.json') and os.path.getsize('tokens.json') > 0:
                    try:
                        with open('tokens.json', 'r') as f:
                            current_tokens = {int(k): v for k, v in json.load(f).items()}
                        logger.info(f"Syncing with {len(current_tokens)} tokens from tokens.json")
                    except Exception as e:
                        logger.error(f"Error loading tokens during sync: {e}")
                
                # Then load the watchlist
                watchlist = monitor.load_watchlist()
                tokens_added = False
                
                # Only add tokens that exist in the tokens.json file
                for token_id in current_tokens.keys():
                    if token_id not in watchlist:
                        # Add token to watchlist with null prices
                        watchlist[token_id] = {
                            "short_term": {
                                "last_price": None,
                                "last_notification_time": current_time
                            },
                            "long_term": {
                                "last_price": None,
                                "last_notification_time": current_time
                            },
                            "name": current_tokens[token_id]["name"],
                            "symbol": current_tokens[token_id]["symbol"]
                        }
                        logger.info(f"Added {current_tokens[token_id]['symbol']} to watchlist with null prices")
                        tokens_added = True
                
                if tokens_added:
                    monitor.save_watchlist(watchlist)
                
                # Update the monitor's tokens to match what's in the file
                monitor.tokens = current_tokens
                
                last_sync_time = current_time
            
            if (current_time - last_check_time).total_seconds() >= PRICE_CHECK_INTERVAL:
                # Always call check_price_movements to ensure tokens are added to watchlist
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
                        
                        # Only print to console, no need to duplicate the logging
                        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}")
                        
                        # Send to Telegram
                        monitor.send_telegram_notification(message)
                elif len(monitor.load_watchlist()) == 0:
                    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] No coins in watchlist")
                
                last_check_time = current_time
            
            time.sleep(1)
            
    except KeyboardInterrupt:
        print("\nStopping price monitor...")

if __name__ == "__main__":
    main()