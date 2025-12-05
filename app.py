import os
import requests
from flask import Flask, request, Response
from openai import OpenAI

# ==========================
# إعدادات عامة
# ==========================

app = Flask(__name__)

# مفتاح OpenAI من متغيرات البيئة في Render
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

# إعدادات UltraMsg (ضع بيانات الـ Instance الخاصة بك)
ULTRA_INSTANCE_ID = "instance154392"   # مثال: instance154392
ULTRA_TOKEN = "qr5ee4h37ptjvz53"       # Token من لوحة UltraMsg


# ==========================
# دالة مساعدة: رد ذكي من AI
# ==========================

def generate_ai_response(user_message: str) -> str:
    """
    تأخذ رسالة المستخدم نصاً وتعيد ردّاً ذكياً من نموذج GPT
    بأسلوب مساعد مطعم في الجزائر.
    """
    try:
        resp = client.responses.create(
            model="gpt-4o-mini",
            input=f"""
أنت مساعد افتراضي لمطعم في الجزائر.
تكلّم بالعامية الجزائرية البسيطة + عربية فصحى خفيفة.
مهامك:
- ترحيب بالزبون بأدب.
- فهم الطلب (أكل/شراب/سؤال) وطرح أسئلة توضيحية قصيرة إذا لزم.
- تلخيص الطلب في سطر واحد في النهاية.

هذه هي رسالة الزبون:
{user_message}
            """,
        )
        return resp.output_text
    except Exception as e:
        return f"صار مشكل تقني صغير، جرّب تعاود بعد لحظات. (تفاصيل: {e})"


# ==========================
# 1) صفحة بسيطة لاختبار السيرفر
# ==========================

@app.route("/")
def index():
    return "Bot is running"


# ==========================
# 2) مسار نصّي /voice (للتجارب من المتصفح)
#    مثال:
#    https://YOUR-APP.onrender.com/voice?msg=سلام
# ==========================

@app.route("/voice")
def voice():
    msg = request.args.get("msg", "").strip()

    if not msg:
        return "Please provide ?msg= in the URL", 400

    reply = generate_ai_response(msg)
    return reply


# ==========================
# 3) مسار /speak لتحويل نص إلى صوت MP3
#    (لا يُستعمل حالياً في الواتساب، فقط للتجارب)
# ==========================

@app.route("/speak")
def speak():
    text = request.args.get("text", "").strip()

    if not text:
        return "Please provide ?text= in the URL", 400

    try:
        speech = client.audio.speech.create(
            model="gpt-4o-mini-tts",
            voice="alloy",
            input=text,
        )

        audio_bytes = speech.read()

        return Response(
            audio_bytes,
            mimetype="audio/mpeg",
            headers={
                "Content-Disposition": 'inline; filename="reply.mp3"'
            },
        )
    except Exception as e:
        return f"Error while generating speech: {e}", 500


# ==========================
# 4) صفحة ويب بسيطة لاختبار رفع ملف صوتي
# ==========================

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


# ==========================
# 5) استقبال ملف صوتي وتفريغه نصًّا (من المتصفح)
# ==========================

@app.route("/transcribe", methods=["POST"])
def transcribe():
    audio_file = request.files.get("audio")

    if not audio_file:
        return "No audio file uploaded with name 'audio'.", 400

    try:
        audio_file.stream.seek(0)
        filename = audio_file.filename or "audio-file.ogg"

        transcript = client.audio.transcriptions.create(
            model="gpt-4o-mini-transcribe",
            file=(filename, audio_file.stream.read(), "audio/ogg"),
        )

        text = transcript.text

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


# ==========================
# 6) Webhook للواتساب من UltraMsg
#    - يدعم الآن:
#      • رسائل نصية (chat)
#      • رسائل صوتية (audio / ptt) → تفريغ → رد نصي
# ==========================

@app.route("/whatsapp", methods=["POST"])
def whatsapp_webhook():
    try:
        event = request.json or {}
        print("Webhook event:", event, flush=True)  # مفيد للـ Logs في Render

        data = event.get("data", {})

        sender = data.get("from")            # رقم المرسل (chatId)
        msg_type = data.get("type")          # chat, audio, ptt, image ...
        body = data.get("body", "")          # نص الرسالة إن وُجد

        if not sender:
            return "no sender", 200

        # رابط API لإرسال رسائل واتساب
        base_url = f"https://api.ultramsg.com/{ULTRA_INSTANCE_ID}/messages"

        # -----------------------------
        # 6.A) إذا كانت الرسالة نصية
        # -----------------------------
        if msg_type == "chat":
            user_text = body.strip()
            if not user_text:
                return "empty text", 200

            reply_text = generate_ai_response(user_text)

            payload = {
                "token": ULTRA_TOKEN,
                "to": sender,
                "body": reply_text,
                "priority": "high",
            }

            requests.post(f"{base_url}/chat", data=payload)
            return "ok", 200

        # -----------------------------
        # 6.B) إذا كانت الرسالة صوتية (فويس)
        # type غالباً: "audio" أو "ptt"
        # -----------------------------
        if msg_type in ("audio", "ptt"):
            audio_url = data.get("url")
            if not audio_url:
                # لو لم يُرسل الرابط لأي سبب، نرجع رد عادي
                fallback = "استقبلت فويس لكن ما قدرش نحمّل الملف، جرّب تعاود ترسلو."
                payload = {
                    "token": ULTRA_TOKEN,
                    "to": sender,
                    "body": fallback,
                    "priority": "high",
                }
                requests.post(f"{base_url}/chat", data=payload)
                return "no_audio_url", 200

            # تحميل ملف الصوت من UltraMsg/WhatsApp
            audio_bytes = requests.get(audio_url).content

            # تفريغ الصوت إلى نص
            try:
                transcript = client.audio.transcriptions.create(
                    model="gpt-4o-mini-transcribe",
                    file=("audio.ogg", audio_bytes, "audio/ogg"),
                )
                user_text = transcript.text
            except Exception as e:
                error_reply = f"صار مشكل في قراءة الفويس، حاول تكتبلي نصًا. (تفاصيل: {e})"
                payload = {
                    "token": ULTRA_TOKEN,
                    "to": sender,
                    "body": error_reply,
                    "priority": "high",
                }
                requests.post(f"{base_url}/chat", data=payload)
                return "stt_error", 200

            # توليد رد ذكي اعتماداً على النص المستخرج
            reply_text = generate_ai_response(user_text)

            # إرسال الرد نصّيًا
            payload = {
                "token": ULTRA_TOKEN,
                "to": sender,
                "body": reply_text,
                "priority": "high",
            }
            requests.post(f"{base_url}/chat", data=payload)

            return "ok", 200

        # أنواع أخرى (صورة، فيديو...) لا نعالجها الآن
        return "unsupported_type", 200

    except Exception as e:
        return f"Webhook error: {e}", 500


# ==========================
# تشغيل التطبيق محلياً أو على Render
# ==========================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
