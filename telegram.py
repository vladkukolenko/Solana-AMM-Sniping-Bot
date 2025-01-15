# Telegram Bot Commands
@telegram_bot.message_handler(commands=['start'])
def start(message: Message):
    telegram_bot.reply_to(message, "Welcome to PumpTrader Bot for Solana! Use /help to see commands.")

@telegram_bot.message_handler(commands=['help'])
def help_command(message: Message):
    commands = """Available commands:
    /balance <wallet_address> <token_address> - Get token balance
    /pump <wallet_address> <token_address> <amount> <interval> <repeats> - Place pump orders
    /monitor <token_address> - Monitor token price
    /liquidity <wallet_address> <token_a_address> <token_b_address> <pool_address> <target_balance> - Manage liquidity
    /create_wallet - Create a new wallet
    """
    telegram_bot.reply_to(message, commands)

@telegram_bot.message_handler(commands=['balance'])
def balance_command(message: Message):
    try:
        _, wallet_address, token_address = message.text.split()
        balance = get_token_balance(wallet_address, token_address)
        telegram_bot.reply_to(message, f"Token balance: {balance}")
    except Exception as e:
        telegram_bot.reply_to(message, f"Error: {e}")

@telegram_bot.message_handler(commands=['pump'])
def pump_command(message: Message):
    try:
        _, wallet_address, token_address, amount, interval, repeats = message.text.split()
        place_pump_order(wallet_address, token_address, int(amount), int(interval), int(repeats))
        telegram_bot.reply_to(message, "Pump order executed!")
    except Exception as e:
        telegram_bot.reply_to(message, f"Error: {e}")

@telegram_bot.message_handler(commands=['monitor'])
def monitor_command(message: Message):
    try:
        _, token_address = message.text.split()
        monitor_price(token_address)  # Start monitoring (simplified for MVP)
    except Exception as e:
        telegram_bot.reply_to(message, f"Error: {e}")

@telegram_bot.message_handler(commands=['liquidity'])
def liquidity_command(message: Message):
    try:
        _, wallet_address, token_a_address, token_b_address, pool_address, target_balance = message.text.split()
        manage_liquidity(wallet_address, token_a_address, token_b_address, pool_address, int(target_balance))
        telegram_bot.reply_to(message, "Liquidity management executed!")
    except Exception as e:
        telegram_bot.reply_to(message, f"Error: {e}")

@telegram_bot.message_handler(commands=['create_wallet'])
def create_wallet_command(message: Message):
    try:
        wallet = create_wallet()
        response = f"New wallet created:\nPublic Key: {wallet['public_key']}\nPrivate Key: {wallet['private_key']}"
        telegram_bot.reply_to(message, response)
    except Exception as e:
        telegram_bot.reply_to(message, f"Error: {e}")

# Main loop
if __name__ == "__main__":
    print("Starting PumpTrader Bot...")
    telegram_bot.polling()
