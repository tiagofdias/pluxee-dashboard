"""Generate VAPID Keypair for Web Push Notifications.

Run this script to generate or display VAPID public and private keys:
    python generate_vapid_keys.py

You can add these keys to your .env file or Render dashboard:
    VAPID_PUBLIC_KEY=<public_key>
    VAPID_PRIVATE_KEY=<private_pem_or_path>
"""

import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from py_vapid import Vapid, utils
from cryptography.hazmat.primitives import serialization

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(DATA_DIR, exist_ok=True)

pem_path = os.path.join(DATA_DIR, "vapid_private.pem")
pub_path = os.path.join(DATA_DIR, "vapid_public.txt")

if os.path.exists(pem_path) and os.path.exists(pub_path):
    with open(pub_path, "r", encoding="utf-8") as f:
        pub_b64 = f.read().strip()
    with open(pem_path, "r", encoding="utf-8") as f:
        pem_str = f.read().strip()
    print("[OK] VAPID Keys already exist:\n")
else:
    v = Vapid()
    v.generate_keys()
    pem_bytes = v.private_pem()
    raw_pub = v.public_key.public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    pub_b64 = utils.b64urlencode(raw_pub)

    with open(pem_path, "wb") as f:
        f.write(pem_bytes)
    with open(pub_path, "w", encoding="utf-8") as f:
        f.write(pub_b64)

    pem_str = pem_bytes.decode("utf-8")
    print("🎉 New VAPID Keypair Generated Successfully!\n")

print(f"Public Key (Browser):\n{pub_b64}\n")
print(f"Private Key Path: {pem_path}")
print("\n" + "=" * 60)
print("Para colocar no .env ou nas variáveis do Render:")
print(f"VAPID_PUBLIC_KEY={pub_b64}")
print(f"VAPID_PRIVATE_KEY={pem_path}")
print("=" * 60)
