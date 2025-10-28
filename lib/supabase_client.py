# lib/supabase_client.py
from supabase import create_client, Client
import streamlit as st

@st.cache_resource
def get_client() -> Client:
    try:
        url = st.secrets["SUPABASE_URL"].strip()
        key = st.secrets["SUPABASE_ANON_KEY"].strip()
    except KeyError as e:
        raise RuntimeError(
            f"Missing Streamlit secret: {e}. "
            "Add SUPABASE_URL and SUPABASE_ANON_KEY in Streamlit Cloud → App → Settings → Secrets."
        )
    return create_client(url, key)
