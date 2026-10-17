"""legends_on_linux.auth — the Xbox Live sign-in the game itself uses.

Two Microsoft sign-ins exist side by side, as in BedrockOnLinux:

* the Store sign-in (xodus-cli login, see store.py) proves ownership and
  decrypts the game;
* this one gives WineGDK's XUser an Xbox Live user. It is a device-code OAuth
  sign-in with the MSA application ID WineGDK refreshes tokens with, after
  which the whole Xbox Live chain (device, user, XSTS/SISU tokens) is minted
  here, from the host's TLS stack, and handed to WineGDK as a "preauth" file:
  Azure resets those connections when Wine's TLS makes them.

The token chain is ported from BedrockOnLinux's bol/auth.py (MIT), trimmed to
the audiences Minecraft Legends asks for.
"""
# SPDX-License-Identifier: MIT

import base64
import json
import re
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse

from . import config as C
from .util import LolError, http_post_form, info, ok, warn, write_private

TOKEN_FILE = C.ACCOUNT / "msa-token.json"
DEVICE_KEY = C.ACCOUNT / "device-key.pem"
DEVICE_ID = C.ACCOUNT / "device-id.txt"

# Keep the cached chain when it is still good for a whole play session.
REUSE_MARGIN = 1800

# ISO "NotAfter" fields and the decimal epoch copies WineGDK actually parses.
EPOCH_FIELDS = {
    "user_token_expiry": "user_token_expiry_epoch",
    "xbl_token_expiry": "xbl_token_expiry_epoch",
    "achievements_expiry": "achievements_expiry_epoch",
    "sisu_expiry": "sisu_expiry_epoch",
    "lic_expiry": "lic_expiry_epoch",
}
REQUIRED = ("device_token", "user_token", "xbl_token", "xbl_xuid")


# ---------------------------------------------------------------- MSA account

def signed_in():
    return _load_token() is not None


def _load_token():
    try:
        token = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return token if token.get("refresh_token") else None


def _save_token(refresh_token):
    write_private(TOKEN_FILE, json.dumps(
        {"refresh_token": refresh_token, "obtained": int(time.time())}).encode())


def login(on_code=None):
    """Device-code sign-in: the user opens a URL and types a short code."""
    started = http_post_form(C.MSA_CONNECT, {
        "client_id": C.MSA_CLIENT_ID, "scope": C.MSA_SCOPE,
        "response_type": "device_code"})
    if "device_code" not in started:
        raise LolError("Microsoft did not start the sign-in: "
                       + str(started.get("error_description") or started.get("error") or started))
    url = started.get("verification_uri") or "https://www.microsoft.com/link"
    code = started.get("user_code")
    if on_code:
        on_code(url, code)
    else:
        info(f"Open {url} and enter the code  {code}")
    interval = max(int(started.get("interval") or 5), 1)
    deadline = time.time() + int(started.get("expires_in") or 900)
    while time.time() < deadline:
        time.sleep(interval)
        answer = http_post_form(C.MSA_TOKEN, {
            "client_id": C.MSA_CLIENT_ID, "grant_type": "device_code",
            "device_code": started["device_code"]})
        error = answer.get("error")
        if error == "authorization_pending":
            continue
        if error == "slow_down":
            interval += 5
            continue
        if error:
            raise LolError("Microsoft sign-in failed: "
                           + str(answer.get("error_description") or error))
        if answer.get("refresh_token"):
            _save_token(answer["refresh_token"])
            _forget_preauth()
            ok("Xbox Live account linked")
            return True
    raise LolError("The Microsoft sign-in timed out. Run the login again.")


def logout():
    for path in (TOKEN_FILE, C.PREAUTH):
        path.unlink(missing_ok=True)
    ok("Xbox Live account unlinked")


def _forget_preauth():
    C.PREAUTH.unlink(missing_ok=True)


def refresh():
    """Trade the stored refresh token for fresh tokens; returns the access token.

    Microsoft rotates refresh tokens, so the new one replaces the old.
    Returns (access_token, refresh_token) or raises LolError.
    """
    token = _load_token()
    if not token:
        raise LolError("No Xbox Live account is linked. Run:  legends-on-linux login")
    answer = http_post_form(C.MSA_TOKEN, {
        "client_id": C.MSA_CLIENT_ID, "scope": C.MSA_SCOPE,
        "grant_type": "refresh_token", "refresh_token": token["refresh_token"]})
    if not answer.get("refresh_token") or not answer.get("access_token"):
        raise LolError("Microsoft refused the stored sign-in ("
                       + str(answer.get("error_description") or answer.get("error") or "no token")
                       + "). Run:  legends-on-linux login")
    _save_token(answer["refresh_token"])
    return answer["access_token"], answer["refresh_token"]


# ---------------------------------------------------------------- Xbox Live chain

def _parse_expiry(raw):
    # Xbox sends 7 fractional digits; Python wants at most 6.
    text = re.sub(r"(\.\d{6})\d+", r"\1", raw.strip())
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    stamp = datetime.fromisoformat(text)
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)


def _with_epochs(payload):
    for iso, epoch in EPOCH_FIELDS.items():
        raw = payload.get(iso)
        try:
            payload[epoch] = str(int(_parse_expiry(raw).timestamp()))
        except (TypeError, ValueError, AttributeError):
            payload.pop(epoch, None)
    return payload


def _problems(payload, min_ttl=60):
    """Why a payload cannot be handed to WineGDK (empty list when it can)."""
    problems = [f for f in REQUIRED if not payload.get(f)]
    now = time.time()
    for iso in ("user_token_expiry", "xbl_token_expiry"):
        try:
            if _parse_expiry(payload[iso]).timestamp() <= now + min_ttl:
                problems.append(iso)
        except (KeyError, TypeError, ValueError, AttributeError):
            problems.append(iso)
    return problems


def _load_device_key():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    try:
        key = serialization.load_pem_private_key(DEVICE_KEY.read_bytes(), password=None)
        device_id = DEVICE_ID.read_text().strip()
        if device_id:
            return key, device_id
    except (OSError, ValueError):
        pass
    # Xbox Live expects one stable device identity across launches.
    key = ec.generate_private_key(ec.SECP256R1())
    device_id = "{" + str(uuid.uuid4()) + "}"
    write_private(DEVICE_KEY, key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()))
    write_private(DEVICE_ID, device_id.encode(), 0o644)
    return key, device_id


class _Signer:
    """Signs Xbox Live requests with the device's proof key."""

    def __init__(self, key):
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

        self._key, self._hashes, self._ec, self._decode = key, hashes, ec, decode_dss_signature
        numbers = key.public_key().public_numbers()
        self.x, self.y, self.d = numbers.x, numbers.y, key.private_numbers().private_value
        self.proof_key = {
            "alg": "ES256", "crv": "P-256", "kty": "EC", "use": "sig",
            "x": base64.b64encode(self.x.to_bytes(32, "big")).decode(),
            "y": base64.b64encode(self.y.to_bytes(32, "big")).decode()}

    def signature(self, method, path, body):
        # version(4) || ts(8) || r||s(64); the signed input separates every
        # field with a NUL (matches WineGDK's DeviceAuth_SignRequest).
        version = (1).to_bytes(4, "big")
        stamp = int((time.time() + 11644473600) * 1e7).to_bytes(8, "big")
        signed = (version + b"\0" + stamp + b"\0" + method.encode() + b"\0"
                  + path.encode() + b"\0" + b"\0" + body + b"\0")
        r, s = self._decode(self._key.sign(signed, self._ec.ECDSA(self._hashes.SHA256())))
        return base64.b64encode(version + stamp + r.to_bytes(32, "big")
                                + s.to_bytes(32, "big")).decode()

    def bcrypt_blob(self):
        # BCRYPT_ECCPRIVATE_BLOB for BCryptImportKeyPair in xgameruntime.dll.
        return ((0x32534345).to_bytes(4, "little") + (32).to_bytes(4, "little")
                + self.x.to_bytes(32, "big") + self.y.to_bytes(32, "big")
                + self.d.to_bytes(32, "big"))

    def post(self, url, body):
        data = json.dumps(body, separators=(",", ":")).encode()
        req = urllib.request.Request(url, data=data, method="POST", headers={
            "User-Agent": "XAL Xbox Live Game (Windows; SDK; 1.0.0.0)",
            "Content-Type": "application/json",
            "x-xbl-contract-version": "1",
            "Signature": self.signature("POST", urlparse(url).path, data)})
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                return resp.status, json.loads(resp.read() or b"{}")
        except urllib.error.HTTPError as exc:
            return exc.code, {"XErr": exc.headers.get("x-err"), "body": exc.read()[:200]}
        except (OSError, ValueError) as exc:
            return 0, {"error": str(exc)}


def _claims(auth):
    try:
        return auth["DisplayClaims"]["xui"][0]
    except (KeyError, IndexError, TypeError):
        return {}


def preauth(force=False):
    """Refresh the account and mint the Xbox Live chain into C.PREAUTH.

    Returns the Wine path of the file, or raises LolError.
    """
    try:
        cached = json.loads(C.PREAUTH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cached = {}
    if not force and cached and not _problems(cached, REUSE_MARGIN):
        info("Xbox Live: reusing the cached sign-in")
        return wine_path(C.PREAUTH)

    access_token, _refresh = refresh()
    key, device_id = _load_device_key()
    signer = _Signer(key)

    status, device = signer.post("https://device.auth.xboxlive.com/device/authenticate", {
        "RelyingParty": "http://auth.xboxlive.com", "TokenType": "JWT",
        "Properties": {"AuthMethod": "ProofOfPossession", "Id": device_id,
                       "DeviceType": "Win32", "Version": "10.0.22631",
                       "ProofKey": signer.proof_key}})
    if status != 200 or not device.get("Token"):
        raise LolError(f"Xbox Live device sign-in failed (HTTP {status}).")

    status, user = signer.post("https://user.auth.xboxlive.com/user/authenticate", {
        "RelyingParty": "http://auth.xboxlive.com", "TokenType": "JWT",
        "Properties": {"AuthMethod": "RPS", "SiteName": "user.auth.xboxlive.com",
                       "RpsTicket": "t=" + access_token}})
    if status != 200 or not user.get("Token"):
        raise LolError(f"Xbox Live user sign-in failed (HTTP {status}).")

    def xsts(rp, device_bound=False):
        props = {"SandboxId": "RETAIL", "UserTokens": [user["Token"]]}
        if device_bound:
            props.update(DeviceToken=device["Token"], ProofKey=signer.proof_key)
        code, answer = signer.post("https://xsts.auth.xboxlive.com/xsts/authorize",
                                   {"RelyingParty": rp, "TokenType": "JWT", "Properties": props})
        return answer if code == 200 and answer.get("Token") else None

    def sisu(rp):
        code, answer = signer.post("https://sisu.xboxlive.com/authorize", {
            "AccessToken": "t=" + access_token, "AppId": C.MSA_CLIENT_ID,
            "deviceToken": device["Token"], "Sandbox": "RETAIL",
            "UseModernGamertag": True, "SiteName": "user.auth.xboxlive.com",
            "RelyingParty": rp, "OfferTermsAcceptance": True, "AcceptOffers": True,
            "ProofKey": signer.proof_key})
        token = answer.get("AuthorizationToken") if code == 200 else None
        return token if isinstance(token, dict) and token.get("Token") else None

    def authorize(rp):
        # SISU is what a GDK title uses; XSTS covers the accounts it refuses.
        return sisu(rp) or xsts(rp, True) or xsts(rp) or {}

    achievements = xsts(C.RP_XBOXLIVE) or {}
    profile = authorize(C.RP_XBOXLIVE)
    playfab = authorize(C.RP_PLAYFAB)
    licensing = authorize(C.RP_LICENSING)
    claims = _claims(profile)

    out = {
        "device_id": device_id,
        "ecc_private_blob_b64": base64.b64encode(signer.bcrypt_blob()).decode(),
        "device_token": device["Token"],
        "device_token_expiry": device.get("NotAfter", ""),
        "user_token": user["Token"],
        "user_token_expiry": user.get("NotAfter", ""),
        "xbl_token": profile.get("Token"),
        "xbl_token_expiry": profile.get("NotAfter", ""),
        "xbl_xuid": claims.get("xid"),
        "xbl_gamertag": claims.get("gtg"),
        "xbl_age_group": claims.get("agg"),
        "xbl_uhs": claims.get("uhs"),
        "obtained": int(time.time()),
    }
    for claim, field in (("mgt", "xbl_modern_gamertag"), ("mgs", "xbl_modern_gamertag_suffix"),
                         ("umg", "xbl_unique_modern_gamertag")):
        if isinstance(claims.get(claim), str):
            out[field] = claims[claim]
    if "prv" in claims:
        privileges = sorted({int(p) for p in re.split(r"[\s,]+", str(claims["prv"]).strip())
                             if p.isdigit() and len(p) <= 10})
        out["xbl_privileges"] = " ".join(map(str, privileges))
    if achievements.get("Token") and _claims(achievements).get("uhs"):
        out.update(achievements_token=achievements["Token"],
                   achievements_uhs=str(int(_claims(achievements)["uhs"])),
                   achievements_expiry=achievements.get("NotAfter", ""))
    if playfab.get("Token"):
        out.update(sisu_rp=C.RP_PLAYFAB, sisu_token=playfab["Token"],
                   sisu_uhs=_claims(playfab).get("uhs"), sisu_expiry=playfab.get("NotAfter", ""))
    if licensing.get("Token"):
        out.update(lic_rp=C.RP_LICENSING, lic_token=licensing["Token"],
                   lic_uhs=_claims(licensing).get("uhs"), lic_expiry=licensing.get("NotAfter", ""))
    _with_epochs(out)

    problems = _problems(out)
    if problems:
        raise LolError("Xbox Live sign-in is incomplete (" + ", ".join(problems) + ").")
    write_private(C.PREAUTH, json.dumps(out).encode())
    got = ["device", "user", "profile"] + [n for n, a in (("PlayFab", playfab),
                                                         ("licensing", licensing)) if a.get("Token")]
    ok(f"Xbox Live: signed in as {out.get('xbl_gamertag') or out['xbl_xuid']} ({', '.join(got)})")
    if not playfab.get("Token"):
        warn("Xbox Live: no PlayFab token; the game will try to get one itself.")
    return wine_path(C.PREAUTH)


def current_refresh_token():
    token = _load_token()
    return token["refresh_token"] if token else None


def wine_path(path):
    return "Z:" + str(path).replace("/", "\\")
