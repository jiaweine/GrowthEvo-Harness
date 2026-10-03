from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import ipaddress
import json
from pathlib import Path

import jwt
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

ISSUER = "https://issuer.example.test/growthevo"
AUDIENCE = "growthevo-ci"
SIGNING_KID = "growthevo-ci-signing-key"


def _write_private_key(path: Path, key: rsa.RSAPrivateKey) -> None:
    path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )


def _claims(*, issuer: str = ISSUER, audience: str = AUDIENCE, expires_in: int = 600):
    now = datetime.now(timezone.utc)
    return {
        "iss": issuer,
        "aud": audience,
        "sub": "ci-production-user",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=expires_in)).timestamp()),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output_dir")
    args = parser.parse_args()
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "GrowthEvo CI Root CA")])
    ca_subject_key_id = x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key())
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=2))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(ca_subject_key_id, critical=False)
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )

    tls_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    tls_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "host.docker.internal")])
    tls_cert = (
        x509.CertificateBuilder()
        .subject_name(tls_name)
        .issuer_name(ca_cert.subject)
        .public_key(tls_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=2))
        .add_extension(
            x509.SubjectAlternativeName(
                [
                    x509.DNSName("host.docker.internal"),
                    x509.DNSName("localhost"),
                    x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
                ]
            ),
            critical=False,
        )
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),
            critical=False,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(tls_key.public_key()),
            critical=False,
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )

    (output / "ca.pem").write_bytes(ca_cert.public_bytes(serialization.Encoding.PEM))
    (output / "tls-cert.pem").write_bytes(tls_cert.public_bytes(serialization.Encoding.PEM))
    _write_private_key(output / "tls-key.pem", tls_key)

    signing_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    _write_private_key(output / "signing-key.pem", signing_key)
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(signing_key.public_key()))
    jwk.update({"kid": SIGNING_KID, "use": "sig", "alg": "RS256"})
    (output / "jwks.json").write_text(
        json.dumps({"keys": [jwk]}, separators=(",", ":")),
        encoding="utf-8",
    )

    token_cases = {
        "valid.jwt": _claims(),
        "wrong-audience.jwt": _claims(audience="wrong-audience"),
        "wrong-issuer.jwt": _claims(issuer="https://wrong.example.test"),
        "expired.jwt": _claims(expires_in=-300),
    }
    for filename, claims in token_cases.items():
        token = jwt.encode(
            claims,
            signing_key,
            algorithm="RS256",
            headers={"kid": SIGNING_KID},
        )
        (output / filename).write_text(token, encoding="utf-8")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
