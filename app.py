import os
import io
import logging

from flask import Flask, request, jsonify
import requests
from openai import OpenAI

# -----------------------------
# إعدادات عامة
# -----------------------------
app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = app.logger

# مفاتيح البيئة (من Render)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
WHAPI_BASE_URL = os.getenv("WHAPI_BASE_URL")  # مثال: https://gate.whapi.cloud
WHAPI_TOKEN = os.getenv("WHAPI_TOKEN")        # التوكن من Whapi.cloud

if not OPENAI_API_KEY:
    logger.error("OPENAI_API_KEY is missing")
if not WHAPI_BASE_URL or not WHAPI_TOKEN:
    logger.error("WHAPI_BASE_URL or WHAPI_TOKEN missing")

client = OpenAI(api_key=OPENAI_API_KEY)


# -----------------------------
# دالة إرسال رسالة نصية عبر Whapi
# -----------------------------
def send_whapi_text(to_number: str, body: str):
    """
    إرسال رسالة نصية إلى رقم واتساب عبر Whapi.
    to_number مثال: '213776206336'
    """
    if not WHAPI_BASE_URL or not WHAPI_TOKEN:
        logger.error("Whapi config missing.")
        return

    url = f"{WHAPI_BASE_URL}/messages/text"
    payload = {
        "to": to_number,
        "body": body,
    }
    headers = {
        "Authorization": f"Bearer {WHAPI_TOKEN}",
        "Content-Type": "application/json",
    }

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=15)
        logger.info("Whapi send response: %s %s", resp.status_code, resp.text)
    except Exception as e:
        logger.exception("Error sending message to Whapi: %s", e)


# -----------------------------
# دالة توليد الرد من النص (باستعمال OpenAI نص فقط)
# -----------------------------
def generate_reply_from_text(user_text: str) -> str:
    """
    نأخذ نص الزبون (سواء مكتوب أو مفرّغ من الصوت)
    ونرجع رد بالعربية كنادل / وكيل مطعم.
    """
    system_prompt = (
        "أنت وكيل مبيعات لمطعم جزائري. "
        "تكلّم باللهجة الجزائرية الخفيفة مع بعض العربية، "
        "كن مهذّب، مختصر، واقترح أطباقاً إضافية عند اللزوم."
    )

    try:
        completion = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text},
            ],
        )
        answer = completion.choices[0].message.content.strip()
        return answer
    except Exception as e:
        logger.exception("Error while calling OpenAI chat model: %s", e)
        return "وقع مشكل تقني صغير في الفهم، جرّب تعاود ترسل الرسالة."


# -----------------------------
# راوت بسيط للفحص
# -----------------------------
@app.route("/", methods=["GET"])
def home():
    return "OK", 200


# -----------------------------
# Webhook من Whapi
# -----------------------------
@app.route("/whapi", methods=["POST"])
def whapi_webhook():
    data = request.get_json(force=True, silent=True) or {}
    logger.info("Incoming Whapi webhook: %s", data)

    messages = data.get("messages") or []
    if not messages:
        # أحيانا يكون الحدث statuses فقط
        return jsonify({"ok": True})

    msg = messages[0]
    msg_type = msg.get("type")

    # 🔢 استخراج رقم المرسل
    from_number = msg.get("from")
    if not from_number:
        chat_id = msg.get("chat_id")
        if isinstance(chat_id, str) and "@s.whatsapp.net" in chat_id:
            from_number = chat_id.split("@")[0]

    if not from_number:
        logger.warning("No from_number in webhook payload.")
        return jsonify({"ok": True})

    # -----------------
    # 1) رسالة نصية
    # -----------------
    if msg_type == "text":
        text_obj = msg.get("text") or {}
        user_text = (text_obj.get("body") or "").strip()
        if not user_text:
            return jsonify({"ok": True})

        logger.info("Received TEXT from %s: %s", from_number, user_text)

        reply_text = generate_reply_from_text(user_text)
        send_whapi_text(from_number, reply_text)
        return jsonify({"ok": True})

    # -----------------
    # 2) رسالة صوتية (voice)
    # -----------------
    elif msg_type in ("voice", "audio"):
        voice_obj = msg.get("voice") or msg.get("audio") or {}
        link = voice_obj.get("link")
        mime_type = voice_obj.get("mime_type") or "audio/ogg"

        if not link:
            logger.warning("Voice message without link.")
            send_whapi_text(
                from_number,
                "ما قدرش نلقا الملف الصوتي في الرسالة، جرّب تبعث فويس جديد أو ابعثلي نص."
            )
            return jsonify({"ok": True})

        logger.info("Downloading voice from link: %s", link)

        try:
            resp = requests.get(link, timeout=20)
            resp.raise_for_status()
            audio_bytes = resp.content

            # نحضّر ملف في الذاكرة بصيغة يقبلها OpenAI
            audio_file = io.BytesIO(audio_bytes)
            audio_file.name = "voice.oga"  # مهم أن يكون له اسم

            transcript = client.audio.transcriptions.create(
                model="gpt-4o-mini-transcribe",
                file=audio_file,
                # يمكن ترك اللغة بدون تحديد ليتعرف تلقائياً
                # language="ar"
            )
            user_text = (transcript.text or "").strip()
            logger.info("Transcribed voice for %s: %s", from_number, user_text)

            if not user_text:
                send_whapi_text(
                    from_number,
                    "ما قدرتش نفهم المقطع الصوتي هذا، جرّب توضّح أكثر أو ابعث نص."
                )
                return jsonify({"ok": True})

            reply_text = generate_reply_from_text(user_text)
            send_whapi_text(from_number, reply_text)
            return jsonify({"ok": True})

        except Exception as e:
            logger.exception("Error while transcribing voice message: %s", e)
            send_whapi_text(
                from_number,
                "صار مشكل في قراءة الرسالة الصوتية، جرّب تبعث فويس آخر أو ابعثلي نص."
            )
            return jsonify({"ok": True})

    # -----------------
    # أنواع أخرى نتجاهلها
    # -----------------
    else:
        logger.info("Ignoring message type: %s", msg_type)
        return jsonify({"ok": True})


# -----------------------------
# تشغيل محلي (ليس ضروريًا على Render)
# -----------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
