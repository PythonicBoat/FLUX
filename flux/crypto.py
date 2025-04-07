import os
import base64
from typing import Union
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend

# Constants
SALT_SIZE = 16
KEY_SIZE = 32
IV_SIZE = 16

def derive_key(password: str, salt: bytes) -> bytes:
    """Derive encryption key from password using PBKDF2"""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=KEY_SIZE,
        salt=salt,
        iterations=100000,
        backend=default_backend()
    )
    return kdf.derive(password.encode())

def encrypt_data(data: bytes, key: bytes) -> bytes:
    """Encrypt data with AES-GCM"""
    iv = os.urandom(IV_SIZE)
    cipher = Cipher(algorithms.AES(key), modes.GCM(iv), backend=default_backend())
    encryptor = cipher.encryptor()
    ciphertext = encryptor.update(data) + encryptor.finalize()
    return iv + encryptor.tag + ciphertext

def decrypt_data(data: bytes, key: bytes) -> bytes:
    """Decrypt data with AES-GCM"""
    iv = data[:IV_SIZE]
    tag = data[IV_SIZE:IV_SIZE+16]
    ciphertext = data[IV_SIZE+16:]
    cipher = Cipher(algorithms.AES(key), modes.GCM(iv, tag), backend=default_backend())
    decryptor = cipher.decryptor()
    return decryptor.update(ciphertext) + decryptor.finalize()

def generate_salt() -> bytes:
    """Generate a random salt for key derivation"""
    return os.urandom(SALT_SIZE)

def encode_salt(salt: bytes) -> str:
    """Encode salt to base64 string for transfer"""
    return base64.b64encode(salt).decode()

def decode_salt(salt_str: str) -> bytes:
    """Decode salt from base64 string"""
    return base64.b64decode(salt_str)