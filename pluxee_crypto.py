"""Pluxee 3.0.7 wire encryption, verified against the APK's built-in test vector.

This protocol constant ships in the official client. It is not a user's password
or authentication token. Keep implementation on the server, not in frontend code.
"""
import base64
import secrets
import string
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

# Populated from CryptoUtilsKt in the user-supplied APK during implementation.
PROTOCOL_KEY = b'S0d3x0_34/25;Z245678936987410321'


def encrypt(value, iv=None):
    iv = iv or ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(16))
    if len(iv) != 16 or not iv.isascii():
        raise ValueError('A 16-byte ASCII IV is required')
    padder = padding.PKCS7(128).padder()
    padded = padder.update(str(value).encode('utf-8')) + padder.finalize()
    cipher = Cipher(algorithms.AES(PROTOCOL_KEY), modes.CBC(iv.encode('ascii'))).encryptor()
    return base64.b64encode(cipher.update(padded) + cipher.finalize()).decode('ascii') + iv
