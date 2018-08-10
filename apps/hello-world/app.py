import sys
from flask import Flask


app = Flask(__name__)

@app.route('/')
def hello_world():
    return 'Hello from Python {}'.format(sys.version)

if __name__ == '__main__':
    app.run()
