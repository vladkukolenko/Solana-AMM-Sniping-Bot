import requests
import hmac
import hashlib
import time

class ExchangeAPI:
    def __init__(self, api_key, api_secret, base_url="https://api.exchange.com"):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = base_url

    def _sign_request(self, method, path, params=None):
        timestamp = str(int(time.time()))
        message = timestamp + method + path
        if params:
            message += str(params)
        signature = hmac.new(self.api_secret.encode(), message.encode(), hashlib.sha256).hexdigest()
        return signature

    def _send_request(self, method, path, params=None):
        headers = {
            "X-API-KEY": self.api_key,
            "X-API-SIGNATURE": self._sign_request(method, path, params),
            "X-API-TIMESTAMP": str(int(time.time()))
        }
        response = requests.request(method, self.base_url + path, headers=headers, json=params)
        response.raise_for_status()
        return response.json()

    def get_balance(self):
        return self._send_request("GET", "/balance")

    def place_order(self, pair, side, price, quantity):
        params = {
            "pair": pair,
            "side": side,
            "price": price,
            "quantity": quantity
        }
        return self._send_request("POST", "/orders", params)

    def cancel_order(self, order_id):
        return self._send_request("DELETE", f"/orders/{order_id}")

    def get_order(self, order_id):
        return self._send_request("GET", f"/orders/{order_id}")
