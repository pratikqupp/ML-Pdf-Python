import threading
import subprocess
from flask import Flask

app = Flask(__name__)

@app.route("/")
def home():
    return "Server is running with mail_fetcher 🎉"

@app.route("/health")
def health():
    return "OK", 200

def run_mail_fetcher():
    # run the script in same container so logs show up in render
    subprocess.call(["python", "mail_fetcher.py"])

if __name__ == "__main__":
    t = threading.Thread(target=run_mail_fetcher)
    t.daemon = True
    t.start()

    # Flask ko render ke PORT env pe run karo
    import os
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
