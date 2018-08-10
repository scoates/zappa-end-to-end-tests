import os
import http.client
from urllib.parse import urlparse

def test_https():
    API_GATEWAY_URL = os.environ.get('API_GATEWAY_URL')
    assert API_GATEWAY_URL, "We have an API Gateway URL"

    url = urlparse(API_GATEWAY_URL)

    hc = http.client.HTTPSConnection(url.netloc)
    hc.request("GET", url.path)

    res = hc.getresponse()
    assert res.status == 200, "API returns 200 on /"

    body = res.read()
    assert body.decode().startswith("Hello from Python 3.6"), "Running on Python 3.6"
