import streamlit as st

from hiretrack import auth, db as dbm, service, ui
from hiretrack.options import DEFAULT_OPTIONS, OPTION_TITLES
from hiretrack.scoring import LABELS

ss = st.session_state


def render():
    d = dbm.get_db()
    st.title("⚙️ Settings")
    msg = ss.pop("_flash", None)
    if msg:
        st.success(msg)

    st.subheader("Default scoring weights for new jobs")
    cur = service.default_weights()
    vals, cols = {}, st.columns(5)
    for col, (k, label) in zip(cols, LABELS.items()):
        with col:
            vals[k] = st.number_input(label, min_value=0, max_value=100, value=int(cur[k]), step=5, key=f"dw_{k}")
    st.caption(f"Total {sum(vals.values())}. Existing jobs keep their own weights (change them under Jobs → Scoring weights).")
    if st.button("💾 Save default weights", key="dw_save", disabled=sum(vals.values()) <= 0):
        service.save_default_weights(vals)
        ss["_flash"] = "Default weights saved."
        st.rerun()

    st.divider()
    st.subheader("Dropdown choices")
    st.write("Built-in choices cannot be removed, but anything you type under “Other…” is remembered here. "
             "You can add or remove your own choices.")
    cat = st.selectbox("List", list(OPTION_TITLES), format_func=OPTION_TITLES.get, key="opt_cat")
    st.caption("Built-in: " + ", ".join(DEFAULT_OPTIONS.get(cat, [])))
    custom = d.custom_options().get(cat, [])
    if custom:
        for label in custom:
            a, b = st.columns([4, 1])
            a.write(label)
            if b.button("Remove", key=f"optdel_{cat}_{label}"):
                d.delete_option(cat, label)
                ui.invalidate_options()
                st.rerun()
    else:
        st.caption("You have not added any custom choices to this list yet.")
    nonce = ss.get("_optn", 0)
    new = st.text_input("Add a choice", key=f"optnew_{cat}_{nonce}")
    if st.button("➕ Add", key="optadd") and new.strip():
        d.add_option(cat, new.strip())
        ui.invalidate_options()
        ss["_optn"] = nonce + 1
        st.rerun()

    st.divider()
    st.subheader("Security")
    st.write("• Password protection: " + ("**on**" if auth.password_required() else "**off** (local mode only)"))
    st.write("• Database: " + ("local file" if d.sqlite else "cloud PostgreSQL (private; the public API is locked down)"))
    st.caption("To change the password, edit APP_PASSWORD in the app's Secrets and reboot the app.")
