import base64
import json
import struct
import hashlib
from solana.transaction import Transaction
from solders.transaction import VersionedTransaction
from solders.pubkey import Pubkey
import sys

def load_idl(file_path):
    with open(file_path, 'r') as f:
        return json.load(f)

def load_transaction(file_path):
    with open(file_path, 'r') as f:
        data = json.load(f)
    return data

def decode_instruction(ix_data, ix_def):
    args = {}
    offset = 8  # Skip 8-byte discriminator

    for arg in ix_def['args']:
        if arg['type'] == 'u64':
            value = struct.unpack_from('<Q', ix_data, offset)[0]
            offset += 8
        elif arg['type'] == 'publicKey':
            value = ix_data[offset:offset+32].hex()
            offset += 32
        elif arg['type'] == 'string':
            length = struct.unpack_from('<I', ix_data, offset)[0]
            offset += 4
            value = ix_data[offset:offset+length].decode('utf-8')
            offset += length
        else:
            raise ValueError(f"Unsupported type: {arg['type']}")
        
        args[arg['name']] = value

    return args

def calculate_discriminator(instruction_name):
    sha = hashlib.sha256()
    sha.update(instruction_name.encode('utf-8'))
    discriminator_bytes = sha.digest()[:8]
    discriminator = struct.unpack('<Q', discriminator_bytes)[0]
    return discriminator

def decode_transaction(tx_data, idl):
    decoded_instructions = []
    
    # Decode the base64 transaction data
    tx_data_decoded = base64.b64decode(tx_data['transaction'][0])
    
    # Check if it's a versioned transaction
    if tx_data.get('version') == 0:
        # Use solders library for versioned transactions
        transaction = VersionedTransaction.from_bytes(tx_data_decoded)
        instructions = transaction.message.instructions
        account_keys = transaction.message.account_keys
        print("Versioned transaction detected")
    else:
        # Use legacy deserialization for older transactions
        transaction = Transaction.deserialize(tx_data_decoded)
        instructions = transaction.instructions
        account_keys = transaction.message.account_keys
        print("Legacy transaction detected")
    
    print(f"Number of instructions: {len(instructions)}")
    
    for idx, ix in enumerate(instructions):
        program_id = str(account_keys[ix.program_id_index])
        print(f"\nInstruction {idx}:")
        print(f"Program ID: {program_id}")
        print(f"IDL program address: {idl['metadata']['address']}")
        
        if program_id == idl['metadata']['address']:
            ix_data = bytes(ix.data)
            discriminator = struct.unpack('<Q', ix_data[:8])[0]
            
            print(f"Discriminator: {discriminator:016x}")
            
            for idl_ix in idl['instructions']:
                idl_discriminator = calculate_discriminator(f"global:{idl_ix['name']}")
                print(f"Checking against IDL instruction: {idl_ix['name']} with discriminator {idl_discriminator:016x}")
                
                if discriminator == idl_discriminator:
                    decoded_args = decode_instruction(ix_data, idl_ix)
                    accounts = [str(account_keys[acc_idx]) for acc_idx in ix.accounts]
                    decoded_instructions.append({
                        'name': idl_ix['name'],
                        'args': decoded_args,
                        'accounts': accounts,
                        'program': program_id
                    })
                    break
            else:
                decoded_instructions.append({
                    'name': 'Unknown',
                    'data': ix_data.hex(),
                    'accounts': [str(account_keys[acc_idx]) for acc_idx in ix.accounts],
                    'program': program_id
                })
        else:
            instruction_name = 'External'
            if program_id == 'ComputeBudget111111111111111111111111111111':
                if ix.data[:1] == b'\x03':
                    instruction_name = 'ComputeBudget: Set compute unit limit'
                elif ix.data[:1] == b'\x02':
                    instruction_name = 'ComputeBudget: Set compute unit price'
            elif program_id == 'ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL':
                instruction_name = 'Associated Token Account: Create'
            
            decoded_instructions.append({
                'name': instruction_name,
                'programId': program_id,
                'data': bytes(ix.data).hex(),
                'accounts': [str(account_keys[acc_idx]) for acc_idx in ix.accounts]
            })

    return decoded_instructions

if len(sys.argv) != 2:
    print("Usage: python decode_fromBlock.py <transaction_file_path>")
    sys.exit(1)

tx_file_path = sys.argv[1]
idl = load_idl('../idl/pump_fun_idl.json')
tx_data = load_transaction(tx_file_path)

decoded_instructions = decode_transaction(tx_data, idl)
print(json.dumps(decoded_instructions, indent=2))