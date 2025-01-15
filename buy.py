import asyncio
import json
import base64
import struct
import base58
import hashlib
import websockets
import time

from solana.rpc.async_api import AsyncClient
from solana.transaction import Transaction
from solana.rpc.commitment import Confirmed
from solana.rpc.types import TxOpts

from solders.pubkey import Pubkey
from solders.keypair import Keypair
from solders.instruction import Instruction, AccountMeta
from solders.system_program import TransferParams, transfer
from solders.transaction import VersionedTransaction

from spl.token.instructions import get_associated_token_address
import spl.token.instructions as spl_token

from config import *

from construct import Struct, Int64ul, Flag

# Here and later all the discriminators are precalculated. See learning-examples/discriminator.py
EXPECTED_DISCRIMINATOR = struct.pack("<Q", 6966180631402821399)
TOKEN_DECIMALS = 6

class BondingCurveState:
    _STRUCT = Struct(
        "virtual_token_reserves" / Int64ul,
        "virtual_sol_reserves" / Int64ul,
        "real_token_reserves" / Int64ul,
        "real_sol_reserves" / Int64ul,
        "token_total_supply" / Int64ul,
        "complete" / Flag
    )

    def __init__(self, data: bytes) -> None:
        parsed = self._STRUCT.parse(data[8:])
        self.__dict__.update(parsed)

async def get_pump_curve_state(conn: AsyncClient, curve_address: Pubkey) -> BondingCurveState:
    response = await conn.get_account_info(curve_address)
    if not response.value or not response.value.data:
        raise ValueError("Invalid curve state: No data")

    data = response.value.data
    if data[:8] != EXPECTED_DISCRIMINATOR:
        raise ValueError("Invalid curve state discriminator")

    return BondingCurveState(data)

def calculate_pump_curve_price(curve_state: BondingCurveState) -> float:
    if curve_state.virtual_token_reserves <= 0 or curve_state.virtual_sol_reserves <= 0:
        raise ValueError("Invalid reserve state")

    return (curve_state.virtual_sol_reserves / LAMPORTS_PER_SOL) / (curve_state.virtual_token_reserves / 10 ** TOKEN_DECIMALS)

async def buy_token(mint: Pubkey, bonding_curve: Pubkey, associated_bonding_curve: Pubkey, amount: float, slippage: float = 0.01, max_retries=5):
    private_key = base58.b58decode(PRIVATE_KEY)
    payer = Keypair.from_bytes(private_key)

    async with AsyncClient(RPC_ENDPOINT) as client:
        associated_token_account = get_associated_token_address(payer.pubkey(), mint)
        amount_lamports = int(amount * LAMPORTS_PER_SOL)

        # Fetch the token price
        curve_state = await get_pump_curve_state(client, bonding_curve)
        token_price_sol = calculate_pump_curve_price(curve_state)
        token_amount = amount / token_price_sol

        # Calculate maximum SOL to spend with slippage
        max_amount_lamports = int(amount_lamports * (1 + slippage))

        # Create associated token account with retries
        for ata_attempt in range(max_retries):
            try:
                account_info = await client.get_account_info(associated_token_account)
                if account_info.value is None:
                    print(f"Creating associated token account (Attempt {ata_attempt + 1})...")
                    create_ata_ix = spl_token.create_associated_token_account(
                        payer=payer.pubkey(),
                        owner=payer.pubkey(),
                        mint=mint
                    )
                    create_ata_tx = Transaction()
                    create_ata_tx.add(create_ata_ix)
                    recent_blockhash = await client.get_latest_blockhash()
                    create_ata_tx.recent_blockhash = recent_blockhash.value.blockhash
                    await client.send_transaction(create_ata_tx, payer)
                    print("Associated token account created.")
                    print(f"Associated token account address: {associated_token_account}")
                    break
                else:
                    print("Associated token account already exists.")
                    print(f"Associated token account address: {associated_token_account}")
                    break
            except Exception as e:
                print(f"Attempt {ata_attempt + 1} to create associated token account failed: {str(e)}")
                if ata_attempt < max_retries - 1:
                    wait_time = 2 ** ata_attempt
                    print(f"Retrying in {wait_time} seconds...")
                    await asyncio.sleep(wait_time)
                else:
                    print("Max retries reached. Unable to create associated token account.")
                    return

        # Continue with the buy transaction
        for attempt in range(max_retries):
            try:
                accounts = [
                    AccountMeta(pubkey=PUMP_GLOBAL, is_signer=False, is_writable=False),
                    AccountMeta(pubkey=PUMP_FEE, is_signer=False, is_writable=True),
                    AccountMeta(pubkey=mint, is_signer=False, is_writable=False),
                    AccountMeta(pubkey=bonding_curve, is_signer=False, is_writable=True),
                    AccountMeta(pubkey=associated_bonding_curve, is_signer=False, is_writable=True),
                    AccountMeta(pubkey=associated_token_account, is_signer=False, is_writable=True),
                    AccountMeta(pubkey=payer.pubkey(), is_signer=True, is_writable=True),
                    AccountMeta(pubkey=SYSTEM_PROGRAM, is_signer=False, is_writable=False),
                    AccountMeta(pubkey=SYSTEM_TOKEN_PROGRAM, is_signer=False, is_writable=False),
                    AccountMeta(pubkey=SYSTEM_RENT, is_signer=False, is_writable=False),
                    AccountMeta(pubkey=PUMP_EVENT_AUTHORITY, is_signer=False, is_writable=False),
                    AccountMeta(pubkey=PUMP_PROGRAM, is_signer=False, is_writable=False),
                ]

                discriminator = struct.pack("<Q", 16927863322537952870)
                data = discriminator + struct.pack("<Q", int(token_amount * 10**6)) + struct.pack("<Q", max_amount_lamports)
                buy_ix = Instruction(PUMP_PROGRAM, data, accounts)

                recent_blockhash = await client.get_latest_blockhash()
                transaction = Transaction()
                transaction.add(buy_ix)
                transaction.recent_blockhash = recent_blockhash.value.blockhash

                tx = await client.send_transaction(
                    transaction,
                    payer,
                    opts=TxOpts(skip_preflight=True, preflight_commitment=Confirmed),
                )

                print(f"Transaction sent: https://explorer.solana.com/tx/{tx.value}")

                await client.confirm_transaction(tx.value, commitment="confirmed")
                print("Transaction confirmed")
                return tx.value

            except Exception as e:
                print(f"Attempt {attempt + 1} failed: {str(e)}")
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt
                    print(f"Retrying in {wait_time} seconds...")
                    await asyncio.sleep(wait_time)
                else:
                    print("Max retries reached. Unable to complete the transaction.")

def load_idl(file_path):
    with open(file_path, 'r') as f:
        return json.load(f)

def decode_create_instruction(ix_data, ix_def, accounts):
    args = {}
    offset = 8  # Skip 8-byte discriminator

    for arg in ix_def['args']:
        if arg['type'] == 'string':
            length = struct.unpack_from('<I', ix_data, offset)[0]
            offset += 4
            value = ix_data[offset:offset+length].decode('utf-8')
            offset += length
        elif arg['type'] == 'publicKey':
            value = base64.b64encode(ix_data[offset:offset+32]).decode('utf-8')
            offset += 32
        else:
            raise ValueError(f"Unsupported type: {arg['type']}")
        
        args[arg['name']] = value

    # Add accounts
    args['mint'] = str(accounts[0])
    args['bondingCurve'] = str(accounts[2])
    args['associatedBondingCurve'] = str(accounts[3])
    args['user'] = str(accounts[7])

    return args

async def listen_for_create_transaction(websocket):
    idl = load_idl('idl/pump_fun_idl.json')
    create_discriminator = 8576854823835016728
    
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

    ping_interval = 20
    last_ping_time = time.time()

    while True:
        try:
            current_time = time.time()
            if current_time - last_ping_time > ping_interval:
                await websocket.ping()
                last_ping_time = current_time

            response = await asyncio.wait_for(websocket.recv(), timeout=30)
            data = json.loads(response)
            
            if 'method' in data and data['method'] == 'blockNotification':
                if 'params' in data and 'result' in data['params']:
                    block_data = data['params']['result']
                    if 'value' in block_data and 'block' in block_data['value']:
                        block = block_data['value']['block']
                        if 'transactions' in block:
                            for tx in block['transactions']:
                                if isinstance(tx, dict) and 'transaction' in tx:
                                    tx_data_decoded = base64.b64decode(tx['transaction'][0])
                                    transaction = VersionedTransaction.from_bytes(tx_data_decoded)
                                    
                                    for ix in transaction.message.instructions:
                                        if str(transaction.message.account_keys[ix.program_id_index]) == str(PUMP_PROGRAM):
                                            ix_data = bytes(ix.data)
                                            discriminator = struct.unpack('<Q', ix_data[:8])[0]
                                            
                                            if discriminator == create_discriminator:
                                                create_ix = next(instr for instr in idl['instructions'] if instr['name'] == 'create')
                                                account_keys = [str(transaction.message.account_keys[index]) for index in ix.accounts]
                                                decoded_args = decode_create_instruction(ix_data, create_ix, account_keys)
                                                return decoded_args
        except asyncio.TimeoutError:
            print("No data received for 30 seconds, sending ping...")
            await websocket.ping()
            last_ping_time = time.time()
        except websockets.exceptions.ConnectionClosed:
            print("WebSocket connection closed. Reconnecting...")
            raise

async def main(yolo_mode=False):
    if yolo_mode:
        while True:
            try:
                async with websockets.connect(WSS_ENDPOINT) as websocket:
                    while True:
                        try:
                            await trade(websocket)
                        except websockets.exceptions.ConnectionClosed:
                            print("WebSocket connection closed. Reconnecting...")
                            break
                        except Exception as e:
                            print(f"An error occurred: {e}")
                        print("Waiting for 5 seconds before looking for the next token...")
                        await asyncio.sleep(5)
            except Exception as e:
                print(f"Connection error: {e}")
                print("Reconnecting in 5 seconds...")
                await asyncio.sleep(5)
    else:
        await trade()

if __name__ == "__main__":
    asyncio.run(main())