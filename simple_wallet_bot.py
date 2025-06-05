#!/usr/bin/env python3
"""
Simple Ethereum Wallet Tracker Bot
Monitors wallet transactions and sends Telegram alerts
"""

import time
import requests
import logging
from web3 import Web3
from datetime import datetime
import json

# Configuration
ALCHEMY_API_KEY = "PB5RUs6zDOKs-lGvw4gfWFyo7pcyvQ5e"
TELEGRAM_BOT_TOKEN = "7719879033:AAHN2NDEnq-KBmwo8_o47ibv4nap-mI4aA4"
TELEGRAM_CHAT_ID = "1114236546"

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize Web3
w3 = Web3(Web3.HTTPProvider(f'https://eth-mainnet.g.alchemy.com/v2/{ALCHEMY_API_KEY}'))

class SimpleWalletTracker:
    def __init__(self):
        self.tracked_wallets = {}
        self.last_processed_block = 0
        self.running = False
        
    def send_telegram_message(self, message):
        """Send message to Telegram"""
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            data = {
                'chat_id': TELEGRAM_CHAT_ID,
                'text': message,
                'parse_mode': 'HTML'
            }
            response = requests.post(url, data=data)
            if response.status_code == 200:
                logger.info("Telegram message sent successfully")
                return True
            else:
                logger.error(f"Failed to send Telegram message: {response.text}")
                return False
        except Exception as e:
            logger.error(f"Error sending Telegram message: {str(e)}")
            return False
    
    def add_wallet(self, address, name=None, min_value_eth=0.1):
        try:
            address = Web3.to_checksum_address(address)
        """Add a wallet to track"""
        try:
            # Validate address
            if not w3.is_address(address):
                logger.error(f"Invalid Ethereum address: {address}")
                return False
            
            # Get initial balance
            balance_wei = w3.eth.get_balance(Web3.to_checksum_address(address))
            balance_eth = w3.from_wei(balance_wei, 'ether')
            
            wallet_name = name or f"Wallet_{len(self.tracked_wallets) + 1}"
            
            self.tracked_wallets[address.lower()] = {
                'name': wallet_name,
                'address': address,
                'min_value_eth': min_value_eth,
                'balance_eth': float(balance_eth),
                'added_at': datetime.now().isoformat()
            }
            
            message = f"✅ <b>Wallet Added</b>\n" \
                     f"Name: {wallet_name}\n" \
                     f"Address: <code>{address}</code>\n" \
                     f"Balance: {balance_eth:.4f} ETH\n" \
                     f"Alert Threshold: {min_value_eth} ETH"
            
            self.send_telegram_message(message)
            logger.info(f"Added wallet: {wallet_name} ({address})")
            return True
            
        except Exception as e:
            logger.error(f"Error adding wallet: {str(e)}")
            return False
    
    def get_wallet_balance(self, address):
        """Get current balance of a wallet"""
        try:
            balance_wei = w3.eth.get_balance(Web3.to_checksum_address(address))
            balance_eth = w3.from_wei(balance_wei, 'ether')
            return float(balance_eth)
        except Exception as e:
            logger.error(f"Error getting balance for {address}: {str(e)}")
            return 0
    
    def check_balance_changes(self):
        """Check for balance changes in tracked wallets"""
        for address, wallet_info in self.tracked_wallets.items():
            try:
                current_balance = self.get_wallet_balance(address)
                previous_balance = wallet_info['balance_eth']
                
                if abs(current_balance - previous_balance) > 0.001:  # Significant change
                    change = current_balance - previous_balance
                    emoji = "📈" if change > 0 else "📉"
                    
                    message = f"{emoji} <b>Balance Change Alert</b>\n" \
                             f"Wallet: {wallet_info['name']}\n" \
                             f"Address: <code>{address}</code>\n" \
                             f"Previous: {previous_balance:.4f} ETH\n" \
                             f"Current: {current_balance:.4f} ETH\n" \
                             f"Change: {change:+.4f} ETH"
                    
                    self.send_telegram_message(message)
                    
                    # Update stored balance
                    self.tracked_wallets[address]['balance_eth'] = current_balance
                    
            except Exception as e:
                logger.error(f"Error checking balance for {address}: {str(e)}")
    
    def process_block_transactions(self, block_number):
        """Process transactions in a block"""
        try:
            block = w3.eth.get_block(block_number, full_transactions=True)
            
            for tx in block.transactions:
                self.check_transaction(tx, block.timestamp)
                
        except Exception as e:
            logger.error(f"Error processing block {block_number}: {str(e)}")
    
    def check_transaction(self, tx, block_timestamp):
        """Check if transaction involves tracked wallets"""
        try:
            tx_from = tx['from'].lower() if tx['from'] else ''
            tx_to = tx['to'].lower() if tx['to'] else ''
            tx_value = tx['value']
            tx_value_eth = w3.from_wei(tx_value, 'ether')
            
            # Check if transaction involves any tracked wallet
            for wallet_address, wallet_info in self.tracked_wallets.items():
                if wallet_address in [tx_from, tx_to]:
                    
                    # Check if transaction meets minimum value threshold
                    if float(tx_value_eth) >= wallet_info['min_value_eth']:
                        
                        # Determine transaction direction
                        if wallet_address == tx_from:
                            direction = "📤 Outgoing"
                            other_address = tx_to
                        else:
                            direction = "📥 Incoming"
                            other_address = tx_from
                        
                        # Get transaction receipt for status
                        try:
                            receipt = w3.eth.get_transaction_receipt(tx['hash'])
                            status = "✅ Success" if receipt['status'] == 1 else "❌ Failed"
                        except:
                            status = "⏳ Pending"
                        
                        # Format timestamp
                        tx_time = datetime.fromtimestamp(block_timestamp).strftime('%Y-%m-%d %H:%M:%S')
                        
                        message = f"🚨 <b>Transaction Alert</b>\n" \
                                 f"Wallet: {wallet_info['name']}\n" \
                                 f"Direction: {direction}\n" \
                                 f"Amount: <b>{tx_value_eth:.4f} ETH</b>\n" \
                                 f"Other Address: <code>{other_address}</code>\n" \
                                 f"Status: {status}\n" \
                                 f"Time: {tx_time}\n" \
                                 f"Hash: <code>{tx['hash'].hex()}</code>\n" \
                                 f"<a href='https://etherscan.io/tx/{tx['hash'].hex()}'>View on Etherscan</a>"
                        
                        self.send_telegram_message(message)
                        logger.info(f"Transaction alert sent for {wallet_info['name']}")
                        
        except Exception as e:
            logger.error(f"Error checking transaction: {str(e)}")
    
    def start_monitoring(self):
        """Start monitoring blockchain"""
        if not w3.is_connected():
            logger.error("Not connected to Ethereum network")
            return False
        
        if len(self.tracked_wallets) == 0:
            logger.warning("No wallets to track")
            return False
        
        self.running = True
        self.last_processed_block = w3.eth.block_number
        
        start_message = f"🤖 <b>Wallet Tracker Started</b>\n" \
                       f"Monitoring {len(self.tracked_wallets)} wallets\n" \
                       f"Starting from block: {self.last_processed_block}"
        
        self.send_telegram_message(start_message)
        logger.info(f"Started monitoring from block {self.last_processed_block}")
        
        try:
            while self.running:
                current_block = w3.eth.block_number
                
                # Process new blocks
                if current_block > self.last_processed_block:
                    for block_num in range(self.last_processed_block + 1, current_block + 1):
                        logger.info(f"Processing block {block_num}")
                        self.process_block_transactions(block_num)
                    
                    self.last_processed_block = current_block
                
                # Check balance changes every few iterations
                if current_block % 5 == 0:  # Every ~1 minute
                    self.check_balance_changes()
                
                # Wait before next check
                time.sleep(12)  # ~12 seconds for Ethereum block time
                
        except KeyboardInterrupt:
            logger.info("Monitoring stopped by user")
            self.running = False
        except Exception as e:
            logger.error(f"Error in monitoring loop: {str(e)}")
            error_message = f"❌ <b>Monitoring Error</b>\n{str(e)}"
            self.send_telegram_message(error_message)
    
    def stop_monitoring(self):
        """Stop monitoring"""
        self.running = False
        logger.info("Monitoring stopped")
    
    def show_status(self):
        """Show current status"""
        try:
            current_block = w3.eth.block_number
            connection_status = "✅ Connected" if w3.is_connected() else "❌ Disconnected"
            
            message = f"📊 <b>Tracker Status</b>\n" \
                     f"Connection: {connection_status}\n" \
                     f"Current Block: {current_block:,}\n" \
                     f"Tracked Wallets: {len(self.tracked_wallets)}\n" \
                     f"Monitoring: {'✅ Active' if self.running else '❌ Inactive'}"
            
            if self.tracked_wallets:
                message += "\n\n<b>Tracked Wallets:</b>"
                for address, wallet_info in self.tracked_wallets.items():
                    balance = self.get_wallet_balance(address)
                    message += f"\n• {wallet_info['name']}: {balance:.4f} ETH"
            
            self.send_telegram_message(message)
            
        except Exception as e:
            logger.error(f"Error showing status: {str(e)}")

def main():
    """Main function with interactive menu"""
    tracker = SimpleWalletTracker()
    
    # Send startup message
    tracker.send_telegram_message("🚀 <b>Wallet Tracker Bot Started</b>\nReady to monitor Ethereum wallets!")
    
    print("=== Simple Ethereum Wallet Tracker ===")
    print("Commands:")
    print("1. Add wallet")
    print("2. Show status")
    print("3. Start monitoring")
    print("4. Stop monitoring")
    print("5. Exit")
    
    while True:
        try:
            choice = input("\nEnter command (1-5): ").strip()
            
            if choice == '1':
                address = input("Enter wallet address: ").strip()
                name = input("Enter wallet name (optional): ").strip() or None
                try:
                    min_value = float(input("Enter minimum alert value in ETH (default 0.1): ").strip() or "0.1")
                except ValueError:
                    min_value = 0.1
                
                tracker.add_wallet(address, name, min_value)
                
            elif choice == '2':
                tracker.show_status()
                
            elif choice == '3':
                print("Starting monitoring... (Press Ctrl+C to stop)")
                tracker.start_monitoring()
                
            elif choice == '4':
                tracker.stop_monitoring()
                
            elif choice == '5':
                tracker.stop_monitoring()
                tracker.send_telegram_message("👋 <b>Wallet Tracker Stopped</b>\nBot is now offline.")
                print("Goodbye!")
                break
                
            else:
                print("Invalid choice. Please enter 1-5.")
                
        except KeyboardInterrupt:
            print("\nStopping...")
            tracker.stop_monitoring()
            break
        except Exception as e:
            logger.error(f"Error in main loop: {str(e)}")

if __name__ == "__main__":
    tracker = SimpleWalletTracker()
    tracker.add_wallet("0x870585E3AF9dA7ff5dcd8f897EA0756f60F69cc1", "MyWallet")
    tracker.start_monitoring()