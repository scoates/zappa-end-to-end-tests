import os
import requests


def test_https():
    API_GATEWAY_URL = os.environ.get('API_GATEWAY_URL')
    assert API_GATEWAY_URL, "We have an API Gateway URL"

    r = requests.get(API_GATEWAY_URL)

    assert r.status_code == 200, "API returns 200 on /"

    assert r.text.startswith("Hello from Slim Handler; Python 2.7"), "Running on Python 2.7"
