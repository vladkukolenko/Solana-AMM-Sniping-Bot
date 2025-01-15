import random

class MeanReversionStrategy:
    def __init__(self, settings):
        self.settings = settings

    def decide(self, pair, amount):
        # This is a very basic strategy that randomly decides to buy or sell
        return "buy" if random.random() < 0.5 else "sell"
