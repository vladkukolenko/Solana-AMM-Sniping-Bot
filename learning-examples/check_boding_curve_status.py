import asyncio
import struct
from typing import Final
from construct import Struct, Int64ul, Flag
from solana.rpc.async_api import AsyncClient
from solders.pubkey import Pubkey
import argparse
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from config import RPC_ENDPOINT, PUMP_PROGRAM

# Constants
EXPECTED_DISCRIMINATOR: Final[bytes] = struct.pack("<Q", 6966180631402821399)

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

def get_associated_bonding_curve_address(mint: Pubkey, program_id: Pubkey) -> tuple[Pubkey, int]:
    """
    Derives the associated bonding curve address for a given mint
    """
    return Pubkey.find_program_address(
        [
            b"bonding-curve",
            bytes(mint)
        ],
        program_id
    )

async def get_bonding_curve_state(conn: AsyncClient, curve_address: Pubkey) -> BondingCurveState:
    response = await conn.get_account_info(curve_address)
    if not response.value or not response.value.data:
        raise ValueError("Invalid curve state: No data")

    data = response.value.data
    if data[:8] != EXPECTED_DISCRIMINATOR:
        raise ValueError("Invalid curve state discriminator")

    return BondingCurveState(data)

async def check_token_status(mint_address: str) -> None:
    try:
        mint = Pubkey.from_string(mint_address)
        
        # Get the associated bonding curve address
        bonding_curve_address, bump = get_associated_bonding_curve_address(mint, PUMP_PROGRAM)
        
        print("\nToken Status:")
        print("-" * 50)
        print(f"Token Mint:              {mint}")
        print(f"Associated Bonding Curve: {bonding_curve_address}")
        print(f"Bump Seed:               {bump}")
        print("-" * 50)
        
        # Check completion status
        async with AsyncClient(RPC_ENDPOINT) as client:
            try:
                curve_state = await get_bonding_curve_state(client, bonding_curve_address)
                
                print("\nBonding Curve Status:")
                print("-" * 50)
                print(f"Completion Status: {'Completed' if curve_state.complete else 'Not Completed'}")
                if curve_state.complete:
                    print("\nNote: This bonding curve has completed and liquidity has been migrated to Raydium.")
                print("-" * 50)
                
            except ValueError as e:
                print(f"\nError accessing bonding curve: {e}")
            
    except ValueError as e:
        print(f"\nError: Invalid address format - {e}")
    except Exception as e:
        print(f"\nUnexpected error: {e}")

def main():
    parser = argparse.ArgumentParser(description='Check token bonding curve status')
    parser.add_argument('mint_address', help='The token mint address')
    
    args = parser.parse_args()
    asyncio.run(check_token_status(args.mint_address))

if __name__ == "__main__":
    main()