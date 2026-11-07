#!/usr/bin/env python3
"""
Query the Realme/Oppo OTA API for an update package, without the removed
realme-ota tool.

Why this exists
---------------
R0rt1z2/realme-ota was taken down by a DMCA notice on 2026-09-02, and
tools/ota_probe.py depended on it. The protocol itself is fully implemented in
historical snapshots, so it is re-expressed here in pure Python.

Those snapshots are preserved at Git baseline 0c4f602 and locally under
.local/migration/source/snapshots/. Source license: licenses/OPlus_firmware_download.LICENSE.

Provenance of every constant below (read from this repo, not from the web):
  snapshots/OPlus_firmware_download/app/src/main/java/com/desmond/ofd/backend/realmeota/
    data/RealmeOtaConfig.kt     - endpoints, RSA public keys, negotiation versions
    network/RealmeOtaRequest.kt - body fields, headers, derived values
    crypto/Rsa.kt              - RSA-OAEP with SHA-1 for BOTH digest and MGF1
    crypto/Aes.kt              - AES-CTR v2 with random 32-byte key, 16-byte IV

Protocol, req-version 2 (RUI >= 2, the modern path):
  1. Build a plaintext JSON body.
  2. AES-CTR encrypt it with a random key/IV  -> {"cipher": b64, "iv": b64}
  3. Wrap that object as {"params": "<json string>"}
  4. RSA-OAEP(SHA1) wrap the base64 AES key -> protectedKey header,
     inside {"SCENE_1": {"protectedKey","version","negotiationVersion"}}
  5. POST with a set of identifying headers.

Requires: cryptography and requests. No vendor binary.

Safety: read-only. One HTTP POST, prints the response. Downloads nothing.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys
import time
from typing import Any

try:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
except ImportError:
    sys.exit("missing dependency: pip install cryptography")

try:
    import requests
except ImportError:
    sys.exit("missing dependency: pip install requests")


# ---------------------------------------------------------------- endpoints
# RealmeOtaConfig.kt - serverParamsByRegion (req-version 2)
SERVERS = {
    "GL": {
        "url": "https://component-otapc-sg.allawnos.com/update/v3",
        "pub": (
            "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAkA980wxi+eTGcFDiw2I6"
            "RrUeO4jL/Aj3Yw4dNuW7tYt+O1sRTHgrzxPD9SrOqzz7G0KgoSfdFHe3JVLPN+U1"
            "waK+T0HfLusVJshDaMrMiQFDUiKajb+QKr+bXQhVofH74fjat+oRJ8vjXARSpFk4"
            "/41x5j1Bt/2bHoqtdGPcUizZ4whMwzap+hzVlZgs7BNfepo24PWPRujsN3uopl+8"
            "u4HFpQDlQl7GdqDYDj2zNOHdFQI2UpSf0aIeKCKOpSKF72KDEESpJVQsqO4nxMwE"
            "i2jMujQeCHyTCjBZ+W35RzwT9+0pyZv8FB3c7FYY9FdF/+lvfax5mvFEBd9jO+dp"
            "MQIDAQAB"
        ),
        "neg": "1615895993238",
    },
    "CN": {
        "url": "https://component-otapc-cn.allawntech.com/update/v3",
        "pub": (
            "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEApXYGXQpNL7gmMzzvajHa"
            "oZIHQQvBc2cOEhJc7/tsaO4sT0unoQnwQKfNQCuv7qC1Nu32eCLuewe9LSYhDXr9"
            "KSBWjOcCFXVXteLO9WCaAh5hwnUoP/5/Wz0jJwBA+yqs3AaGLA9wJ0+B2lB1vLE4"
            "FZNE7exUfwUc03fJxHG9nCLKjIZlrnAAHjRCd8mpnADwfkCEIPIGhnwq7pdkbamZ"
            "coZfZud1+fPsELviB9u447C6bKnTU4AaMcR9Y2/uI6TJUTcgyCp+ilgU0JxemrSI"
            "PFk3jbCbzamQ6Shkw/jDRzYoXpBRg/2QDkbq+j3ljInu0RHDfOeXf3VBfHSnQ66H"
            "CwIDAQAB"
        ),
        "neg": "1615879139745",
    },
    "EU": {
        "url": "https://component-otapc-eu.allawnos.com/update/v3",
        "pub": (
            "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAh8/EThsK3f0WyyPgrtXb"
            "/D0Xni6UZNppaQHUqHWo976cybl92VxmehE0ISObnxERaOtrlYmTPIxkVC9MMueD"
            "vTwZ1l0KxevZVKU0sJRxNR9AFcw6D7k9fPzzpNJmhSlhpNbt3BEepdgibdRZbacF"
            "3NWy3ejOYWHgxC+I/Vj1v7QU5gD+1OhgWeRDcwuV4nGY1ln2lvkRj8EiJYXfkSq/"
            "wUI5AvPdNXdEqwou4FBcf6mD84G8pKDyNTQwwuk9lvFlcq4mRqgYaFg9DAgpDgqV"
            "K4NTJWM7tQS1GZuRA6PhupfDqnQExyBFhzCefHkEhcFywNyxlPe953NWLFWwbGvF"
            "KwIDAQAB"
        ),
        "neg": "1615897067573",
    },
}

REGION_LABEL = {"GL": "GL", "CN": "CN", "IN": "IN", "EU": "EU", "NA": "GL"}
NV_CARRIER = {"CN": "10010111", "EU": "01000100"}
DEFAULT_IMEI = "000000000000000"


# ------------------------------------------------------------------- crypto

def rsa_wrap_aes_key(aes_key_b64: str, pub_b64: str) -> str:
    """Rsa.kt::wrapAesKey - RSA-OAEP where digest AND MGF1 are both SHA-1.

    Rsa.kt is explicit that PyCryptodome defaults MGF1 to SHA-1 while some JCE
    providers default it to SHA-256, so both are pinned here deliberately.
    """
    der = base64.b64decode(pub_b64)
    pub = serialization.load_der_public_key(der)
    wrapped = pub.encrypt(
        aes_key_b64.encode("utf-8"),
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA1()),
            algorithm=hashes.SHA1(),
            label=None,
        ),
    )
    return base64.b64encode(wrapped).decode("ascii")


def aes_ctr_v2_encrypt(plaintext: str) -> dict:
    """Aes.kt::encryptCtrV2 - random 32-byte key, random 16-byte IV."""
    key = os.urandom(32)
    iv = os.urandom(16)
    cipher = Cipher(algorithms.AES(key), modes.CTR(iv))
    enc = cipher.encryptor()
    ct = enc.update(plaintext.encode("utf-8")) + enc.finalize()
    return {
        "keyB64": base64.b64encode(key).decode("ascii"),
        "ivB64": base64.b64encode(iv).decode("ascii"),
        "cipherB64": base64.b64encode(ct).decode("ascii"),
    }


# ------------------------------------------------------------------- request

def build_request(args, ota_version: str):
    region = args.region
    label = REGION_LABEL.get(region, "GL")
    # Each region has its OWN endpoint and its OWN RSA key. Using the GL key against
    # the EU endpoint returns responseCode 500 - measured 2026-10-16.
    server = SERVERS.get(label, SERVERS["GL"])

    rui = args.rui
    android_version = f"Android{10 + rui - 1}.0"
    color_os = "ColorOS7" if rui == 1 else f"ColorOS{11 + rui - 2}"
    nv_carrier = args.nv or NV_CARRIER.get(label, "00011011")
    is_realme = "1" if "RMX" in args.model else "0"
    ota_prefix = "_".join(ota_version.split("_")[:2])
    device_id = hashlib.sha256(
        (args.imei or DEFAULT_IMEI).encode("utf-8")
).hexdigest().upper()
    now_ms = int(time.time() * 1000)

    body = {
        "language": args.language,
        "romVersion": ota_prefix,
        "otaVersion": ota_version,
        "androidVersion": android_version,
        "colorOSVersion": color_os,
        "model": args.model,
        "productName": args.model,
        "operator": "unknown",
        "uRegion": label,
        "trackRegion": label,
        "imei": args.imei or DEFAULT_IMEI,
        "imei1": args.imei or DEFAULT_IMEI,
        "mode": "1" if args.beta else "0",
        "registrationId": "unknown",
        "deviceId": device_id,
        "version": "2" if rui == 1 else "3",
        "type": "1",
        "otaPrefix": ota_prefix,
        "isRealme": is_realme,
        "time": str(now_ms),
        "canCheckSelf": "0",
        # Both fields are present in OTA-Pulse's defaultBody (Data.kt:24) and were
        # missing from the OPlus_firmware_download port. Measured omission.
        "gray": "0",
        "reqMode": "manual",
    }

    headers = {
        "language": args.language,
        "romVersion": ota_prefix,
        "otaVersion": ota_version,
        "androidVersion": android_version,
        "colorOSVersion": color_os,
        "model": args.model,
        "infVersion": "1",
        "operator": "unknown",
        "nvCarrier": nv_carrier,
        "uRegion": label,
        "trackRegion": label,
        "imei": args.imei or DEFAULT_IMEI,
        "imei1": args.imei or DEFAULT_IMEI,
        "deviceId": device_id,
        "mode": "client_auto",
        "channel": "pc",
        "version": "1",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "NULL",
    }

    ctr = aes_ctr_v2_encrypt(json.dumps(body, separators=(",", ":")))
    cipher_iv = json.dumps({"cipher": ctr["cipherB64"], "iv": ctr["ivB64"]}, separators=(",", ":"))
    outer = json.dumps({"params": cipher_iv}, separators=(",", ":"))

    protected_key = rsa_wrap_aes_key(ctr["keyB64"], server["pub"])
    scene = json.dumps(
        {"SCENE_1": {
            "protectedKey": protected_key,
            "version": str(now_ms + 86_400_000),
            "negotiationVersion": server["neg"],
        }},
        separators=(",", ":"),
    )
    headers["version"] = "2"
    headers["protectedKey"] = scene

    return server["url"], outer, headers, json.dumps(body, indent=2), ctr["keyB64"]


# ------------------------------------------------------------------ response

def device_nv_id():
    """ro.build.oplus_nv_id of the attached phone, or None."""
    import subprocess
    for exe in ("adb", "adb.exe"):
        try:
            out = subprocess.run([exe, "shell", "getprop", "ro.build.oplus_nv_id"],
                                 capture_output=True, text=True, timeout=15).stdout.strip()
            if out:
                return out
        except Exception:
            continue
    return None


def decrypt_body(payload, key_b64):
    """RealmeOtaDecoder: body is a JSON string of {"cipher","iv"}, AES-CTR with OUR request key."""
    if not key_b64:
        return None
    try:
        obj = json.loads(payload) if isinstance(payload, str) else payload
        ct = base64.b64decode(obj["cipher"])
        iv = base64.b64decode(obj["iv"])
    except Exception:
        return None
    try:
        key = base64.b64decode(key_b64)
        dec = Cipher(algorithms.AES(key), modes.CTR(iv)).decryptor()
        return (dec.update(ct) + dec.finalize()).decode("utf-8", "replace")
    except Exception:
        return None


def find_urls(obj: Any):
    """Walk the response for anything that looks like a firmware URL."""
    found = []

    def walk(o):
        if isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
        elif isinstance(o, str):
            low = o.lower()
            if low.startswith("http") and (".zip" in low or "download" in low
                                           or "component-ota" in low):
                found.append(o)

    walk(obj)
    return found


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Query the Realme/Oppo OTA API (req-version 2, RUI >= 2).")
    ap.add_argument("--model", default="RMX3301", help="ro.product.model")
    ap.add_argument("--region", default="EU", choices=["GL", "CN", "IN", "EU", "NA"])
    ap.add_argument("--rui", type=int, default=6, help="RUI major (6 = Android 15)")
    ap.add_argument("--nv", default=None,
                    help="carrier code (8 digits). Default: read ro.build.oplus_nv_id from the "
                         "attached phone, else the region table. NOT ro.separate.soft.")
    ap.add_argument("--imei", default=None)
    ap.add_argument("--language", default="en-EN")
    ap.add_argument("--beta", action="store_true")
    ap.add_argument("versions", nargs="+", help="otaVersion candidate(s)")
    ap.add_argument("--show-request", action="store_true", help="print the plaintext body")
    a = ap.parse_args(argv)
    if not a.nv:
        a.nv = device_nv_id()
        print(f"  carrier code from device: {a.nv or '(unavailable - using the region table)'}")

    for v in a.versions:
        print(f"=== {a.model} region={a.region} rui={a.rui} version={v}")
        try:
            url, body, headers, plain, aes_key_b64 = build_request(a, v)
        except Exception as e:
            print(f"  build failed: {e}")
            continue
        if a.show_request:
            print("  --- plaintext body ---")
            for line in plain.splitlines():
                print("    " + line)
        print(f"  POST {url}")
        try:
            resp = requests.post(url, data=body.encode("utf-8"),
                                 headers=headers, timeout=30)
        except Exception as e:
            print(f"  request failed: {type(e).__name__}: {e}")
            continue
        print(f"  HTTP {resp.status_code}  ({len(resp.content)} bytes)")
        try:
            data = resp.json()
        except Exception:
            data = resp.text
        urls = []
        if isinstance(data, dict):
            # The envelope is plaintext: responseCode and errMsg need no decryption.
            print(f"    responseCode = {data.get('responseCode')}")
            if data.get("errMsg"):
                print(f"    errMsg       = {data.get('errMsg')}")
            payload = data.get("body") or data.get("resps")
            if payload:
                plain_text = decrypt_body(payload, aes_key_b64)
                if plain_text:
                    print("  --- decrypted body ---")
                    for line in plain_text[:600].splitlines():
                        print("    " + line)
                    urls = find_urls(plain_text)
                else:
                    print("  body present but not decryptable with this key")
            else:
                urls = find_urls(data)
            if urls:
                print("  --- downloadable URLs ---")
                for u in urls[:8]:
                    print("    " + u)
            else:
                print("  no download URL in response")
        else:
            print("  raw response (first 400 chars):")
            print("    " + str(data)[:400])
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
