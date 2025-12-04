from flask import Flask, request, Response
import os
from openai import OpenAI

app = Flask(__name__)

# عميل OpenAI باستعمال المفتاح من Environment Variables في Render
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

@app.route("/")
def index():
    return "Bot is running"

# مسار نصي ذكي (كما عملناه سابقاً)
@app.route("/voice")
def voice():
    user_msg = request.args.get("msg", "").strip()

    if not user_msg:
        return "Please provide ?msg= in the URL", 400

    prompt = f"""
أنت وكيل ذكي لمطعم بيتزا في الجزائر.
الزبون قال: "{user_msg}"

مهمتك:
- إذا طلب المنيو، أعطه منيو مختصراً.
- إذا أراد طلباً، لخّص ما يريد: الأطباق، الكميات، الأحجام.
- اسأله بلطف عن العنوان إذا لم يذكره.
- استعمل الدارجة الجزائرية البسيطة + العربية الفصحى الخفيفة.
- الرد يجب أن يكون في 3 أسطر كحد أقصى.
"""

    try:
        response = client.responses.create(
            model="gpt-4.1-mini",
            input=prompt,
        )

        ai_reply = response.output[0].content[0].text
        return ai_reply

    except Exception as e:
        return f"Error while contacting AI: {e}", 500


# 🔊 مسار جديد: تحويل نص إلى صوت MP3
@app.route("/speak")
def speak():
    text = request.args.get("msg", "").strip()

    if not text:
        return "Please provide ?msg= in the URL", 400

    try:
        # إنشاء صوت من النص باستعمال نموذج TTS
        speech = client.audio.speech.create(
            model="gpt-4o-mini-tts",
            voice="alloy",      # صوت افتراضي
            format="mp3",
            input=text,
        )

        audio_bytes = speech.read()  # نحصل على البيانات الصوتية كـ bytes

        return Response(
            audio_bytes,
            mimetype="audio/mpeg",
            headers={
                "Content-Disposition": 'inline; filename="reply.mp3"'
            }
        )

    except Exception as e:
        return f"Error while generating speech: {e}", 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
