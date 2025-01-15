import json
import base58
from solana.transaction import Transaction
from solders.pubkey import Pubkey
import struct
import sys
import base64

import sys

if len(sys.argv) != 2:
    print("Usage: python decode_getTransaction.py <transaction_file_path>")
    sys.exit(1)

tx_file_path = sys.argv[1]

# Load the IDL
with open('../idl/pump_fun_idl.json', 'r') as f:
    idl = json.load(f)

# Load the transaction log
with open(tx_file_path, 'r') as f:
    tx_log = json.load(f)

# Extract the transaction data
tx_data = tx_log['result']['transaction']

print(json.dumps(tx_data, indent=2))

def decode_create_instruction(data):
    # The Create instruction has 3 string arguments: name, symbol, uri
    offset = 8  # Skip the 8-byte discriminator
    results = []
    for _ in range(3):
        length = struct.unpack_from("<I", data, offset)[0]
        offset += 4
        string_data = data[offset:offset+length].decode('utf-8')
        results.append(string_data)
        offset += length
    return {
        "name": results[0],
        "symbol": results[1],
        "uri": results[2]
    }

def decode_buy_instruction(data):
    # Assuming the buy instruction has a u64 argument for amount
    amount = struct.unpack_from("<Q", data, 8)[0]
    return {"amount": amount}

def decode_instruction_data(instruction, accounts, data):
    if instruction['name'] == 'create':
        return decode_create_instruction(data)
    elif instruction['name'] == 'buy':
        return decode_buy_instruction(data)
    else:
        return f"Unhandled instruction type: {instruction['name']}"

def find_matching_instruction(accounts, data):
    if 'instructions' not in idl:
        print("Warning: No instructions found in IDL")
        return None
    for instruction in idl['instructions']:
        if len(instruction['accounts']) == len(accounts):
            return instruction
    return None

# Parse the transaction
tx_message = tx_data['message']
instructions = tx_message['instructions']

for ix in instructions:
    program_id = ix.get('programId')
    accounts = ix.get('accounts', [])
    data = ix.get('data', '')
    
    if 'parsed' in ix:
        print(f"Parsed instruction: {ix['program']} - {ix['parsed']['type']}")
        print(f"Info: {json.dumps(ix['parsed']['info'], indent=2)}")
    elif program_id == idl['metadata']['address']:
        matching_instruction = find_matching_instruction(accounts, data)
        if matching_instruction:
            decoded_data = decode_instruction_data(matching_instruction, accounts, base58.b58decode(data))
            print(f"Instruction: {matching_instruction['name']}")
            print(f"Decoded data: {decoded_data}")
            
            print("\nAccounts:")
            for i, account in enumerate(accounts):
                account_info = matching_instruction['accounts'][i]
                print(f"  {account_info['name']}: {account}")
        else:
            print(f"Unable to match instruction for program {program_id}")
    else:
        print(f"Instruction for program: {program_id}")
        print(f"Data: {data}\n")

print("\nTransaction Information:")
print(f"Blockhash: {tx_message['recentBlockhash']}")
print(f"Fee payer: {tx_message['accountKeys'][0]['pubkey']}")
print(f"Signature: {tx_data['signatures'][0]}")