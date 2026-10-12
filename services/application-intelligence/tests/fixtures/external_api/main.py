import requests

def get_data():
    requests.get("https://api.stripe.com/v1/charges")
