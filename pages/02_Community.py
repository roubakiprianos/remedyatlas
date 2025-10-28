# pages/02_Community.py
import re
import html
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

import streamlit as st
from supabase import create_client, Client

st.title("🌱 Community remedies")
st.caption("Share folk practices from your culture. Be kind. Not medical advice.")

# ================= Supabase client =================
@st.cache_resource
def get_sb() -> Client:
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_ANON_KEY"]
    return create_client(url, key)

sb = get_sb()

# ================= Auth helpers =================
def _get_user():
    try:
        u = sb.auth.get_user()
        return u.user if u and getattr(u, "user", None) else None
    except Exception:
        return None

def _is_logged_in() -> bool:
    return _get_user() is not None

def _user_id() -> Optional[str]:
    u = _get_user()
    return str(u.id) if u else None

def _email_local_part() -> str:
    u = _get_user()
    if not u or not getattr(u, "email", None):
        return "anon"
    return u.email.split("@", 1)[0]

def _safe_username(seed: str) -> str:
    s = (seed or "").strip()
    s = re.sub(r"\s+", "_", s)
    s = re.sub(r"[^a-zA-Z0-9_.-]", "", s)
    return s[:32] or "anon"

# ================= Profile helpers =================
def _load_profile(uid: str) -> Dict[str, Any]:
    try:
        res = sb.table("profiles").select("*").eq("id", uid).limit(1).execute()
        if res.data:
            return res.data[0]
        # create minimal profile if missing
        default_username = _safe_username(_email_local_part())
        ins = sb.table("profiles").insert({"id": uid, "username": default_username}).execute()
        if ins.data:
            return ins.data[0]
        return {"id": uid, "username": default_username}
    except Exception:
        return {"id": uid, "username": "anon"}

def _upsert_profile(uid: str, username: Optional[str], country: Optional[str]):
    payload = {"id": uid}
    if username is not None:
        payload["username"] = _safe_username(username)
    if country is not None:
        payload["country"] = (country or "").strip() or None
    sb.table("profiles").upsert(payload, on_conflict="id").execute()

def _profiles_map(user_ids: List[str]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    if not user_ids:
        return out
    try:
        res = sb.table("profiles").select("id,username,country").in_("id", user_ids).execute()
        for r in (res.data or []):
            out[str(r["id"])] = r
    except Exception:
        pass
    return out

# ================= Sidebar: Auth + Profile =================
with st.sidebar:
    st.header("Account")

    if _is_logged_in():
        st.success("You are logged in.")
        if st.button("Log out"):
            try:
                sb.auth.sign_out()
            finally:
                st.rerun()

        uid = _user_id()
        prof = _load_profile(uid)
        st.markdown("**Your profile**")
        new_username = st.text_input("Username", value=prof.get("username") or _safe_username(_email_local_part()))
        new_country  = st.text_input("Country (optional)", value=prof.get("country") or "")
        if st.button("Save profile"):
            try:
                _upsert_profile(uid, new_username, new_country)
                st.success("Profile saved.")
                st.rerun()
            except Exception as e:
                st.error(f"Could not save profile: {e}")

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
                    st.success("Account created.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Sign-up failed: {e}")

st.divider()

# ================= Posting form (no lat/lon) =================
st.subheader("📬 Share a remedy")

if not _is_logged_in():
    st.info("Log in to publish a community post.")
else:
    with st.form("post_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            ailment = st.text_input("Ailment / symptom", placeholder="e.g., headache, nausea")
            country = st.text_input("Country", placeholder="e.g., Lebanon")
            region = st.text_input("Region (optional)", placeholder="e.g., Middle East")
        with col2:
            plant_common = st.text_input("Plant/common name (optional)", placeholder="e.g., Peppermint")
            preparation = st.text_input("Preparation (optional)", placeholder="e.g., Tea, topical oil")
            source_url = st.text_input("Source (optional URL)")

        remedy_text = st.text_area(
            "Describe the remedy and cultural context",
            placeholder="Short description of the practice as used in your culture…",
            height=120,
        )

        submitted = st.form_submit_button("Publish")
        if submitted:
            if not ailment.strip() or not country.strip() or not remedy_text.strip():
                st.error("Please fill at least Ailment, Country, and Remedy description.")
            else:
                payload = {
                    "user_id": _user_id(),
                    "ailment": ailment.strip(),
                    "country": country.strip(),
                    "region": region.strip() or None,
                    "plant_common": plant_common.strip() or None,
                    "preparation": preparation.strip() or None,
                    "source_url": source_url.strip() or None,
                    "remedy_text": remedy_text.strip(),
                }
                try:
                    res = sb.table("posts").insert(payload).execute()
                    if getattr(res, "data", None):
                        st.success("Thanks! Your remedy is live.")
                        st.rerun()
                    else:
                        st.error("Could not publish (no data returned).")
                except Exception as e:
                    st.error(f"Could not publish: {e}")

st.divider()

# ================= Feed filters =================
st.subheader("🗺️ Latest community remedies")
c1, c2, c3 = st.columns([2, 2, 1])
with c1:
    q_country = st.text_input("Filter by country (contains)", "")
with c2:
    q_ailment = st.text_input("Filter by ailment (contains)", "")
with c3:
    newest_first = st.toggle("Newest first", value=True)

# ================= Data access =================
def fetch_posts() -> List[Dict[str, Any]]:
    q = sb.table("posts").select("*")
    # If 'status' column exists, filter to published; ignore if not present
    try:
        q = q.eq("status", "published")
    except Exception:
        pass
    if q_country.strip():
        q = q.ilike("country", f"%{q_country.strip()}%")
    if q_ailment.strip():
        q = q.ilike("ailment", f"%{q_ailment.strip()}%")
    q = q.order("created_at", desc=newest_first)
    res = q.execute()
    return res.data or []

def vote_count(post_id: str) -> int:
    try:
        res = sb.table("votes").select("post_id", count="exact").eq("post_id", post_id).execute()
        return int(res.count or 0)
    except Exception:
        return 0

def user_has_voted(post_id: str, user_id: str) -> bool:
    if not user_id:
        return False
    try:
        res = (sb.table("votes")
               .select("post_id,user_id")
               .eq("post_id", post_id)
               .eq("user_id", user_id)
               .limit(1)
               .execute())
        return bool(res.data)
    except Exception:
        return False

def toggle_vote(post_id: str, user_id: str):
    if user_has_voted(post_id, user_id):
        try:
            sb.table("votes").delete().eq("post_id", post_id).eq("user_id", user_id).execute()
        except Exception as e:
            st.error(f"Could not remove vote: {e}")
    else:
        try:
            sb.table("votes").insert({"post_id": post_id, "user_id": user_id, "empathy": True}).execute()
        except Exception as e:
            st.error(f"Could not add vote: {e}")

def fetch_comments(post_id: str) -> List[Dict[str, Any]]:
    try:
        res = sb.table("comments").select("*").eq("post_id", post_id).order("created_at", desc=True).execute()
        return res.data or []
    except Exception:
        return []

def add_comment(post_id: str, body: str):
    try:
        sb.table("comments").insert({"post_id": post_id, "user_id": _user_id(), "body": body.strip()}).execute()
    except Exception as e:
        st.error(f"Could not add comment: {e}")

def _fmt_date_ddmmyyyy(iso_string: str) -> str:
    try:
        dt = datetime.fromisoformat(iso_string.replace("Z", "+00:00")).astimezone(timezone.utc)
        return dt.strftime("%d/%m/%Y")
    except Exception:
        return iso_string

def _chip(text: str) -> str:
    return f"<span class='chip'>{html.escape(text)}</span>"

# ================= Feed render =================
posts: List[Dict[str, Any]] = []
err: Optional[str] = None
try:
    posts = fetch_posts()
except Exception as e:
    err = str(e)

if err:
    st.error(f"Error loading posts: {err}")
elif not posts:
    st.info("No posts yet. Be the first to share!")
else:
    # Minimal CSS
    st.markdown(
        """
        <style>
          .post-card{border-radius:14px;padding:14px 16px;margin:10px 0;background:#12171b;border:1px solid #1e2936;}
          .post-top{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:6px}
          .chip{display:inline-block;padding:2px 8px;border-radius:999px;font-size:12px;background:#1f2a36;color:#b7c5d3;border:1px solid #263445}
          .post-body{color:#d8e2ee;margin:6px 0}
        </style>
        """,
        unsafe_allow_html=True,
    )

    # author usernames
    uid_list = sorted({p["user_id"] for p in posts if p.get("user_id")})
    prof_map = _profiles_map(uid_list)
    current_uid = _user_id() or ""

    for p in posts:
        pid = p["id"]
        prof = prof_map.get(str(p.get("user_id")), {})
        username = prof.get("username") or "anon"
        when = _fmt_date_ddmmyyyy(p.get("created_at", ""))

        top_html_parts = [
            _chip("👤 " + username),
            _chip(when),
            _chip("🩺 " + (p.get("ailment") or "—")),
        ]
        country = p.get("country")
        region = p.get("region")
        if country:
            top_html_parts.append(_chip(country))
        if region:
            top_html_parts.append(_chip(region))
        if p.get("plant_common"):
            top_html_parts.append(_chip("🌿 " + p["plant_common"]))

        top_html = "".join(top_html_parts)

        vc = vote_count(pid)
        already = user_has_voted(pid, current_uid)

        st.markdown("<div class='post-card'>", unsafe_allow_html=True)
        st.markdown(f"<div class='post-top'>{top_html}</div>", unsafe_allow_html=True)

        st.markdown("<div class='post-body'>" + html.escape(p.get("remedy_text", "")) + "</div>", unsafe_allow_html=True)

        extras = []
        if p.get("preparation"):
            extras.append("Prep: " + html.escape(p["preparation"]))
        if p.get("source_url"):
            extras.append(f"[Source]({p['source_url']})")
        if extras:
            st.markdown(" • ".join(extras))

        btn_label = ("💚 Empathy" if not already else "💔 Remove vote") + f" · {vc}"
        if st.button(btn_label, key=f"vote-{pid}"):
            if not _is_logged_in():
                st.warning("Log in to vote.")
            else:
                toggle_vote(pid, current_uid)
                st.rerun()

        with st.expander("💬 Comments"):
            cs = fetch_comments(pid)
            if not cs:
                st.write("_No comments yet._")
            else:
                cm_uids = sorted({c["user_id"] for c in cs if c.get("user_id")})
                cm_map = _profiles_map(cm_uids)
                for c in cs:
                    cu = cm_map.get(str(c.get("user_id")), {})
                    cu_name = cu.get("username") or "anon"
                    when_c = _fmt_date_ddmmyyyy(c.get("created_at", ""))
                    st.markdown(f"- **{html.escape(cu_name)}** — {when_c}: {html.escape(c.get('body',''))}")

            new_c = st.text_input("Add a comment", key=f"c-{pid}")
            if st.button("Post comment", key=f"cbtn-{pid}"):
                if not new_c.strip():
                    st.warning("Write something first.")
                else:
                    add_comment(pid, new_c)
                    st.rerun()

        st.markdown("</div>", unsafe_allow_html=True)
