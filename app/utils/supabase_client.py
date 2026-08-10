"""
Initializes a single shared Supabase client for the backend, using the
service_role key.

IMPORTANT: the service_role key bypasses Row Level Security entirely and
has full admin access to the database. It must NEVER be sent to the
React Native app, committed to git, or exposed in any client-facing code.
It lives only in this backend's .env file (see .env.example).
"""

import os
from supabase import create_client, Client

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")

SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY")

supabase_auth: Client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
    raise RuntimeError(
        "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in your .env file. "
        "Find these in your Supabase project under Settings -> API."
    )
def get_fresh_admin_client() -> Client:
    return create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

    
supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
