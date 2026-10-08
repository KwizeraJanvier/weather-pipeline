import os
import time

import jwt
from fastapi import HTTPException

# Static (signed) embedding, NOT a public link - this keeps the Metabase
# dashboard gated behind this app's own login, since the token is only ever
# generated for a request that already passed get_current_user. A public
# link would bypass the auth system entirely for anyone who got the URL.
#
# Needs embedding enabled in Metabase (Admin settings -> Embedding) and the
# embedding secret key from that same page, plus the numeric dashboard id
# (visible in its URL, e.g. localhost:3000/dashboard/2 -> 2) with embedding
# turned on for that specific dashboard (Share -> Embed this dashboard).
METABASE_SITE_URL = os.environ.get("METABASE_SITE_URL", "http://localhost:3000")
METABASE_EMBED_SECRET = os.environ.get("METABASE_EMBED_SECRET")
METABASE_DASHBOARD_ID = os.environ.get("METABASE_DASHBOARD_ID")


def get_embed_url() -> str:
    if not METABASE_EMBED_SECRET or not METABASE_DASHBOARD_ID:
        raise HTTPException(
            status_code=503,
            detail="Metabase embedding isn't configured yet - set METABASE_EMBED_SECRET "
            "and METABASE_DASHBOARD_ID (see README).",
        )
    payload = {
        "resource": {"dashboard": int(METABASE_DASHBOARD_ID)},
        "params": {},
        "exp": round(time.time()) + 600,  # token itself expires in 10 minutes
    }
    token = jwt.encode(payload, METABASE_EMBED_SECRET, algorithm="HS256")
    return f"{METABASE_SITE_URL}/embed/dashboard/{token}#bordered=true&titled=true"
