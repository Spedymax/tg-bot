from cryptography.fernet import Fernet
import openpyxl
import os

# Generate a key for encryption and decryption
# You should store this key securely - if you lose it, you will not be able to decrypt your files!
key = b'Nfv2uvCjgJPdymgG5sTXC28-VygFCtIeI-tlYSHIbok='
cipher_suite = Fernet(key)

# Function to encrypt the file
def encrypt_file(file_path, encrypted_file_path):
    with open(file_path, 'rb') as file:
        file_data = file.read()
        encrypted_data = cipher_suite.encrypt(file_data)
    with open(encrypted_file_path, 'wb') as file:
        file.write(encrypted_data)
    print(f"File {file_path} encrypted to {encrypted_file_path}")


# Function to decrypt the file
def decrypt_file(encrypted_file_path, decrypted_file_path):
    with open(encrypted_file_path, 'rb') as file:
        encrypted_data = file.read()
        decrypted_data = cipher_suite.decrypt(encrypted_data)
    with open(decrypted_file_path, 'wb') as file:
        file.write(decrypted_data)
    print(f"File {encrypted_file_path} decrypted to {decrypted_file_path}")


# Usage
# original_file = '../Api Keys.xlsx'  # Replace with your Excel file path
# encrypted_file = 'encrypted.xlsx'  # Replace with path for the encrypted file
# decrypted_file = 'decrypted.xlsx'  # Replace with path for the decrypted file
#
# # Encrypt the Excel file
# encrypt_file(original_file, encrypted_file)
#
# # Decrypt the Excel file
# decrypt_file(encrypted_file, decrypted_file)
