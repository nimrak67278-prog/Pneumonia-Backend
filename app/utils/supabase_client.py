import os
from supabase import create_client, Client

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY")

# ✅ Check FIRST before doing anything
if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
    raise RuntimeError(
        "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in your .env file. "
        "Find these in your Supabase project under Settings -> API."
    )

if not SUPABASE_ANON_KEY:
    raise RuntimeError(
        "SUPABASE_ANON_KEY must be set in your .env file."
    )

# ✅ Create clients AFTER validation
supabase_auth: Client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

def get_fresh_admin_client() -> Client:
    return create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
