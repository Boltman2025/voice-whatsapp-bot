import os
import logging
import requests
from flask import Flask, request, jsonify

# ---------------------------------
# إعداد التطبيق والـ logging
# ---------------------------------
app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# مفاتيح البيئة
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
WHAPI_API_URL = os.getenv("WHAPI_API_URL", "https://gate.whapi.cloud")
WHAPI_TOKEN = os.getenv("WHAPI_TOKEN")


# ---------------------------------
# دالة: طلب رد من OpenAI (نص ← نص)
# ---------------------------------
def generate_ai_reply(user_text: str) -> str:
    """
    يرسل نص الزبون إلى OpenAI ويعيد الرد كنص.
    """
    if not OPENAI_API_KEY:
        app.logger.error("OPENAI_API_KEY is missing.")
        return "كاين مشكل في إعداد مفتاح الذكاء الاصطناعي، رجاء جرّب بعد شوية 🙏"

    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }

    data = {
        "model": "gpt-4o-mini",
        "messages": [
            {
                "role": "system",
                "content": (
                    "أنت مساعد مطعم جزائري تتكلّم بالدارجة البسيطة، "
                    "تستقبل الطلبات عبر الواتساب، "
                    "تسأل عن الكمية، نوع الأكل، والوقت أو التوصيل عند الحاجة، "
                    "وتجاوب باختصار وبأسلوب ودود."
                ),
            },
            {"role": "user", "content": user_text},
        ],
        "max_tokens": 220,
    }

    try:
        resp = requests.post(url, headers=headers, json=data, timeout=20)
        resp.raise_for_status()
        j = resp.json()
        reply = j["choices"][0]["message"]["content"].strip()
        return reply
    except Exception as e:
        app.logger.error("Error calling OpenAI (chat): %s", e)
        return "وقع خلل تقني في خدمة الذكاء الاصطناعي، جرّب تعاود بعد شوية 😊"


# ---------------------------------
# دالة: تفريغ صوت من URL باستخدام OpenAI
# ---------------------------------
def transcribe_audio_from_url(file_url: str, mime_type: str | None = None) -> str | None:
    """
    تحمّل ملف صوتي من رابط (Whapi) وتفريغه نصّياً باستعمال
    /v1/audio/transcriptions
    """
    if not OPENAI_API_KEY:
        app.logger.error("OPENAI_API_KEY is missing (for audio).")
        return None

    try:
        # 1) تحميل الملف من الرابط الذي أعطاه Whapi
        app.logger.info("Downloading audio from: %s", file_url)
        audio_resp = requests.get(file_url, timeout=30)
        audio_resp.raise_for_status()
        audio_bytes = audio_resp.content
    except Exception as e:
        app.logger.error("Error downloading audio file: %s", e)
        return None

    # 2) إرسال الملف إلى OpenAI للتفريغ
    url = "https://api.openai.com/v1/audio/transcriptions"
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        # لا نحدّد Content-Type هنا، requests يتكفّل به (multipart/form-data)
    }

    files = {
        "file": (
            "audio.ogg",
            audio_bytes,
            mime_type or "audio/ogg",
        )
    }
    data = {
        "model": "gpt-4o-mini-transcribe",  # أو "whisper-1" إذا أردت
    }

    try:
        resp = requests.post(url, headers=headers, files=files, data=data, timeout=60)
        resp.raise_for_status()
        j = resp.json()
        text = j.get("text") or ""
        app.logger.info("Transcription result: %s", text)
        return text.strip() or None
    except Exception as e:
        app.logger.error("Error calling OpenAI (audio): %s | body=%s", e, resp.text if 'resp' in locals() else "")
        return None


# ---------------------------------
# دالة: إرسال رسالة نصية عبر Whapi
# ---------------------------------
def send_whapi_text(to_number: str, body: str):
    """
    يرسل رسالة نصية إلى رقم معيّن عبر Whapi.
    """
    if not WHAPI_TOKEN:
        app.logger.error("WHAPI_TOKEN is missing.")
        return

    base = WHAPI_API_URL.rstrip("/")
    url = f"{base}/messages/text"

    headers = {
        "Authorization": f"Bearer {WHAPI_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "to": to_number,  # مثال: "213776206336"
        "body": body,
    }

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=15)
        app.logger.info("Whapi send response: %s %s", resp.status_code, resp.text)
    except Exception as e:
        app.logger.error("Error sending via Whapi: %s", e)


# ---------------------------------
# مسار فحص بسيط
# ---------------------------------
@app.route("/", methods=["GET"])
def index():
    return "Bot is running", 200


# ---------------------------------
# Webhook من Whapi (نص + صوت)
# ---------------------------------
@app.route("/whapi", methods=["POST"])
def whapi_webhook():
    """
    يستقبل Webhook من Whapi:
    - إذا كانت الرسالة نصية: يردّ مباشرة بالنص من OpenAI
    - إذا كانت الرسالة صوتية (voice): يحوّل الصوت إلى نص ثم يردّ
    """
    data = request.get_json(force=True, silent=True) or {}
    app.logger.info("Incoming Whapi webhook: %s", data)

    messages = data.get("messages") or []
    if not messages:
        return jsonify({"ok": True})

    msg = messages[0]
    msg_type = msg.get("type")

    # 🔢 استخراج رقم المرسل
    from_number = msg.get("from")
    if not from_number:
        chat_id = msg.get("chat_id")
        if chat_id and "@s.whatsapp.net" in chat_id:
            from_number = chat_id.split("@")[0]

    if not from_number:
        app.logger.warning("No from_number in webhook payload.")
        return jsonify({"ok": True})

    # -------------------------
    # 1) رسائل نصيّة
    # -------------------------
    if msg_type == "text":
        text_obj = msg.get("text") or {}
        user_text = ""
        if isinstance(text_obj, dict):
            user_text = text_obj.get("body", "")

        if not user_text:
            app.logger.info("No text body in text message.")
            return jsonify({"ok": True})

        ai_reply = generate_ai_reply(user_text)
        send_whapi_text(from_number, ai_reply)
        return jsonify({"ok": True})

    # -------------------------
    # 2) رسائل صوتية (voice)
    # -------------------------
    if msg_type == "voice":
        voice_info = msg.get("voice") or {}
        file_url = voice_info.get("link")
        mime_type = voice_info.get("mime_type")

        if not file_url:
            app.logger.error("Voice message without 'link' field.")
            send_whapi_text(
                from_number,
                "استقبلت فويس لكن ما قدرش نحمّل الملف، جرّب تعاود ترسلو 🙏",
            )
            return jsonify({"ok": True})

        # تفريغ الصوت إلى نص
        transcript = transcribe_audio_from_url(file_url, mime_type)
        if not transcript:
            send_whapi_text(
                from_number,
                "ما قدرناش نفهم الرسالة الصوتية (مشكلة تقنية)، لو تقدر ابعث نفس الشيء كتابيًا 🌟",
            )
            return jsonify({"ok": True})

        # إرسال النص إلى الذكاء الاصطناعي ثم الرد
        ai_reply = generate_ai_reply(transcript)
        send_whapi_text(from_number, ai_reply)
        return jsonify({"ok": True})

    # -------------------------
    # 3) أي أنواع أخرى نتجاهلها
    # -------------------------
    app.logger.info("Ignoring non-supported message type: %s", msg_type)
    return jsonify({"ok": True})


# ---------------------------------
# تشغيل محلي (غير مستعمل على Render غالبًا)
# ---------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
