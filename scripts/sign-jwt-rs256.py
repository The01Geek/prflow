#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""sign-jwt-rs256.py — mint an RS256 GitHub-App JWT with the Python standard
library alone, so the credential refresher signs identically on every runner the
``runs-on`` expression can select (issue #1882).

The refresher previously signed with ``openssl dgst -sha256 -sign
<(printf '%s' "$KEY")`` — a process-substitution ``/dev/fd`` path a
native-Windows ``openssl`` cannot open, so a long cloud run on a self-hosted
Windows runner silently lost its write credentials once the job-start token's
hour lapsed. This signer replaces that call: no part of the signing path invokes
``openssl``, and the private key reaches the process only on standard input —
never a file, never an argv.

Contract:
  argv:   <iss> <iat> <exp>   (the App id and the two integer JWT timestamps)
  stdin:  the unencrypted PEM private key (PKCS#1 or PKCS#8), bytes
  stdout: the finished JWT ``<header>.<payload>.<signature>`` (no trailing
          newline), base64url without padding
  stderr: on any refusal, one ``sign-jwt-rs256:``-prefixed diagnostic naming the
          encoding detected — and NO run of characters from the key body

Only the two unencrypted PEM encodings GitHub issues (PKCS#1) or an operator
converts to (PKCS#8, ``openssl pkcs8 -topk8``) are accepted; every other input —
a passphrase-protected PEM, an OpenSSH key, a raw DER key, empty stdin, a
truncated PEM, or a PEM whose body decodes but is not an RSA private key — is
refused by name, and no signature is ever emitted from an unrecognized encoding.
A wrong-but-valid signature from a mis-parsed key would resurface as the same
misdirecting API error this issue removes, so the reader recognizes exactly the
two encodings and refuses the rest.

The primitive is hand-rolled RSASSA-PKCS1-v1_5 (RFC 8017 §8.2): SHA-256 digest,
the SHA-256 ``DigestInfo`` prefix, EMSA-PKCS1-v1_5 padding sized from the
modulus, and the built-in three-argument ``pow``. It is deterministic, so a
byte-equality check against ``openssl`` is a total verification (the suite runs
it); it has no verification surface (it signs with the caller's own key and
nothing verifies the signature), so a defect yields a token GitHub rejects — an
availability failure the mint's retry cycle already absorbs, never an accepted
forgery.
"""
import base64
import hashlib
import sys

# rsaEncryption OID (1.2.840.113549.1.1.1) DER content bytes (after tag+length).
_RSA_OID = bytes.fromhex("2a864886f70d010101")
# The DER ``DigestInfo`` prefix for SHA-256 (RFC 8017 §9.2 notes-2).
_SHA256_DIGESTINFO = bytes.fromhex("3031300d060960864801650304020105000420")


class SignerError(Exception):
    """A refusal naming the encoding detected; its message never carries key bytes."""


def _b64url(raw: bytes) -> bytes:
    return base64.urlsafe_b64encode(raw).rstrip(b"=")


def _read_tlv(buf: bytes, i: int):
    """Read one DER TAG-LENGTH-VALUE at offset ``i``; return (tag, value, next_offset)."""
    if i + 2 > len(buf):
        raise SignerError("PEM body decoded but is not a valid RSA private key structure")
    tag = buf[i]
    i += 1
    length = buf[i]
    i += 1
    if length & 0x80:
        nbytes = length & 0x7F
        if nbytes == 0 or i + nbytes > len(buf):
            raise SignerError("PEM body decoded but is not a valid RSA private key structure")
        length = int.from_bytes(buf[i:i + nbytes], "big")
        i += nbytes
    if i + length > len(buf):
        raise SignerError("PEM body decoded but is not a valid RSA private key structure")
    return tag, buf[i:i + length], i + length


def _parse_pkcs1(der: bytes):
    """Parse a PKCS#1 RSAPrivateKey DER; return (modulus, private_exponent)."""
    tag, seq, _ = _read_tlv(der, 0)
    if tag != 0x30:
        raise SignerError("PEM body decoded but is not a valid RSA private key structure")
    i = 0
    fields = []
    # version, modulus (n), publicExponent (e), privateExponent (d), ...
    for _ in range(4):
        tag, val, i = _read_tlv(seq, i)
        if tag != 0x02:
            raise SignerError("PEM body decoded but is not a valid RSA private key structure")
        fields.append(val)
    n = int.from_bytes(fields[1], "big")
    d = int.from_bytes(fields[3], "big")
    if n == 0 or d == 0:
        raise SignerError("PEM body decoded but is not a valid RSA private key structure")
    return n, d


def _parse_pkcs8(der: bytes):
    """Parse a PKCS#8 PrivateKeyInfo DER; verify rsaEncryption; return (n, d)."""
    tag, seq, _ = _read_tlv(der, 0)
    if tag != 0x30:
        raise SignerError("PEM body decoded but is not a valid RSA private key structure")
    i = 0
    _tag, _ver, i = _read_tlv(seq, i)          # version INTEGER
    atag, alg, i = _read_tlv(seq, i)           # AlgorithmIdentifier SEQUENCE
    if atag != 0x30:
        raise SignerError("PEM body decoded but is not a valid RSA private key structure")
    otag, oid, _ = _read_tlv(alg, 0)           # OID
    if otag != 0x06 or oid != _RSA_OID:
        raise SignerError("PKCS#8 PEM whose key algorithm is not RSA")
    ktag, key_octets, i = _read_tlv(seq, i)    # privateKey OCTET STRING
    if ktag != 0x04:
        raise SignerError("PEM body decoded but is not a valid RSA private key structure")
    return _parse_pkcs1(key_octets)


def _pem_body(text: str, begin: str, end: str) -> bytes:
    """Extract and base64-decode the body between a matching BEGIN/END pair."""
    start = text.find(begin)
    after = start + len(begin)
    stop = text.find(end, after)
    if stop < 0:
        raise SignerError("truncated PEM (no matching END marker)")
    body = "".join(text[after:stop].split())
    try:
        return base64.b64decode(body, validate=True)
    except ValueError:
        raise SignerError("truncated PEM (undecodable base64 body)")


def load_rsa_private_key(pem: bytes):
    """Detect the encoding and return (modulus, private_exponent), or refuse by name."""
    if not pem or not pem.strip():
        raise SignerError("empty standard input")
    text = pem.decode("latin-1")
    if "-----BEGIN" not in text:
        raise SignerError("raw DER key (no PEM armor) — only PEM is accepted")
    if "ENCRYPTED" in text or "Proc-Type:" in text or "DEK-Info:" in text:
        raise SignerError("passphrase-protected (encrypted) PEM")
    if "BEGIN OPENSSH PRIVATE KEY" in text:
        raise SignerError("OpenSSH-format private key")
    if "BEGIN EC PRIVATE KEY" in text:
        raise SignerError("EC private key (not RSA)")
    if "BEGIN DSA PRIVATE KEY" in text:
        raise SignerError("DSA private key (not RSA)")
    if "BEGIN RSA PRIVATE KEY" in text:
        der = _pem_body(text, "-----BEGIN RSA PRIVATE KEY-----", "-----END RSA PRIVATE KEY-----")
        return _parse_pkcs1(der)
    if "BEGIN PRIVATE KEY" in text:
        der = _pem_body(text, "-----BEGIN PRIVATE KEY-----", "-----END PRIVATE KEY-----")
        return _parse_pkcs8(der)
    raise SignerError("unrecognized PEM type (not a PKCS#1 or PKCS#8 RSA private key)")


def sign_jwt(iss: str, iat: str, exp: str, pem: bytes) -> bytes:
    """Build and RS256-sign the JWT; return the finished token bytes."""
    try:
        iat_i = int(iat)
        exp_i = int(exp)
    except (TypeError, ValueError):
        raise SignerError("iat and exp must be integers")
    n, d = load_rsa_private_key(pem)
    header = b'{"alg":"RS256","typ":"JWT"}'
    # iss is inserted between two integer literals, so JSON-escape it defensively.
    iss_json = '"' + iss.replace("\\", "\\\\").replace('"', '\\"') + '"'
    payload = ('{"iat":%d,"exp":%d,"iss":%s}' % (iat_i, exp_i, iss_json)).encode("ascii")
    signing_input = _b64url(header) + b"." + _b64url(payload)
    digest = hashlib.sha256(signing_input).digest()
    t = _SHA256_DIGESTINFO + digest
    k = (n.bit_length() + 7) // 8
    if len(t) + 11 > k:
        raise SignerError("RSA modulus too small for a SHA-256 PKCS#1 v1.5 signature")
    ps = b"\xff" * (k - len(t) - 3)
    em = b"\x00\x01" + ps + b"\x00" + t
    m = int.from_bytes(em, "big")
    s = pow(m, d, n)
    signature = s.to_bytes(k, "big")
    return signing_input + b"." + _b64url(signature)


def main(argv) -> int:
    if len(argv) != 3:
        sys.stderr.write("sign-jwt-rs256: usage: sign-jwt-rs256.py <iss> <iat> <exp> (key on stdin)\n")
        return 2
    try:
        token = sign_jwt(argv[0], argv[1], argv[2], sys.stdin.buffer.read())
    except SignerError as exc:
        sys.stderr.write("sign-jwt-rs256: refusing to sign — %s\n" % exc)
        return 2
    sys.stdout.buffer.write(token)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
