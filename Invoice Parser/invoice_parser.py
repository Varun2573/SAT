import google.generativeai as genai
import os, json, base64
from functools import wraps
from dotenv import load_dotenv, find_dotenv
import fitz
from docx import Document
from json import JSONDecodeError

load_dotenv(find_dotenv())
GEMINIAPI = os.getenv("GOOGLEAPI")
genai.configure(api_key=GEMINIAPI)

class InvoiceParser(object):
    def __init__(self, MODEL="models/gemini-2.0-flash") -> None:
        self.GMODEL = genai.GenerativeModel(
            model_name=MODEL,
            generation_config={"response_mime_type": "application/json"},
        )

    def ExceptionHandling(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                print(f"Error in {func.__name__}: {e}")
                return None
        return wrapper

    @ExceptionHandling
    def documentParser(self, filepath: str, promptfile: str = "prompt.txt") -> str:
        if not filepath:
            print("NO FILEPATH IS AVAILABLE!")
            return None

        ExtractedData = ""
        FileName = os.path.basename(filepath)

        if filepath.lower().endswith(".pdf"):
            document = fitz.open(filepath)
            for page in document:
                text = page.get_text()
                if text:
                    ExtractedData += text
            document.close()
        elif filepath.lower().endswith(".docx"):
            document = Document(filepath)
            for paragraph in document.paragraphs:
                ExtractedData += paragraph.text + "\n"
        elif filepath.lower().endswith(".txt"):
            with open(filepath, 'r', encoding='utf-8') as file:
                ExtractedData = file.read()

        with open(promptfile, "r") as file:
            prompt = file.read()

        Fprompt = f"{prompt}\n\nExtracted Data from {FileName}:\n{ExtractedData}"
        response = self.GMODEL.generate_content(Fprompt)
        try:
            responseJSON = json.loads(response.text)
            print(f"JSON generated for: {FileName}")
            return responseJSON
        except JSONDecodeError as e:
            print(f"Error in documentParser: {e}")
            return None

    @ExceptionHandling
    def ImageParser(self, filepath, promptfile: str = "ImagePrompt.txt") -> dict:
        if not filepath:
            print("NO FILEPATH IS AVAILABLE!")
            return None

        with open(promptfile, "r") as file:
            prompt = file.read()
        with open(filepath, "rb") as Imagefile:
            ImageData = base64.b64encode(Imagefile.read()).decode("utf-8")

        Fprompt = f"{prompt}\n\nExtract the text from this image as accurately as possible:"
        response = self.GMODEL.generate_content(
            [Fprompt, {"mime_type": "image/jpeg", "data": ImageData}]
        )
        try:
            responseJSON = json.loads(response.text)
            print(f"JSON generated for: {os.path.basename(filepath)}")
            return responseJSON
        except JSONDecodeError as e:
            print(f"Error in ImageParser: {e}")
            return None
