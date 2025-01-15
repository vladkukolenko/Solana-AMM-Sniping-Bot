# Import the necessary libraries import web3 from web3 import Web3, middleware, Account

# Connect to Ethereum node via Web3 provider = Web3.HTTPProvider("https://mainnet.infura.io/v3/< YOUR_API_KEY>") web3 = Web3(provider)

# Create a wallet object from the private key private_key = "<YOUR_API_KEY>" account = web3.eth.account.from_key(private_key)

# Connect to the wallet API via Web3.middleware.geth_poa_middleware w3 = Web3(middleware=geth_poa_middleware(provider)) w3.eth.default_account = account.address
