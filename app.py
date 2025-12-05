import os
import logging
import requests
from flask import Flask, request, jsonify

# ---------------------------------
# إعداد التطبيق و اللوج
# ---------------------------------
app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# مفاتيح البيئة
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
WHAPI_API_URL = os.getenv("WHAPI_API_URL", "https://gate.whapi.cloud")
WHAPI_TOKEN = os.getenv("WHAPI_TOKEN")

# ---------------------------------
# دالة مساعدة: طلب رد من OpenAI
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

    # يمكنك تعديل البرومبت حسب أسلوب المطعم
    data = {
        "model": "gpt-4o-mini",
        "messages": [
            {
                "role": "system",
                "content": (
                    "أنت مساعد مطعم جزائري تتكلّم بالدارجة البسيطة، "
                    "تستقبل الطلبات عبر الواتساب، "
                    "تسأل عن الكمية، نوع الأكل، والوقت أو التوصيل عند الحاجة."
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
        app.logger.error("Error calling OpenAI: %s", e)
        return "وقع خلل تقني في الخدمة تاع الذكاء الاصطناعي، جرّب تعاود بعد شوية 😊"


# ---------------------------------
# دالة مساعدة: إرسال رسالة نصّية عبر Whapi
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
        "to": to_number,  # مثال: "213664226955"
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
# Webhook من Whapi
# ---------------------------------
@app.route("/whapi", methods=["POST"])
def whapi_webhook():
    """
    يستقبل Webhook من Whapi، يقرأ الرسالة النصيّة،
    يرسلها إلى OpenAI، ثم يردّ على نفس الرقم عبر Whapi.
    """
    data = request.get_json(force=True, silent=True) or {}
    app.logger.info("Incoming Whapi webhook: %s", data)

    messages = data.get("messages") or []
    if not messages:
        return jsonify({"ok": True})

    msg = messages[0]

    # نوع الرسالة (text, audio, action, ...)
    msg_type = msg.get("type")
    if msg_type != "text":
        app.logger.info("Ignoring non-text message of type: %s", msg_type)
        return jsonify({"ok": True})

    # 🔢 استخراج رقم المرسل من هيكل Whapi
    # Whapi يرسل الحقل باسم "from"
    from_number = msg.get("from")

    # أحياناً الرقم يكون في chat_id بصيغة 213xxx@s.whatsapp.net
    if not from_number:
        chat_id = msg.get("chat_id")
        if chat_id and "@s.whatsapp.net" in chat_id:
            from_number = chat_id.split("@")[0]

    if not from_number:
        app.logger.warning("No from_number in webhook payload.")
        return jsonify({"ok": True})

    # 📩 النص الذي أرسله الزبون
    text_body = ""
    text_obj = msg.get("text") or {}
    if isinstance(text_obj, dict):
        text_body = text_obj.get("body", "")

    if not text_body:
        app.logger.info("No text body in message.")
        return jsonify({"ok": True})

    # 🧠 نولّد الرد من الذكاء الاصطناعي
    reply = generate_ai_reply(text_body)

    # 📤 نردّ على نفس الرقم عبر Whapi
    send_whapi_text(from_number, reply)

    return jsonify({"ok": True})


# ---------------------------------
# تشغيل محلي (غير مستعمل على Render)
# ---------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
