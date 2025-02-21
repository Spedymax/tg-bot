import Crypto
from openai import OpenAI
from openpyxl import load_workbook
from google import genai

encrypted_file = 'encrypted.xlsx'  # Replace with path for the encrypted file
decrypted_file = 'decrypted.xlsx'  # Replace with path for the decrypted file

Crypto.decrypt_file(encrypted_file, decrypted_file)

workbook = load_workbook(filename='decrypted.xlsx')
sheet = workbook.active  # Assumes you want the active sheet

# Read the value from cell A1
openai_api_key = sheet['A1'].value
google_api_key = sheet['A2'].value
client = OpenAI(
    api_key=f'{openai_api_key}'
)

clientGoogle = genai.Client(
    api_key=f'{google_api_key}'
)
