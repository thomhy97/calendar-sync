"""Lance ce script UNE FOIS pour générer les clés secrètes à coller dans .env"""
import secrets
from cryptography.fernet import Fernet

print("SECRET_KEY=" + secrets.token_hex(32))
print("FERNET_KEY=" + Fernet.generate_key().decode())
