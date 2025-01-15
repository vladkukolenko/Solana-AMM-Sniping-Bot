def create_wallet():
    keypair = Keypair()
    public_key = keypair.public_key
    private_key = list(keypair.secret_key)
    return {
        "public_key": str(public_key),
        "private_key": private_key
    }
