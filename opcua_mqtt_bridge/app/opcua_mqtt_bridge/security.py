import os
import subprocess
from asyncua import ua
from asyncua.crypto.security_policies import (
    SecurityPolicyNone,
    SecurityPolicyBasic128Rsa15,
    SecurityPolicyBasic256,
    SecurityPolicyBasic256Sha256,
)


def map_security_policy(policy: str):
    p = (policy or "None").strip()
    if p == "None":
        return SecurityPolicyNone
    if p == "Basic128Rsa15":
        return SecurityPolicyBasic128Rsa15
    if p == "Basic256":
        return SecurityPolicyBasic256
    if p == "Basic256Sha256":
        return SecurityPolicyBasic256Sha256
    raise ValueError(f"Unsupported security_policy: {policy}")


def map_security_mode(mode: str):
    m = (mode or "None").strip()
    if m == "None":
        return ua.MessageSecurityMode.None_
    if m == "Sign":
        return ua.MessageSecurityMode.Sign
    if m == "SignAndEncrypt":
        return ua.MessageSecurityMode.SignAndEncrypt
    raise ValueError(f"Unsupported security_mode: {mode}")


def cert_contains_uri(cert_pem_path: str, app_uri: str) -> bool:
    try:
        out = subprocess.check_output(
            ["openssl", "x509", "-in", cert_pem_path, "-noout", "-text"],
            text=True
        )
        return app_uri in out
    except Exception:
        return False


def pki_paths(pki_dir: str = "/data/pki") -> dict:
    trusted_server_dir = os.path.join(pki_dir, "trusted_server")
    os.makedirs(trusted_server_dir, exist_ok=True)
    return {
        "pki_dir": pki_dir,
        "client_cert": os.path.join(pki_dir, "client_cert.pem"),
        "client_key": os.path.join(pki_dir, "client_key.pem"),
        "trusted_server_dir": trusted_server_dir,
        "server_cert_path": os.path.join(trusted_server_dir, "server_cert.der"),
    }
