from flask import Flask
import os

app = Flask(__name__)

@app.route("/")
def index():
    return "Bot is running"

# هذا المسار سنستعمله لاحقاً لاستقبال الصوت من واتساب
@app.route("/voice")
def voice():
    return "Voice endpoint ready"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
