from flask import Flask, request
import os
from openai import OpenAI

app = Flask(__name__)

# تهيئة عميل OpenAI باستعمال المفتاح من Environment Variables
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

@app.route("/")
def index():
    return "Bot is running"

@app.route("/voice")
def voice():
    # نأخذ النص الذي يمثل ما قاله الزبون (مؤقتاً كـ query string)
    user_msg = request.args.get("msg", "").strip()

    if not user_msg:
        return "Please provide ?msg= in the URL", 400

    # نطلب من النموذج أن يتصرف كوكيل طلبات لمطعم في الجزائر
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

        # نأخذ النص من أول مخرجات النموذج
        ai_reply = response.output[0].content[0].text

        return ai_reply

    except Exception as e:
        # في حالة خطأ نرجّع رسالة بسيطة
        return f"Error while contacting AI: {e}", 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
