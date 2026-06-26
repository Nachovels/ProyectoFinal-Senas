import os
import dotenv
import google.generativeai as genai

env_path = os.path.join(os.path.dirname(__file__), '.env')
dotenv.load_dotenv(dotenv_path=env_path)

API_KEY = os.getenv("GEMINI_API_KEY")
print(f"API KEY: {API_KEY}")

if API_KEY:
    genai.configure(api_key=API_KEY)
    model = genai.GenerativeModel('gemini-1.5-flash')
    try:
        response = model.generate_content("Responde con la palabra 'OK'")
        print("Gemini Response:", response.text)
    except Exception as e:
        print("Gemini Error:", e)
else:
    print("No API key loaded.")
