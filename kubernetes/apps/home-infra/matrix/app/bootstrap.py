from pathlib import Path
import secrets

from signedjson.key import generate_signing_key, write_signing_keys


data_dir = Path("/data")

for filename in (
    "registration_shared_secret",
    "macaroon_secret_key",
    "form_secret",
):
    path = data_dir / filename
    if not path.exists():
        path.write_text(secrets.token_urlsafe(48), encoding="utf-8")
        path.chmod(0o600)

signing_key = data_dir / "matrix.signing.key"
if not signing_key.exists():
    with signing_key.open("w", encoding="utf-8") as stream:
        key_id = f"a_{secrets.token_hex(2)}"
        write_signing_keys(stream, (generate_signing_key(key_id),))
    signing_key.chmod(0o600)
