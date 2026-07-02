"""Experiment management page (browse + metadata edit + agentic metadata + visibility)."""

from __future__ import annotations

import json
import logging

import streamlit as st

from graph_lineage.streamlit_ui.db.repository.experiment_repository import ExperimentRepository
from graph_lineage.streamlit_ui.utils.async_helpers import run_async
from graph_lineage.streamlit_ui.utils.errors import UIError
from graph_lineage.streamlit_ui.utils import get_neo4j_client
from graph_lineage.history.repository import ExperimentRepository as HistoryRepository

logger = logging.getLogger(__name__)

# ── Enum options (speculari alle costanti nel repository) ─────────────────────

_SCOPE_OPTIONS = [
    "baseline",
    "ablation",
    "hyperparameter_search",
    "architecture_change",
    "data_experiment",
    "regression_check",
]

_CONCLUSION_TYPE_OPTIONS = [
    "confirmed",
    "refuted",
    "inconclusive",
    "unexpected",
    "error",
]

_RETRY_POLICY_OPTIONS = [
    "none",
    "on_failure",
    "always",
    "if_promising",
]

_VALIDATION_SCOPE_OPTIONS = [
    "train_only",
    "held_out",
    "full_benchmark",
    "human_eval",
]

# ── Async helpers ─────────────────────────────────────────────────────────────

async def _list_rich(status_filter=None, search=None) -> list[dict]:
    repo = ExperimentRepository(get_neo4j_client())
    return await repo.list_rich(status_filter=status_filter, search=search)

async def _update_metadata(id: str, description: str | None, notes: str | None) -> dict:
    repo = ExperimentRepository(get_neo4j_client())
    return await repo.update_metadata(id=id, description=description, notes=notes)

async def _get_agentic(id: str) -> dict | None:
    repo = ExperimentRepository(get_neo4j_client())
    return await repo.get_agentic_metadata(id)

async def _update_agentic(id: str, **kwargs) -> dict:
    repo = ExperimentRepository(get_neo4j_client())
    return await repo.update_agentic_metadata(id, **kwargs)

async def _set_visibility(id: str, usable: bool) -> list[str]:
    repo = HistoryRepository(get_neo4j_client())
    return await repo.set_visibility(id, usable)

# ── UI helpers ────────────────────────────────────────────────────────────────

def _status_badge(status: str | None, usable: bool | None) -> str:
    if usable is False:
        return ":gray[HIDDEN]"
    if status == "COMPLETED":
        return ":green[COMPLETED]"
    if status == "RUNNING":
        return ":orange[RUNNING]"
    if status == "FAILED":
        return ":red[FAILED]"
    return f":blue[{status or 'UNKNOWN'}]"

def _selectbox_with_none(label: str, options: list[str], current: str | None, key: str) -> str | None:
    """Selectbox che include un'opzione vuota iniziale."""
    display = ["— not set —"] + options
    idx = 0
    if current in options:
        idx = options.index(current) + 1
    chosen = st.selectbox(label, display, index=idx, key=key)
    return None if chosen == "— not set —" else chosen

def _float_or_none(label: str, current: float | None, key: str, min_v=0.0, max_v=1.0, step=0.05) -> float | None:
    """Slider che ritorna None se l'utente non ha ancora impostato il valore."""
    use_it = st.checkbox(f"Set {label}", value=current is not None, key=f"{key}_enabled")
    if not use_it:
        return None
    default = current if current is not None else min_v
    return st.slider(label, min_value=min_v, max_value=max_v, value=float(default), step=step, key=key)

def _parse_json_textarea(raw: str, field_name: str) -> tuple[list | None, str | None]:
    """Parsea testo JSON da textarea; ritorna (valore, errore)."""
    raw = raw.strip()
    if not raw:
        return None, None
    try:
        parsed = json.loads(raw)
        if not isinstance(parsed, list):
            return None, f"{field_name} deve essere un array JSON"
        return parsed, None
    except json.JSONDecodeError as exc:
        return None, f"JSON non valido in {field_name}: {exc}"

def _render_evidences_help() -> None:
    st.caption(
        "Array JSON di oggetti. Esempio:\n"
        '```json\n[{"metric": "eval_loss", "value": 0.18, '
        '"delta_vs_baseline": -0.05, "significant": true}]\n```'
    )

def _render_open_questions_help() -> None:
    st.caption(
        'Array JSON di stringhe. Esempio:\n'
        '```json\n["Does this hold with 13B?", "Is improvement dataset-specific?"]\n```'
    )

# ── Sezioni del form agentico ─────────────────────────────────────────────────

def _section_identity(current: dict) -> dict:
    """Gruppo 1 — Identità e contesto."""
    st.markdown("#### 🔬 Identità e contesto")
    scope = _selectbox_with_none("Scope", _SCOPE_OPTIONS, current.get("scope"), "ag_scope")
    hypothesis = st.text_area(
        "Hypothesis",
        value=current.get("hypothesis") or "",
        height=80,
        key="ag_hypothesis",
        help="Claim verificabile scritto PRIMA del run. Es: 'Aumentare LR di 10x ridurrà loss del 5%'.",
    )
    motivation = st.text_area(
        "Motivation",
        value=current.get("motivation") or "",
        height=80,
        key="ag_motivation",
        help="Quale osservazione su esperimenti precedenti ha motivato questo run.",
    )
    return {
        "scope": scope,
        "hypothesis": hypothesis.strip() or None,
        "motivation": motivation.strip() or None,
    }

def _section_knowledge(current: dict) -> tuple[dict, list[str]]:
    """Gruppo 2 — Conoscenza estratta post-run. Ritorna (valori, errori)."""
    st.markdown("#### 📊 Conoscenza estratta post-run")
    errors: list[str] = []

    conclusion = st.text_area(
        "Conclusion",
        value=current.get("conclusion") or "",
        height=100,
        key="ag_conclusion",
        help="Cosa hai imparato, indipendentemente dal successo. Un run fallito con buona conclusion è prezioso.",
    )
    conclusion_type = _selectbox_with_none(
        "Conclusion type", _CONCLUSION_TYPE_OPTIONS, current.get("conclusion_type"), "ag_conclusion_type"
    )

    st.markdown("**Evidences** (JSON array)")
    _render_evidences_help()
    raw_evidences = current.get("evidences")
    evidences_default = json.dumps(raw_evidences, indent=2) if raw_evidences else ""
    evidences_raw = st.text_area("Evidences JSON", value=evidences_default, height=120, key="ag_evidences", label_visibility="collapsed")
    evidences, ev_err = _parse_json_textarea(evidences_raw, "evidences")
    if ev_err:
        errors.append(ev_err)

    st.markdown("**Open questions** (JSON array of strings)")
    _render_open_questions_help()
    raw_oq = current.get("open_questions")
    oq_default = json.dumps(raw_oq, indent=2) if raw_oq else ""
    oq_raw = st.text_area("Open questions JSON", value=oq_default, height=100, key="ag_open_questions", label_visibility="collapsed")
    open_questions, oq_err = _parse_json_textarea(oq_raw, "open_questions")
    if oq_err:
        errors.append(oq_err)

    return {
        "conclusion": conclusion.strip() or None,
        "conclusion_type": conclusion_type,
        "evidences": evidences,
        "open_questions": open_questions,
    }, errors

def _section_navigation(current: dict) -> dict:
    """Gruppo 3 — Navigabilità del grafo."""
    st.markdown("#### 🗺️ Navigabilità del grafo")

    col1, col2 = st.columns(2)
    with col1:
        is_base = st.checkbox(
            "Is base experiment",
            value=bool(current.get("is_base", False)),
            key="ag_is_base",
            help="Marca come baseline di riferimento.",
        )
        dead_end = st.checkbox(
            "Dead end",
            value=bool(current.get("dead_end", False)),
            key="ag_dead_end",
            help="Direzione sterile: non esplorare ulteriormente. Distinto da usable=false.",
        )

    with col2:
        exploration_priority = _float_or_none(
            "Exploration priority",
            current.get("exploration_priority"),
            "ag_exploration_priority",
            min_v=0.0, max_v=1.0, step=0.05,
        )

    st.markdown("**Tags** (separati da virgola)")
    raw_tags = current.get("tags") or []
    tags_str = st.text_input(
        "Tags",
        value=", ".join(raw_tags) if isinstance(raw_tags, list) else "",
        key="ag_tags",
        label_visibility="collapsed",
        placeholder="low-lr, no-warmup, dataset-v2",
    )
    tags = [t.strip() for t in tags_str.split(",") if t.strip()] if tags_str.strip() else []

    return {
        "is_base": is_base,
        "dead_end": dead_end,
        "exploration_priority": exploration_priority,
        "tags": tags,
    }

def _section_reliability(current: dict) -> dict:
    """Gruppo 4 — Riproducibilità e affidabilità."""
    st.markdown("#### 🎯 Affidabilità")

    confidence = _float_or_none(
        "Confidence",
        current.get("confidence"),
        "ag_confidence",
        min_v=0.0, max_v=1.0, step=0.05,
    )
    retry_policy = _selectbox_with_none(
        "Retry policy", _RETRY_POLICY_OPTIONS, current.get("retry_policy"), "ag_retry_policy"
    )
    validation_scope = _selectbox_with_none(
        "Validation scope", _VALIDATION_SCOPE_OPTIONS, current.get("validation_scope"), "ag_validation_scope"
    )
    return {
        "confidence": confidence,
        "retry_policy": retry_policy,
        "validation_scope": validation_scope,
    }

def _section_costs(current: dict) -> dict:
    """Gruppo 5 — Metadati computazionali."""
    st.markdown("#### 💰 Costi computazionali")

    col1, col2, col3 = st.columns(3)
    with col1:
        compute_enabled = st.checkbox("Set compute cost", value=current.get("compute_cost") is not None, key="ag_compute_enabled")
        compute_cost = (
            st.number_input("Compute cost (GPU-h)", min_value=0.0, value=float(current.get("compute_cost") or 0.0), step=0.5, key="ag_compute_cost")
            if compute_enabled else None
        )
    with col2:
        duration_enabled = st.checkbox("Set duration", value=current.get("duration_seconds") is not None, key="ag_duration_enabled")
        duration_seconds = (
            st.number_input("Duration (seconds)", min_value=0, value=int(current.get("duration_seconds") or 0), step=60, key="ag_duration_seconds")
            if duration_enabled else None
        )
    with col3:
        gain_enabled = st.checkbox("Set estimated gain", value=current.get("estimated_gain") is not None, key="ag_gain_enabled")
        estimated_gain = (
            st.number_input("Estimated gain (Δ metric)", value=float(current.get("estimated_gain") or 0.0), step=0.01, format="%.4f", key="ag_estimated_gain")
            if gain_enabled else None
        )

    return {
        "compute_cost": compute_cost,
        "duration_seconds": int(duration_seconds) if duration_seconds is not None else None,
        "estimated_gain": estimated_gain,
    }

# ── Tab agentic metadata ──────────────────────────────────────────────────────

def _render_tab_agentic(experiments: list[dict]) -> None:
    st.subheader("Agentic Metadata")
    st.caption(
        "Compilare questi campi prima e dopo ogni run per abilitare le query "
        "di esplorazione, navigazione e cost-benefit sul grafo."
    )

    if not experiments:
        st.info("Nessun esperimento disponibile.")
        return

    exp_ids = [e["id"] for e in experiments]
    selected_exp_id = st.selectbox("Seleziona esperimento", exp_ids, key="ag_exp_select")
    if not selected_exp_id:
        return

    # Carica i metadati correnti dal DB
    try:
        current = run_async(_get_agentic(selected_exp_id)) or {}
    except UIError as exc:
        st.error(f"Errore nel caricamento: {exc.user_message}")
        return

    st.divider()

    # Suddivisione in sezioni collassabili per non sovraccaricare la UI
    with st.expander("🔬 Identità e contesto (pre-run)", expanded=True):
        identity_vals = _section_identity(current)

    with st.expander("📊 Conoscenza estratta (post-run)", expanded=True):
        knowledge_vals, knowledge_errors = _section_knowledge(current)

    with st.expander("🗺️ Navigabilità del grafo", expanded=False):
        nav_vals = _section_navigation(current)

    with st.expander("🎯 Affidabilità e riproducibilità", expanded=False):
        reliability_vals = _section_reliability(current)

    with st.expander("💰 Costi computazionali", expanded=False):
        cost_vals = _section_costs(current)

    # Mostra errori di validazione prima del bottone
    for err in knowledge_errors:
        st.error(err)

    st.divider()
    col_save, col_reset = st.columns([2, 1])

    with col_save:
        if st.button("💾 Salva metadati agentici", type="primary", disabled=bool(knowledge_errors)):
            all_vals = {
                **identity_vals,
                **knowledge_vals,
                **nav_vals,
                **reliability_vals,
                **cost_vals,
            }
            # Rimuove None espliciti per i bool con default (is_base, dead_end)
            # ma li passa comunque perché l'utente può volerli portare a False
            try:
                run_async(_update_agentic(selected_exp_id, **all_vals))
                st.success(f"✅ Metadati agentici salvati per `{selected_exp_id}`")
                st.rerun()
            except UIError as exc:
                st.error(f"Errore: {exc.user_message}")

    with col_reset:
        if st.button("🔄 Ricarica dal DB"):
            st.rerun()

    # Preview compatta dei valori correnti (letti dal DB, non dalla form)
    with st.expander("👁 Preview nodo Neo4j (valori correnti in DB)", expanded=False):
        st.json(current)

# ── Entry point ───────────────────────────────────────────────────────────────

def run() -> None:
    """Run experiment management page."""
    st.title("Experiment Management")

    tab_browse, tab_edit, tab_agentic, tab_visibility = st.tabs(
        ["Browse", "Edit Metadata", "Agentic Metadata", "Visibility"]
    )

    # ── Browse ────────────────────────────────────────────────────────────────
    with tab_browse:
        st.subheader("Browse Experiments")

        col_filter, col_search = st.columns([1, 2])
        with col_filter:
            status_filter = st.selectbox("Status", ["All", "COMPLETED", "RUNNING", "FAILED"])
        with col_search:
            search = st.text_input("Search", placeholder="Filter by id or description")

        try:
            filter_val = None if status_filter == "All" else status_filter
            search_val = search.strip() if search and search.strip() else None
            experiments = run_async(_list_rich(status_filter=filter_val, search=search_val))

            if experiments:
                for exp in experiments:
                    badge = _status_badge(exp.get("status"), exp.get("usable"))
                    with st.expander(f"{exp.get('id', 'N/A')} {badge}"):
                        col1, col2 = st.columns(2)
                        with col1:
                            st.markdown(f"**Model:** {exp.get('model_name', 'N/A')}")
                            st.markdown(f"**Recipe:** {exp.get('recipe_name', 'N/A')}")
                            if exp.get("technique_code"):
                                st.markdown(
                                    f"**Technique:** {exp.get('technique_code')} "
                                    f"({exp.get('framework_code', 'N/A')})"
                                )
                        with col2:
                            st.markdown(f"**Checkpoints:** {exp.get('ckp_count', 0)}")
                            st.caption(f"Config hash: {exp.get('config_hash', 'N/A')}")
                            st.caption(f"Created: {exp.get('created_at', 'N/A')}")
                        if exp.get("description"):
                            st.markdown(f"**Description:** {exp.get('description')}")
                        if exp.get("notes"):
                            st.markdown(f"**Notes:** {exp.get('notes')}")

                        # Pillole agentiche nel browse (read-only, rapide)
                        tags = exp.get("tags") or []
                        if tags:
                            st.markdown(" ".join(f"`{t}`" for t in tags))
                        scope = exp.get("scope")
                        dead_end = exp.get("dead_end")
                        conclusion_type = exp.get("conclusion_type")
                        if any(v is not None for v in [scope, dead_end, conclusion_type]):
                            parts = []
                            if scope:
                                parts.append(f"scope: **{scope}**")
                            if conclusion_type:
                                parts.append(f"outcome: **{conclusion_type}**")
                            if dead_end:
                                parts.append(":red[dead end]")
                            st.caption(" · ".join(parts))
            else:
                st.info("🔬 No experiments found")
                st.caption(
                    "Experiments are created automatically when you run a "
                    "training function with @lineage_tracker()."
                )
        except UIError as e:
            st.error(f"Error: {e.user_message}")

    # ── Edit Metadata ─────────────────────────────────────────────────────────
    with tab_edit:
        st.subheader("Edit Metadata")
        try:
            experiments = run_async(_list_rich())

            if not experiments:
                st.info("No experiments available to edit.")
            else:
                exp_ids = [e["id"] for e in experiments]
                selected_exp_id = st.selectbox("Select Experiment", exp_ids, key="edit_exp")

                if selected_exp_id:
                    current = next((e for e in experiments if e["id"] == selected_exp_id), None)
                    if current:
                        with st.form("edit_metadata_form"):
                            description = st.text_area(
                                "Description",
                                value=current.get("description", "") or "",
                            )
                            notes = st.text_area(
                                "Notes",
                                value=current.get("notes", "") or "",
                            )
                            if st.form_submit_button("Save Metadata"):
                                try:
                                    run_async(_update_metadata(selected_exp_id, description, notes))
                                    st.success("Metadata updated successfully!")
                                except UIError as e:
                                    st.error(f"Error: {e.user_message}")
        except UIError as e:
            st.error(f"Error: {e.user_message}")

    # ── Agentic Metadata ──────────────────────────────────────────────────────
    with tab_agentic:
        try:
            experiments = run_async(_list_rich())
            _render_tab_agentic(experiments)
        except UIError as e:
            st.error(f"Error: {e.user_message}")

    # ── Visibility ────────────────────────────────────────────────────────────
    with tab_visibility:
        st.subheader("Experiment Visibility")
        try:
            experiments = run_async(_list_rich())

            if not experiments:
                st.info("No experiments available.")
            else:
                exp_ids = [e["id"] for e in experiments]
                selected_exp_id = st.selectbox("Select Experiment", exp_ids, key="vis_exp")

                if selected_exp_id:
                    current = next((e for e in experiments if e["id"] == selected_exp_id), None)
                    if current:
                        is_usable = current.get("usable", True)
                        if is_usable is not False:
                            st.markdown("**Current status:** Visible")
                            st.warning("This will hide the experiment from browse views.")
                            confirm = st.checkbox(
                                "I understand this experiment will be hidden",
                                key="confirm_hide_exp",
                            )
                            if confirm and st.button("Hide Experiment"):
                                try:
                                    affected = run_async(_set_visibility(selected_exp_id, False))
                                    st.success(f"Experiment hidden. Affected: {len(affected)} experiment(s).")
                                except Exception as e:
                                    st.error(f"Error: {str(e)}")
                        else:
                            st.markdown("**Current status:** :gray[HIDDEN]")
                            if st.button("Restore Experiment"):
                                try:
                                    affected = run_async(_set_visibility(selected_exp_id, True))
                                    st.success(
                                        f"Experiment restored. Affected: {len(affected)} experiment(s) "
                                        "(including ancestor chain)."
                                    )
                                except Exception as e:
                                    st.error(f"Error: {str(e)}")
        except UIError as e:
            st.error(f"Error: {e.user_message}")

