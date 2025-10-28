# pages/02_Community.py
import streamlit as st
import pandas as pd
from lib.supabase_client import get_client

st.set_page_config(page_title="Community — RemedyAtlas", page_icon="🫶", layout="wide")
sb = get_client()

st.title("🫶 Community")
st.caption("Share folk remedies from your culture and browse others. Please be respectful. Not medical advice.")

# ---------------- Auth (email + password for simplicity) ----------------
def _is_logged_in():
    try:
        user = sb.auth.get_user()
        return user is not None and user.user is not None
    except Exception:
        return False

def _user_id():
    try:
        user = sb.auth.get_user()
        return str(user.user.id) if user and user.user else None
    except Exception:
        return None

with st.sidebar:
    st.header("Account")
    if _is_logged_in():
        st.success("You are logged in.")
        if st.button("Log out"):
            sb.auth.sign_out()
            st.rerun()
    else:
        tab_login, tab_signup = st.tabs(["Log in", "Sign up"])

        with tab_login:
            email = st.text_input("Email", key="login_email")
            password = st.text_input("Password", type="password", key="login_pw")
            if st.button("Log in"):
                try:
                    sb.auth.sign_in_with_password({"email": email.strip(), "password": password})
                    st.success("Logged in.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Login failed: {e}")

        with tab_signup:
            email2 = st.text_input("Email (sign up)", key="signup_email")
            pw2 = st.text_input("Password (sign up)", type="password", key="signup_pw")
            if st.button("Create account"):
                try:
                    sb.auth.sign_up({"email": email2.strip(), "password": pw2})
                    st.success("Account created. If email confirmation is required, check your inbox.")
                except Exception as e:
                    st.error(f"Sign-up failed: {e}")

st.divider()

# ---------------- Submit a remedy (auth required to post) ----------------
st.subheader("Share a remedy")

if not _is_logged_in():
    st.info("Log in to submit a remedy.")
else:
    with st.form("post_form", clear_on_submit=True):
        cols = st.columns(2)
        with cols[0]:
            country = st.text_input("Country (e.g., Lebanon)")
            region = st.text_input("Region (optional)")
            ailment = st.text_input("Ailment / Symptom (e.g., Cough)")
            plant_common = st.text_input("Plant (common name) (optional)")
            preparation = st.text_input("Preparation (e.g., Tea with honey)")
        with cols[1]:
            source_url = st.text_input("Source URL (optional)")

        remedy_text = st.text_area("Describe the remedy and cultural context", height=120)

        submitted = st.form_submit_button("Publish")
        if submitted:
            if not country or not ailment or not remedy_text:
                st.error("Country, Ailment and Remedy description are required.")
            else:
                try:
                    sb.table("posts").insert({
                        "user_id": _user_id(),
                        "country": country.strip(),
                        "region": region.strip() or None,
                        "ailment": ailment.strip(),
                        "remedy_text": remedy_text.strip(),
                        "plant_common": (plant_common.strip() or None),
                        "preparation": (preparation.strip() or None),
                        "source_url": (source_url.strip() or None),
                        "status": "published",
                    }).execute()
                    st.success("Thanks! Your remedy is live.")
                except Exception as e:
                    st.error(f"Could not publish: {e}")

st.divider()

# ---------------- Feed / listing ----------------
st.subheader("Latest community remedies")

c1, c2, c3 = st.columns([1,1,1])
with c1:
    f_country = st.text_input("Filter by country (contains)")
with c2:
    f_ailment = st.text_input("Filter by ailment (contains)")
with c3:
    newest_first = st.toggle("Newest first", value=True)

q = sb.table("posts").select("*").eq("status", "published")
if f_country:
    q = q.ilike("country", f"%{f_country}%")
if f_ailment:
    q = q.ilike("ailment", f"%{f_ailment}%")
q = q.order("created_at", desc=newest_first).limit(200)

try:
    data = q.execute().data or []
except Exception as e:
    st.error(f"Error loading posts: {e}")
    data = []

if not data:
    st.info("No posts yet. Be the first to share!")
else:
    df = pd.DataFrame(data)
    show_cols = ["created_at","country","region","ailment","plant_common","preparation","remedy_text","source_url"]
    for c in show_cols:
        if c not in df.columns:
            df[c] = None
    st.dataframe(
        df[show_cols].sort_values("created_at", ascending=not newest_first).reset_index(drop=True),
        use_container_width=True
    )
