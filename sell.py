import asyncio
import json
import base64
import struct
import base58
from typing import Final

from solana.rpc.async_api import AsyncClient
from solana.transaction import Transaction
from solana.rpc.commitment import Confirmed
from solana.rpc.types import TxOpts

from solders.pubkey import Pubkey
from solders.keypair import Keypair
from solders.instruction import Instruction, AccountMeta
from solders.system_program import TransferParams, transfer

from spl.token.instructions import get_associated_token_address
import spl.token.instructions as spl_token

from construct import Struct, Int64ul, Flag

from config import *

# Here and later all the discriminators are precalculated. See learning-examples/discriminator.py
EXPECTED_DISCRIMINATOR: Final[bytes] = struct.pack("<Q", 6966180631402821399)
TOKEN_DECIMALS: Final[int] = 6

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

async def get_token_balance(conn: AsyncClient, associated_token_account: Pubkey):
    response = await conn.get_token_account_balance(associated_token_account)
    if response.value:
        return int(response.value.amount)
    return 0

async def sell_token(mint: Pubkey, bonding_curve: Pubkey, associated_bonding_curve: Pubkey, slippage: float = 0.25, max_retries=5):
    private_key = base58.b58decode(PRIVATE_KEY)
    payer = Keypair.from_bytes(private_key)

    async with AsyncClient(RPC_ENDPOINT) as client:
        associated_token_account = get_associated_token_address(payer.pubkey(), mint)
        
        # Get token balance
        token_balance = await get_token_balance(client, associated_token_account)
        token_balance_decimal = token_balance / 10**TOKEN_DECIMALS
        print(f"Token balance: {token_balance_decimal}")
        if token_balance == 0:
            print("No tokens to sell.")
            return

        # Fetch the token price
        curve_state = await get_pump_curve_state(client, bonding_curve)
        token_price_sol = calculate_pump_curve_price(curve_state)
        print(f"Price per Token: {token_price_sol:.20f} SOL")

        # Calculate minimum SOL output
        amount = token_balance
        min_sol_output = float(token_balance_decimal) * float(token_price_sol)
        slippage_factor = 1 - slippage
        min_sol_output = int((min_sol_output * slippage_factor) * LAMPORTS_PER_SOL)
        
        print(f"Selling {token_balance_decimal} tokens")
        print(f"Minimum SOL output: {min_sol_output / LAMPORTS_PER_SOL:.10f} SOL")

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
                    AccountMeta(pubkey=SYSTEM_ASSOCIATED_TOKEN_ACCOUNT_PROGRAM, is_signer=False, is_writable=False),
                    AccountMeta(pubkey=SYSTEM_TOKEN_PROGRAM, is_signer=False, is_writable=False),
                    AccountMeta(pubkey=PUMP_EVENT_AUTHORITY, is_signer=False, is_writable=False),
                    AccountMeta(pubkey=PUMP_PROGRAM, is_signer=False, is_writable=False),
                ]

                discriminator = struct.pack("<Q", 12502976635542562355)
                data = discriminator + struct.pack("<Q", amount) + struct.pack("<Q", min_sol_output)
                sell_ix = Instruction(PUMP_PROGRAM, data, accounts)

                recent_blockhash = await client.get_latest_blockhash()
                transaction = Transaction()
                transaction.add(sell_ix)
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