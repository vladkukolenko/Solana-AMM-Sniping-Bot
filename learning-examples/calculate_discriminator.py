import hashlib
import struct

# https://book.anchor-lang.com/anchor_bts/discriminator.html
# Set the instruction name here
instruction_name = "account:BondingCurve"

def calculate_discriminator(instruction_name):
    # Create a SHA256 hash object
    sha = hashlib.sha256()
    
    # Update the hash with the instruction name
    sha.update(instruction_name.encode('utf-8'))
    
    # Get the first 8 bytes of the hash
    discriminator_bytes = sha.digest()[:8]
    
    # Convert the bytes to a 64-bit unsigned integer (little-endian)
    discriminator = struct.unpack('<Q', discriminator_bytes)[0]
    
    return discriminator

# Calculate the discriminator for the specified instruction
discriminator = calculate_discriminator(instruction_name)

print(f"Discriminator for '{instruction_name}' instruction: {discriminator}")

# global:buy discriminator - 16927863322537952870
# global:sell discriminator - 12502976635542562355
# global:create discriminator - 8576854823835016728
# account:BondingCurve discriminator - 6966180631402821399