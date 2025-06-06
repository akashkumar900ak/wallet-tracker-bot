# Wallet Tracker Bot - Complete System
# Install required packages:
# pip install web3 flask requests python-telegram-bot asyncio websockets

import asyncio
import json
import logging
import threading
import time
from datetime import datetime
from typing import Dict, List, Set
import requests
from web3 import Web3
from flask import Flask, render_template, request, jsonify, redirect, url_for
import sqlite3
import os

# Configuration
ALCHEMY_API_KEY = "PB5RUs6zDOKs-lGvw4gfWFyo7pcyvQ5e"
ALCHEMY_URL = f"https://eth-mainnet.g.alchemy.com/v2/{ALCHEMY_API_KEY}"
TELEGRAM_BOT_TOKEN = "7866851849:AAFZ7mcwh1rtduuMF1EzlR14mqwrCn6H9zc"
TELEGRAM_CHAT_ID = "1114236546"

# Initialize Web3
w3 = Web3(Web3.HTTPProvider(ALCHEMY_URL))

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class DatabaseManager:
    def __init__(self):
        self.init_db()
    
    def init_db(self):
        conn = sqlite3.connect('wallet_tracker.db')
        cursor = conn.cursor()
        
        # Create wallets table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS wallets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                address TEXT UNIQUE NOT NULL,
                label TEXT,
                added_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                active BOOLEAN DEFAULT TRUE
            )
        ''')
        
        # Create transactions table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                wallet_address TEXT,
                tx_hash TEXT UNIQUE,
                block_number INTEGER,
                from_address TEXT,
                to_address TEXT,
                value TEXT,
                gas_used INTEGER,
                gas_price TEXT,
                timestamp TIMESTAMP,
                tx_type TEXT,
                FOREIGN KEY (wallet_address) REFERENCES wallets (address)
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def add_wallet(self, address: str, label: str = ""):
        conn = sqlite3.connect('wallet_tracker.db')
        cursor = conn.cursor()
        try:
            cursor.execute(
                "INSERT INTO wallets (address, label) VALUES (?, ?)",
                (address.lower(), label)
            )
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False
        finally:
            conn.close()
    
    def get_wallets(self) -> List[Dict]:
        conn = sqlite3.connect('wallet_tracker.db')
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM wallets WHERE active = TRUE")
        wallets = []
        for row in cursor.fetchall():
            wallets.append({
                'id': row[0],
                'address': row[1],
                'label': row[2],
                'added_date': row[3],
                'active': row[4]
            })
        conn.close()
        return wallets
    
    def remove_wallet(self, address: str):
        conn = sqlite3.connect('wallet_tracker.db')
        cursor = conn.cursor()
        cursor.execute("UPDATE wallets SET active = FALSE WHERE address = ?", (address.lower(),))
        conn.commit()
        conn.close()
    
    def save_transaction(self, tx_data: Dict):
        conn = sqlite3.connect('wallet_tracker.db')
        cursor = conn.cursor()
        try:
            cursor.execute('''
                INSERT INTO transactions 
                (wallet_address, tx_hash, block_number, from_address, to_address, 
                 value, gas_used, gas_price, timestamp, tx_type)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                tx_data['wallet_address'],
                tx_data['tx_hash'],
                tx_data['block_number'],
                tx_data['from_address'],
                tx_data['to_address'],
                tx_data['value'],
                tx_data['gas_used'],
                tx_data['gas_price'],
                tx_data['timestamp'],
                tx_data['tx_type']
            ))
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False
        finally:
            conn.close()
    
    def get_recent_transactions(self, limit: int = 50) -> List[Dict]:
        conn = sqlite3.connect('wallet_tracker.db')
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM transactions 
            ORDER BY timestamp DESC 
            LIMIT ?
        ''', (limit,))
        
        transactions = []
        for row in cursor.fetchall():
            transactions.append({
                'id': row[0],
                'wallet_address': row[1],
                'tx_hash': row[2],
                'block_number': row[3],
                'from_address': row[4],
                'to_address': row[5],
                'value': row[6],
                'gas_used': row[7],
                'gas_price': row[8],
                'timestamp': row[9],
                'tx_type': row[10]
            })
        conn.close()
        return transactions

class TelegramNotifier:
    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{bot_token}"
    
    def send_message(self, message: str):
        try:
            url = f"{self.base_url}/sendMessage"
            data = {
                'chat_id': self.chat_id,
                'text': message,
                'parse_mode': 'HTML'
            }
            response = requests.post(url, data=data)
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Failed to send Telegram message: {e}")
            return False
    
    def send_transaction_alert(self, tx_data: Dict):
        value_eth = float(tx_data['value']) / 10**18
        
        message = f"""
🔔 <b>New Transaction Alert</b>

💰 <b>Amount:</b> {value_eth:.6f} ETH
🏦 <b>Type:</b> {tx_data['tx_type']}
📤 <b>From:</b> <code>{tx_data['from_address'][:10]}...{tx_data['from_address'][-8:]}</code>
📥 <b>To:</b> <code>{tx_data['to_address'][:10]}...{tx_data['to_address'][-8:]}</code>
🔗 <b>Hash:</b> <code>{tx_data['tx_hash'][:10]}...{tx_data['tx_hash'][-8:]}</code>
⏰ <b>Time:</b> {tx_data['timestamp']}

<a href="https://etherscan.io/tx/{tx_data['tx_hash']}">View on Etherscan</a>
        """
        
        self.send_message(message.strip())

class WalletTracker:
    def __init__(self):
        self.db = DatabaseManager()
        self.telegram = TelegramNotifier(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
        self.tracked_wallets: Set[str] = set()
        self.last_block = 0
        self.running = False
        
    def start_tracking(self):
        self.running = True
        self.update_tracked_wallets()
        self.last_block = w3.eth.block_number
        
        # Start monitoring thread
        monitoring_thread = threading.Thread(target=self._monitor_loop)
        monitoring_thread.daemon = True
        monitoring_thread.start()
        
        logger.info("Wallet tracking started")
    
    def stop_tracking(self):
        self.running = False
        logger.info("Wallet tracking stopped")
    
    def update_tracked_wallets(self):
        wallets = self.db.get_wallets()
        self.tracked_wallets = {wallet['address'].lower() for wallet in wallets}
        logger.info(f"Updated tracked wallets: {len(self.tracked_wallets)} wallets")
    
    def _monitor_loop(self):
        while self.running:
            try:
                current_block = w3.eth.block_number
                
                if current_block > self.last_block:
                    self._scan_blocks(self.last_block + 1, current_block)
                    self.last_block = current_block
                
                time.sleep(10)  # Check every 10 seconds
                
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
                time.sleep(30)  # Wait longer on error
    
    def _scan_blocks(self, start_block: int, end_block: int):
        for block_num in range(start_block, end_block + 1):
            try:
                block = w3.eth.get_block(block_num, full_transactions=True)
                
                for tx in block.transactions:
                    self._process_transaction(tx, block)
                    
            except Exception as e:
                logger.error(f"Error scanning block {block_num}: {e}")
    
    def _process_transaction(self, tx, block):
        from_addr = tx['from'].lower() if tx['from'] else ""
        to_addr = tx['to'].lower() if tx['to'] else ""
        
        # Check if transaction involves any tracked wallet
        if from_addr in self.tracked_wallets or to_addr in self.tracked_wallets:
            tx_data = {
                'wallet_address': from_addr if from_addr in self.tracked_wallets else to_addr,
                'tx_hash': tx['hash'].hex(),
                'block_number': block['number'],
                'from_address': from_addr,
                'to_address': to_addr,
                'value': str(tx['value']),
                'gas_used': tx['gas'],
                'gas_price': str(tx['gasPrice']),
                'timestamp': datetime.fromtimestamp(block['timestamp']).isoformat(),
                'tx_type': 'Outgoing' if from_addr in self.tracked_wallets else 'Incoming'
            }
            
            # Save to database
            if self.db.save_transaction(tx_data):
                logger.info(f"New transaction detected: {tx_data['tx_hash']}")
                # Send Telegram alert
                self.telegram.send_transaction_alert(tx_data)
    
    def get_wallet_balance(self, address: str) -> float:
        try:
            balance_wei = w3.eth.get_balance(address)
            return float(balance_wei) / 10**18
        except Exception as e:
            logger.error(f"Error getting balance for {address}: {e}")
            return 0.0
    
    def get_wallet_info(self, address: str) -> Dict:
        balance = self.get_wallet_balance(address)
        return {
            'address': address,
            'balance': balance,
            'balance_usd': balance * self.get_eth_price()  # Simplified
        }
    
    def get_eth_price(self) -> float:
        try:
            response = requests.get('https://api.coingecko.com/api/v3/simple/price?ids=ethereum&vs_currencies=usd')
            return response.json()['ethereum']['usd']
        except:
            return 0.0

# Initialize tracker
tracker = WalletTracker()

# Flask Web Dashboard
app = Flask(__name__)
app.secret_key = 'your-secret-key-change-this'

@app.route('/')
def dashboard():
    wallets = tracker.db.get_wallets()
    wallet_info = []
    
    for wallet in wallets:
        info = tracker.get_wallet_info(wallet['address'])
        info.update(wallet)
        wallet_info.append(info)
    
    recent_transactions = tracker.db.get_recent_transactions(20)
    
    return render_template('dashboard.html', 
                         wallets=wallet_info, 
                         transactions=recent_transactions)

@app.route('/add_wallet', methods=['POST'])
def add_wallet():
    address = request.form.get('address', '').strip()
    label = request.form.get('label', '').strip()
    
    if not address:
        return jsonify({'error': 'Address is required'}), 400
    
    # Validate Ethereum address
    if not w3.is_address(address):
        return jsonify({'error': 'Invalid Ethereum address'}), 400
    
    # Add to database
    if tracker.db.add_wallet(address, label):
        tracker.update_tracked_wallets()
        return jsonify({'success': 'Wallet added successfully'})
    else:
        return jsonify({'error': 'Wallet already exists'}), 400

@app.route('/remove_wallet', methods=['POST'])
def remove_wallet():
    address = request.form.get('address', '').strip()
    
    if not address:
        return jsonify({'error': 'Address is required'}), 400
    
    tracker.db.remove_wallet(address)
    tracker.update_tracked_wallets()
    
    return jsonify({'success': 'Wallet removed successfully'})

@app.route('/api/wallet/<address>')
def get_wallet_info(address):
    info = tracker.get_wallet_info(address)
    return jsonify(info)

@app.route('/api/transactions')
def get_transactions():
    limit = request.args.get('limit', 50, type=int)
    transactions = tracker.db.get_recent_transactions(limit)
    return jsonify(transactions)

# HTML Template (save as templates/dashboard.html)
dashboard_html = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Wallet Tracker Dashboard</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://unpkg.com/alpinejs@3.x.x/dist/cdn.min.js" defer></script>
</head>
<body class="bg-gray-100 min-h-screen">
    <div class="container mx-auto px-4 py-8">
        <h1 class="text-3xl font-bold text-gray-800 mb-8">Wallet Tracker Dashboard</h1>
        
        <!-- Add Wallet Form -->
        <div class="bg-white rounded-lg shadow-md p-6 mb-8">
            <h2 class="text-xl font-semibold mb-4">Add New Wallet</h2>
            <form id="addWalletForm" class="flex gap-4">
                <input type="text" id="walletAddress" placeholder="Ethereum Address (0x...)" 
                       class="flex-1 px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500">
                <input type="text" id="walletLabel" placeholder="Label (optional)" 
                       class="w-48 px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500">
                <button type="submit" class="px-6 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700">
                    Add Wallet
                </button>
            </form>
        </div>

        <!-- Tracked Wallets -->
        <div class="bg-white rounded-lg shadow-md p-6 mb-8">
            <h2 class="text-xl font-semibold mb-4">Tracked Wallets</h2>
            <div class="overflow-x-auto">
                <table class="min-w-full divide-y divide-gray-200">
                    <thead class="bg-gray-50">
                        <tr>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Address</th>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Label</th>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Balance</th>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Actions</th>
                        </tr>
                    </thead>
                    <tbody class="bg-white divide-y divide-gray-200">
                        {% for wallet in wallets %}
                        <tr>
                            <td class="px-6 py-4 whitespace-nowrap text-sm font-mono text-gray-900">
                                {{ wallet.address[:10] }}...{{ wallet.address[-8:] }}
                            </td>
                            <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                                {{ wallet.label or 'No label' }}
                            </td>
                            <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                                {{ "%.6f"|format(wallet.balance) }} ETH
                            </td>
                            <td class="px-6 py-4 whitespace-nowrap text-sm font-medium">
                                <button onclick="removeWallet('{{ wallet.address }}')" 
                                        class="text-red-600 hover:text-red-900">Remove</button>
                            </td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>

        <!-- Recent Transactions -->
        <div class="bg-white rounded-lg shadow-md p-6">
            <h2 class="text-xl font-semibold mb-4">Recent Transactions</h2>
            <div class="overflow-x-auto">
                <table class="min-w-full divide-y divide-gray-200">
                    <thead class="bg-gray-50">
                        <tr>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Hash</th>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Type</th>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">From</th>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">To</th>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Value</th>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Time</th>
                        </tr>
                    </thead>
                    <tbody class="bg-white divide-y divide-gray-200">
                        {% for tx in transactions %}
                        <tr>
                            <td class="px-6 py-4 whitespace-nowrap text-sm font-mono text-gray-900">
                                <a href="https://etherscan.io/tx/{{ tx.tx_hash }}" target="_blank" class="text-blue-600 hover:text-blue-800">
                                    {{ tx.tx_hash[:10] }}...{{ tx.tx_hash[-8:] }}
                                </a>
                            </td>
                            <td class="px-6 py-4 whitespace-nowrap">
                                <span class="px-2 inline-flex text-xs leading-5 font-semibold rounded-full 
                                           {{ 'bg-green-100 text-green-800' if tx.tx_type == 'Incoming' else 'bg-red-100 text-red-800' }}">
                                    {{ tx.tx_type }}
                                </span>
                            </td>
                            <td class="px-6 py-4 whitespace-nowrap text-sm font-mono text-gray-900">
                                {{ tx.from_address[:10] }}...{{ tx.from_address[-8:] }}
                            </td>
                            <td class="px-6 py-4 whitespace-nowrap text-sm font-mono text-gray-900">
                                {{ tx.to_address[:10] }}...{{ tx.to_address[-8:] }}
                            </td>
                            <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                                {{ "%.6f"|format(tx.value|float / 10**18) }} ETH
                            </td>
                            <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                                {{ tx.timestamp[:19].replace('T', ' ') }}
                            </td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
    </div>

    <script>
        // Add wallet form submission
        document.getElementById('addWalletForm').addEventListener('submit', async function(e) {
            e.preventDefault();
            
            const address = document.getElementById('walletAddress').value;
            const label = document.getElementById('walletLabel').value;
            
            const formData = new FormData();
            formData.append('address', address);
            formData.append('label', label);
            
            try {
                const response = await fetch('/add_wallet', {
                    method: 'POST',
                    body: formData
                });
                
                const result = await response.json();
                
                if (response.ok) {
                    alert('Wallet added successfully!');
                    location.reload();
                } else {
                    alert('Error: ' + result.error);
                }
            } catch (error) {
                alert('Error adding wallet: ' + error.message);
            }
        });
        
        // Remove wallet function
        async function removeWallet(address) {
            if (!confirm('Are you sure you want to remove this wallet?')) {
                return;
            }
            
            const formData = new FormData();
            formData.append('address', address);
            
            try {
                const response = await fetch('/remove_wallet', {
                    method: 'POST',
                    body: formData
                });
                
                const result = await response.json();
                
                if (response.ok) {
                    alert('Wallet removed successfully!');
                    location.reload();
                } else {
                    alert('Error: ' + result.error);
                }
            } catch (error) {
                alert('Error removing wallet: ' + error.message);
            }
        }
        
        // Auto-refresh every 30 seconds
        setInterval(() => {
            location.reload();
        }, 30000);
    </script>
</body>
</html>
'''

if __name__ == '__main__':
    # Create templates directory and save HTML template (optional if already exists)
    os.makedirs('templates', exist_ok=True)
    if not os.path.exists('templates/dashboard.html'):
        with open('templates/dashboard.html', 'w') as f:
            f.write(dashboard_html)

    # Start the wallet tracker
    tracker.start_tracking()

    # Send startup notification
    tracker.telegram.send_message("🚀 Wallet Tracker Bot started successfully!")

    # Run Flask app with dynamic port
    port = int(os.environ.get('PORT', 5000))
    print(f"Starting Wallet Tracker Dashboard on port {port}...")
    print(f"Monitoring {len(tracker.tracked_wallets)} wallets")

    app.run(debug=True, host='0.0.0.0', port=port)
