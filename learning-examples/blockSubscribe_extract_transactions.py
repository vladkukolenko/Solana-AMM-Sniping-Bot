import asyncio
import hashlib
import json
import os
import sys
import websockets

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from config import WSS_ENDPOINT, PUMP_PROGRAM

async def save_transaction(tx_data, tx_signature):
    os.makedirs("blockSubscribe-transactions", exist_ok=True)
    hashed_signature = hashlib.sha256(tx_signature.encode()).hexdigest()
    file_path = os.path.join("blockSubscribe-transactions", f"{hashed_signature}.json")
    with open(file_path, 'w') as f:
        json.dump(tx_data, f, indent=2)
    print(f"Saved transaction: {hashed_signature[:8]}...")

async def listen_for_transactions():
    async with websockets.connect(WSS_ENDPOINT) as websocket:
        subscription_message = json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "blockSubscribe",
            "params": [
                {"mentionsAccountOrProgram": str(PUMP_PROGRAM)},
                {
                    "commitment": "confirmed",
                    "encoding": "base64",
                    "showRewards": False,
                    "transactionDetails": "full",
                    "maxSupportedTransactionVersion": 0
                }
            ]
        })
        await websocket.send(subscription_message)
        print(f"Subscribed to blocks mentioning program: {PUMP_PROGRAM}")

        while True:
            try:
                response = await websocket.recv()
                data = json.loads(response)
                
                if 'method' in data and data['method'] == 'blockNotification':
                    if 'params' in data and 'result' in data['params']:
                        block_data = data['params']['result']
                        if 'value' in block_data and 'block' in block_data['value']:
                            block = block_data['value']['block']
                            if 'transactions' in block:
                                transactions = block['transactions']
                                for tx in transactions:
                                    if isinstance(tx, dict) and 'transaction' in tx:
                                        if isinstance(tx['transaction'], list) and len(tx['transaction']) > 0:
                                            tx_signature = tx['transaction'][0]
                                        elif isinstance(tx['transaction'], dict) and 'signatures' in tx['transaction']:
                                            tx_signature = tx['transaction']['signatures'][0]
                                        else:
                                            continue
                                        await save_transaction(tx, tx_signature)
                elif 'result' in data:
                    print(f"Subscription confirmed")
            except Exception as e:
                print(f"An error occurred: {str(e)}")

if __name__ == "__main__":
    asyncio.run(listen_for_transactions())