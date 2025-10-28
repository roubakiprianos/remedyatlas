# lib/supabase_client.py
import streamlit as st
from supabase import create_client, Client

def get_client() -> Client:
    """
    Return a Supabase client that is unique to the user's Streamlit session.
    This prevents auth from leaking across users.
    """
    if "sb_client" not in st.session_state:
        url = st.secrets["SUPABASE_URL"]
        key = st.secrets["SUPABASE_ANON_KEY"]
        st.session_state["sb_client"] = create_client(url, key)
    return st.session_state["sb_client"]
