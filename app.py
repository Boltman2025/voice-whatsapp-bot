from flask import Flask, request, jsonify
import requests
import logging
from openai import OpenAI
import os

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

WHAPI_TOKEN = os.getenv("WHAPI_TOKEN")
WHAPI_API_URL = "https://gate.whapi.cloud"

def whapi_send_message(to, text):
    url = f"{WHAPI_API_URL}/messages/text?token={WHAPI_TOKEN}"
    payload = {
        "to": to,
        "body": text
    }
    r = requests.post(url, json=payload)
    app.logger.info(f"Whapi send response: {r.status_code} {r.text}")

@app.route("/whapi", methods=["POST"])
def whapi_webhook():
    data = request.get_json(force=True, silent=True) or {}
    app.logger.info("Incoming Whapi webhook: %s", data)

    messages = data.get("messages")
    if not messages:
        return jsonify({"ok": True})

    msg = messages[0]

    # استخراج رقم المرسل
    from_number = msg.get("from")
    if not from_number:
        chat_id = msg.get("chat_id", "")
        if "@s.whatsapp.net" in chat_id:
            from_number = chat_id.split("@")[0]

    if not from_number:
        app.logger.warning("Could not extract from_number")
        return jsonify({"ok": True})

    msg_type = msg.get("type")

    # ======================
    # 1️⃣ معالجة الرسائل النصية
    # ======================
    if msg_type == "text":
        text = msg.get("text", {}).get("body", "")
        if not text:
            return jsonify({"ok": True})

        app.logger.info(f"User said: {text}")

        ai_reply = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "أنت مساعد ودود."},
                {"role": "user", "content": text}
            ]
        ).choices[0].message["content"]

        whapi_send_message(from_number, ai_reply)
        return jsonify({"ok": True})

    # ======================
    # 2️⃣ معالجة الرسائل الصوتية
    # ======================
    if msg_type == "voice":
        voice = msg.get("voice", {})
        voice_url = voice.get("link")

        if not voice_url:
            app.logger.error("Voice message has no link.")
            return jsonify({"ok": True})

        # تحميل الصوت
        audio_data = requests.get(voice_url).content

        # إرسال إلى OpenAI لأجل التفريغ
        transcript = client.audio.transcriptions.create(
            model="gpt-4o-mini-transcribe",
            file=("audio.ogg", audio_data)
        )

        text_transcribed = transcript.text
        app.logger.info(f"Voice -> Text: {text_transcribed}")

        # توليد رد
        ai_reply = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "أنت مساعد صوتي ذكي."},
                {"role": "user", "content": text_transcribed}
            ]
        ).choices[0].message["content"]

        whapi_send_message(from_number, ai_reply)
        return jsonify({"ok": True})

    app.logger.info(f"Ignored unknown message type: {msg_type}")
    return jsonify({"ok": True})

@app.route("/", methods=["GET"])
def home():
    return "Bot is running!"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
