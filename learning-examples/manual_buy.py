import asyncio
import json
import base64
import struct
import base58
import os

from solana.transaction import Message
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed
from solana.rpc.types import TxOpts

from solders.pubkey import Pubkey
from solders.keypair import Keypair
from solders.instruction import Instruction, AccountMeta
from solders.system_program import TransferParams, transfer
from solders.transaction import VersionedTransaction, Transaction
from solders.compute_budget import set_compute_unit_price

import spl.token.instructions as spl_token
from spl.token.instructions import get_associated_token_address

import websockets
import hashlib
from construct import Struct, Int64ul, Flag

# Here and later all the discriminators are precalculated. See learning-examples/discriminator.py
EXPECTED_DISCRIMINATOR = struct.pack("<Q", 6966180631402821399)
TOKEN_DECIMALS = 6

# Global constants
PUMP_PROGRAM = Pubkey.from_string("6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P")
PUMP_GLOBAL = Pubkey.from_string("4wTV1YmiEkRvAtNtsSGPtUrqRYQMe5SKy2uB4Jjaxnjf")
PUMP_EVENT_AUTHORITY = Pubkey.from_string("Ce6TQqeHC9p8KetsN6JsjHK7UTZk7nasjjnr7XxXp9F1")
PUMP_FEE = Pubkey.from_string("CebN5WGQ4jvEPvsVU4EoHEpgzq1VV7AbicfhtW4xC9iM")
SYSTEM_PROGRAM = Pubkey.from_string("11111111111111111111111111111111")
SYSTEM_TOKEN_PROGRAM = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
SYSTEM_ASSOCIATED_TOKEN_ACCOUNT_PROGRAM = Pubkey.from_string("ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL")
SYSTEM_RENT = Pubkey.from_string("SysvarRent111111111111111111111111111111111")
SOL = Pubkey.from_string("So11111111111111111111111111111111111111112")
LAMPORTS_PER_SOL = 1_000_000_000

# RPC ENDPOINTS
RPC_ENDPOINT = "ENTER_YOUR_CHAINSTACK_HTTP_ENDPOINT"
RPC_WEBSOCKET = "ENTER_YOUR_CHAINSTACK_WS_ENDPOINT"

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

async def buy_token(mint: Pubkey, bonding_curve: Pubkey, associated_bonding_curve: Pubkey, amount: float, slippage: float = 0.25, max_retries=5):
    private_key = base58.b58decode("ENTER_PRIVATE_KEY")
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

                    msg = Message([create_ata_ix], payer.pubkey())
                    tx_ata = await client.send_transaction(
                        Transaction([payer], msg, (await client.get_latest_blockhash()).value.blockhash),
                        opts=TxOpts(skip_preflight=True, preflight_commitment=Confirmed)
                        )
                    
                    await client.confirm_transaction(tx_ata.value, commitment="confirmed")

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

                msg = Message([set_compute_unit_price(1_000), buy_ix], payer.pubkey())
                tx_buy = await client.send_transaction(
                    Transaction([payer], msg, (await client.get_latest_blockhash()).value.blockhash),
                    opts=TxOpts(skip_preflight=True, preflight_commitment=Confirmed)
                    )

                print(f"Transaction sent: https://explorer.solana.com/tx/{tx_buy.value}")

                await client.confirm_transaction(tx_buy.value, commitment="confirmed")
                print("Transaction confirmed")
                return  # Success, exit the function

            except Exception as e:
                print(f"Attempt {attempt + 1} failed: {str(e)[:50]}")
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt
                    print(f"Retrying in {wait_time} seconds...")
                    await asyncio.sleep(wait_time)
                else:
                    print("Max retries reached. Unable to complete the transaction.")

def load_idl(file_path):
    with open(file_path, 'r') as f:
        return json.load(f)

def calculate_discriminator(instruction_name):
    sha = hashlib.sha256()
    sha.update(instruction_name.encode('utf-8'))
    return struct.unpack('<Q', sha.digest()[:8])[0]

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

async def listen_for_create_transaction():
    idl_path = os.path.join(os.path.dirname(__file__), '..', 'idl', 'pump_fun_idl.json')
    idl = load_idl(idl_path)
    create_discriminator = calculate_discriminator("global:create")
    
    async with websockets.connect(RPC_WEBSOCKET) as websocket:
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
            response = await websocket.recv()
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

async def main():
    print("Waiting for a new token creation...")
    token_data = await listen_for_create_transaction()
    print("New token created:")
    print(json.dumps(token_data, indent=2))

    sleep_duration_sec = 15
    print(f"Waiting for {sleep_duration_sec} seconds for things to stabilize...")
    await asyncio.sleep(sleep_duration_sec)

    mint = Pubkey.from_string(token_data['mint'])
    bonding_curve = Pubkey.from_string(token_data['bondingCurve'])
    associated_bonding_curve = Pubkey.from_string(token_data['associatedBondingCurve'])

    # Fetch the token price
    async with AsyncClient(RPC_ENDPOINT) as client:
        curve_state = await get_pump_curve_state(client, bonding_curve)
        token_price_sol = calculate_pump_curve_price(curve_state)

    # Amount of SOL to spend (adjust as needed)
    amount = 0.00001  # 0.00001 SOL
    slippage = 0.3  # 30% slippage tolerance

    print(f"Bonding curve address: {bonding_curve}")
    print(f"Token price: {token_price_sol:.10f} SOL")
    print(f"Buying {amount:.6f} SOL worth of the new token with {slippage*100:.1f}% slippage tolerance...")
    await buy_token(mint, bonding_curve, associated_bonding_curve, amount, slippage)

if __name__ == "__main__":
    asyncio.run(main())