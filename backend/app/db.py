"""Supabase-py client init using service role key."""

from app.config import SUPABASE_SERVICE_ROLE_KEY, SUPABASE_URL
from supabase import create_client

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
