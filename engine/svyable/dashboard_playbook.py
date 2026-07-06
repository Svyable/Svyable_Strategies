"""Streamlit browser for daily strategy playbook cards and CI golden choice."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from svyable.golden_contract import (
    base_contract,
    config_repr,
    default_contract_path,
    golden_option_frame,
    load_golden_contract,
    registered_strategy_contract,
    save_golden_contract,
)
from svyable.strategy_playbook import render_candidate_playbook, write_playbook_bundle
from svyable.strategy_selection_service import StrategySelectionService


def _truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _candidate_option_label(board: pd.DataFrame, candidate_id: str) -> str:
    rows = board[board["candidate_id"].astype(str) == candidate_id]
    if rows.empty:
        return candidate_id
    row = rows.iloc[0]
    utility = row.get("utility_bps", "—")
    try:
        utility_text = f"{float(utility):.2f} bps"
    except (TypeError, ValueError):
        utility_text = "—"
    status = "eligible" if _truthy(row.get("eligible")) else "blocked"
    return f"{candidate_id} · {row.get('name', '')} · {status} · utility {utility_text}"


def _render_golden_contract(board: pd.DataFrame) -> None:
    st.markdown("### Golden CI contract")
    st.caption(
        "The golden strategy is the regression test fixture. It should be stable and representative; "
        "it is not automatically the best strategy to run with live capital."
    )
    path = default_contract_path()
    contract = load_golden_contract(path)
    cols = st.columns(4)
    cols[0].metric("Current golden", contract.get("label", contract.get("strategy_id", "—")))
    cols[1].metric("Kind", contract.get("kind", "—"))
    cols[2].metric("Provider", (contract.get("provider") or {}).get("kind", "—"))
    cols[3].metric("Config", config_repr(contract)[:42] + ("…" if len(config_repr(contract)) > 42 else ""))
    st.info(contract.get("reason", "No reason recorded."))

    options = golden_option_frame()
    st.dataframe(options, use_container_width=True, hide_index=True)
    selectable = ["base_nasdaq_lo"] + [
        cid for cid in board.get("candidate_id", pd.Series(dtype=str)).astype(str).tolist()
        if cid != "hold_current" and not cid.startswith("chimera_")
    ]
    selected = st.selectbox(
        "Choose a CI golden fixture candidate",
        selectable,
        help="Registered strategies become the pinned CI behavior contract after re-blessing golden_weights.json.",
    )
    reason = st.text_area(
        "Why this should be the golden contract",
        value=(
            "Use this as the representative deterministic behavior contract. "
            "This is separate from the daily PM decision."
        ),
    )
    warning = ""
    match = options[options["candidate_id"].astype(str) == selected]
    if not match.empty and bool(match.iloc[0].get("ml_enabled")):
        warning = (
            "This candidate has ML enabled. It may be a strong research strategy, but exact CI hashes "
            "can be more fragile across numerical environments. Prefer it only if you want CI to pin that behavior."
        )
        st.warning(warning)
    typed = st.text_input(
        f"Type `{selected}` to update `engine/tests/golden_contract.json`",
        value="",
    )
    if st.button("Save golden CI contract", disabled=typed.strip() != selected):
        try:
            payload = base_contract(reason=reason) if selected == "base_nasdaq_lo" else registered_strategy_contract(selected, reason=reason)
            saved = save_golden_contract(payload, path)
            st.success(
                f"Saved {saved}. Run `cd engine && python -m pytest tests/test_regression.py` "
                "and commit the updated golden artifacts if the change is intentional."
            )
            if warning:
                st.caption(warning)
        except Exception as exc:
            st.error(str(exc))


def render_strategy_playbook(service: StrategySelectionService, board: pd.DataFrame) -> None:
    st.subheader("📖 Strategy playbook")
    st.caption(
        "Flip through today’s candidate plays: what names the strategy would hold, what risk/regime state it sees, "
        "which sleeves/factors are live, and whether it clears the hold-current hurdle."
    )
    if board.empty:
        st.info("No candidate board yet. Run a fresh evaluation first.")
        return
    board_dir = service.latest_board_dir()
    if board_dir is None:
        st.info("No board directory found for the latest candidate board.")
        return

    left, right = st.columns([1, 3])
    with left:
        eligible_only = st.checkbox("Eligible only", value=False)
    display = board.copy()
    if eligible_only and "eligible" in display.columns:
        display = display[display["eligible"].map(_truthy)]
    if "utility_bps" in display.columns:
        display = display.sort_values("utility_bps", ascending=False)
    candidate_ids = display["candidate_id"].astype(str).tolist() if "candidate_id" in display.columns else []
    if not candidate_ids:
        st.warning("No candidates match the current filter.")
        return
    with right:
        selected = st.selectbox(
            "Flip through plays",
            candidate_ids,
            format_func=lambda cid: _candidate_option_label(board, cid),
        )

    if st.button("Write/update all playbook files", type="primary"):
        try:
            result = write_playbook_bundle(board, board_dir)
            st.success(f"Wrote {result['count']} playbooks to `{result['directory']}`.")
        except Exception as exc:
            st.error(str(exc))

    row = board[board["candidate_id"].astype(str) == selected].iloc[0]
    md = render_candidate_playbook(row, board=board, board_dir=board_dir)
    st.download_button(
        "Download selected playbook markdown",
        data=md,
        file_name=f"{selected}_playbook.md",
        mime="text/markdown",
    )
    st.markdown(md)

    st.divider()
    _render_golden_contract(board)
