import os
import io
import json
import requests
from flask import Flask, request, Response

from openai import OpenAI

# 🔑 تهيئة عميل OpenAI
client = OpenAI()

# نموذج المحادثة
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")

# 🔗 بيانات UltraMsg مباشرة (للتجارب)
ULTRA_INSTANCE_ID = "instance154392"       # اكتب هنا الـ Instance ID كما يظهر في UltraMsg
ULTRA_TOKEN = "qr5ee4h37ptjvz53"           # اكتب هنا الـ Token الخاص بالـ Instance

ULTRA_BASE_URL = f"https://api.ultramsg.com/{ULTRA_INSTANCE_ID}"


app = Flask(__name__)


# ======================
#  مساعدة: تفريغ صوت إلى نص
# ======================
def transcribe_audio_bytes(audio_bytes, filename="audio.ogg", mime_type="audio/ogg"):
    """
    يأخذ بايتات ملف صوتي (مثل فويس واتساب) ويعيد النص المستخرج منه.
    """
    bio = io.BytesIO(audio_bytes)
    bio.name = filename

    transcript = client.audio.transcriptions.create(
        model="gpt-4o-mini-transcribe",
        file=bio,
        response_format="text",
    )
    return transcript.text


# ======================
#  مساعدة: توليد رد ذكي على طلب الزبون
# ======================
def generate_order_reply(user_text: str) -> str:
    """
    هنا نحدد شخصية البوت: موظف استقبال طلبات لمطعم / محل.
    يمكن لاحقًا تخصيصه حسب كل مطعم.
    """
    system_prompt = (
        "أنت بوت طلبات لمطعم في الجزائر. "
        "تتكلم بالدارجة الجزائرية مع لمسة عربية فصيحة بسيطة. "
        "مهمّتك:\n"
        "- تفهم واش الزبون حاب يطلب (مأكولات / مشروبات ...).\n"
        "- إذا يطلب المنيو، تعطيه قائمة مختصرة بأمثلة، ليس كاملة جدًا.\n"
        "- إذا الطلب واضح، تعيد تلخيص الطلب بشكل مرتب، "
        "وتطلب من الزبون تأكيد نهائي (نعم / لا أو تعديل بسيط).\n"
        "- إذا ناقص معلومات (مثلاً الحجم، العدد، النكهة، العنوان، طريقة الدفع)، "
        "اسأله أسئلة قصيرة وواضحة.\n"
        "- لا تذكر أنك نموذج ذكاء اصطناعي، تصرّف كموظف استقبال عادي.\n"
        "- لا تتكلم في السياسة أو مواضيع خارج الطلبات.\n"
    )

    try:
        completion = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text},
            ],
        )
        reply = completion.choices[0].message.content
        return reply.strip()
    except Exception as e:
        print("AI error:", e, flush=True)
        return "صارت مشكل تقني في معالجة الطلب، جرّب تعاود تبعث بعد شوية."


# ======================
#  مساعدة: إرسال رسالة نصية عبر UltraMsg
# ======================
def send_text_message(to_chat_id: str, body: str):
    """
    إرسال رسالة نصية إلى نفس الشات عبر UltraMsg.
    to_chat_id يكون مثل: 2136XXXXXXX@c.us
    """
    if not ULTRA_BASE_URL or not ULTRA_TOKEN:
        print("UltraMsg config missing (ULTRA_INSTANCE_ID / ULTRA_TOKEN).", flush=True)
        return

    url = f"{ULTRA_BASE_URL}/messages/chat"
    data = {
        "token": ULTRA_TOKEN,
        "to": to_chat_id,
        "body": body,
        "priority": 10,
        "referenceId": "",
    }

    try:
        resp = requests.post(url, data=data, timeout=20)
        print("UltraMsg send response:", resp.status_code, resp.text, flush=True)
    except Exception as e:
        print("Error sending message via UltraMsg:", e, flush=True)


# ======================
#  المسار الرئيسي: فقط للتجربة
# ======================
@app.route("/", methods=["GET"])
def index():
    return "Bot is running"


# ======================
#  /voice: اختبار الرد النصي من السيرفر
# ======================
@app.route("/voice", methods=["GET"])
def voice():
    msg = request.args.get("msg", "").strip()
    if not msg:
        return "أرسل بارامتر msg في الرابط.", 400

    reply = generate_order_reply(msg)
    return reply


# ======================
#  صفحة اختبار لرفع ملف صوتي يدويًا
# ======================
@app.route("/test-upload", methods=["GET"])
def test_upload():
    return """
    <html>
      <body>
        <h3>Test audio transcription</h3>
        <form action="/transcribe" method="post" enctype="multipart/form-data">
          <p>Select an audio file (مثلاً رسالة واتساب صوتية .ogg أو .mp3):</p>
          <input type="file" name="audio" accept="audio/*" />
          <button type="submit">Transcribe</button>
        </form>
      </body>
    </html>
    """


# ======================
#  /transcribe: تفريغ ملف صوتي مرفوع من المتصفح
# ======================
@app.route("/transcribe", methods=["POST"])
def transcribe():
    audio_file = request.files.get("audio")

    if not audio_file:
        return "No audio file uploaded with name 'audio'.", 400

    try:
        audio_bytes = audio_file.read()
        filename = audio_file.filename or "audio.ogg"

        text = transcribe_audio_bytes(audio_bytes, filename=filename)

        return f"""
        <html>
          <body>
            <h3>Transcription result:</h3>
            <p>{text}</p>
            <hr/>
            <a href="/test-upload">Try another file</a>
          </body>
        </html>
        """
    except Exception as e:
        return f"Error while transcribing audio: {e}", 500


# ======================
#  /whatsapp: Webhook من UltraMsg
# ======================
@app.route("/whatsapp", methods=["POST"])
def whatsapp_webhook():
    """
    هذا المسار تستدعيه UltraMsg عندما تصل رسالة جديدة.
    نعالج:
    - type == 'chat'  → نص
    - type == 'ptt' أو 'audio' → فويس
    """
    payload = request.get_json(force=True, silent=True) or {}
    print("Webhook event:", json.dumps(payload, ensure_ascii=False), flush=True)

    event_type = payload.get("event_type")
    if event_type != "message_received":
        # نتجاهل الأحداث الأخرى
        return Response("ignored", status=200)

    data = payload.get("data", {}) or {}

    msg_type = data.get("type")          # chat, ptt, audio, ...
    from_chat = data.get("from")         # مثل 2136XXXXXXX@c.us
    body = (data.get("body") or "").strip()
    msg_id = data.get("id")

    if not from_chat:
        return Response("no from", status=200)

    reply_text = None

    # ---------- 1) رسالة نصية عادية ----------
    if msg_type == "chat":
        if not body:
            reply_text = "مرحبا 👋، ابعثلي الطلب تاعك في رسالة أو فويس."
        else:
            reply_text = generate_order_reply(body)

    # ---------- 2) رسالة صوتية (فويس / ptt) ----------
    elif msg_type in ("ptt", "audio", "voice"):
        if not ULTRA_BASE_URL or not ULTRA_TOKEN:
            reply_text = "استقبلت فويس، لكن إعدادات السيرفر ناقصة. تقدر تبعث طلبك مكتوب مؤقتًا."
        elif not msg_id:
            reply_text = "استقبلت فويس لكن ما قدرش نحمّل الملف، جرّب تعاود ترسلو."
        else:
            try:
                # ⚠ ملاحظة:
                # حسب توثيق UltraMsg، استرجاع ميديا الرسالة يكون عبر endpoint خاص بالـ media.
                # الصيغة الشائعة:
                #   GET https://api.ultramsg.com/{instance_id}/messages/media/{message_id}?token=XXXX
                #
                # إذا تغيّر عندهم المسار، فقط عدّل هذا الـ URL حسب التوثيق.
                media_url = f"{ULTRA_BASE_URL}/messages/media/{msg_id}"
                resp = requests.get(
                    media_url,
                    params={"token": ULTRA_TOKEN},
                    timeout=30,
                )

                if not resp.ok:
                    print("Error downloading media:", resp.status_code, resp.text, flush=True)
                    reply_text = "استقبلت فويس لكن ما قدرش نحمّل الملف، جرّب تعاود ترسلو."
                else:
                    audio_bytes = resp.content
                    text = transcribe_audio_bytes(audio_bytes)
                    print("Voice transcription:", text, flush=True)
                    reply_text = generate_order_reply(text)
            except Exception as e:
                print("Error handling voice message:", e, flush=True)
                reply_text = "استقبلت فويس لكن ما قدرش نحمّل الملف، جرّب تعاود ترسلو."

    # ---------- 3) أنواع أخرى ----------
    else:
        reply_text = "مرحبا 👋، أرسل رسالة نصية أو فويس باش نقدر نفهم الطلب تاعك."

    # إرسال الرد إلى الزبون
    if reply_text:
        send_text_message(from_chat, reply_text)

    # مهم: نرجع 200 حتى لا تعيد UltraMsg الإرسال
    return Response("ok", status=200)


# ======================
#  تشغيل محلي (Render يستعمل gunicorn app:app)
# ======================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
