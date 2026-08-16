"""
Member 3 — Digital Signatures, server side
(requirement #5: "Each sender has a signing key pair"
 requirement #6: "Messages contain a sender signature and the signature is verified")

Each client generates an ECDSA P-256 key pair in the browser (see
static/crypto.js) — the private key never leaves the browser. The public key
(as a JWK) is sent once at join time; every chat message is signed client-side
and verified here using the `cryptography` library.
"""
import base64
from cryptography.hazmat.primitives.asymmetric import ec, utils as asym_utils
from cryptography.hazmat.primitives import hashes
from cryptography.exceptions import InvalidSignature


def jwk_to_public_key(jwk: dict) -> ec.EllipticCurvePublicKey:
    """Converts a P-256 JWK (as exported by the browser's Web Crypto API) into
    a `cryptography` EC public key object."""
    x = int.from_bytes(_b64url_decode(jwk["x"]), "big")
    y = int.from_bytes(_b64url_decode(jwk["y"]), "big")
    numbers = ec.EllipticCurvePublicNumbers(x, y, ec.SECP256R1())
    return numbers.public_key()


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def _raw_to_der(signature_b64: str) -> bytes:
    """Web Crypto's ECDSA sign() returns a raw (r || s) 64-byte signature for
    P-256, but `cryptography`'s verify() expects DER encoding — convert it."""
    raw = base64.b64decode(signature_b64)
    r = int.from_bytes(raw[:32], "big")
    s = int.from_bytes(raw[32:], "big")
    return asym_utils.encode_dss_signature(r, s)


def verify_signature(pubkey_jwk: dict, signature_b64: str, message: str) -> bool:
    """
    message must be the EXACT string the client signed — see
    static/crypto.js `canonicalMessage()` and app.py's matching helper,
    both must build the string identically or every signature will fail.
    """
    try:
        public_key = jwk_to_public_key(pubkey_jwk)
        der_sig = _raw_to_der(signature_b64)
        public_key.verify(der_sig, message.encode("utf-8"), ec.ECDSA(hashes.SHA256()))
        return True
    except (InvalidSignature, ValueError, KeyError, IndexError):
        return False
