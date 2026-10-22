"""Provision an expiring local-operator profile; never prints the secret.

Load the resulting env file only into a loopback-only local RAG process. It is
not a cloud login/SSO adapter. Existing profiles are never silently overwritten.
"""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subject", required=True)
    parser.add_argument("--scope", choices=["business_rules", "law", "project_design"], action="append", required=True)
    parser.add_argument("--days", type=int, choices=range(1, 8), default=1)
    args = parser.parse_args()
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from app.reference_security import PrincipalRegistry
    folder = Path(__file__).resolve().parents[1] / "data"
    folder.mkdir(exist_ok=True)
    registry = folder / "local-review-principals.json"
    profile = folder / "local-review.env"
    if registry.exists() or profile.exists():
        parser.error("local review profile already exists; rotate explicitly, do not overwrite a live operator")
    key = secrets.token_urlsafe(48)
    value = {"principals": [{"subject": args.subject, "key_sha256": hashlib.sha256(key.encode()).hexdigest(),
        "namespaces": sorted(set(args.scope)), "roles": ["reviewer"],
        "valid_until": (datetime.now(timezone.utc) + timedelta(days=args.days)).isoformat()}]}
    PrincipalRegistry.model_validate(value)
    old_umask = os.umask(0o077)
    try:
        with registry.open("x", encoding="utf-8") as target:
            target.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
        with profile.open("x", encoding="utf-8") as target:
            target.write(f'RAG_DOCUMENT_REVIEW_PRINCIPALS_FILE="{registry.as_posix()}"\nRAG_UI_DOCUMENT_REVIEW_KEY="{key}"\n')
    finally:
        os.umask(old_umask)
    print(f"Created local-only operator profile: {profile}")
    print("Keep both files restricted to the service account; load the profile server-side, never paste its contents into the browser or Git.")


if __name__ == "__main__":
    main()
