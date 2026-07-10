"""Experiment management page (browse + metadata edit + agentic metadata)."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional
import streamlit as st

from graph_lineage.data_classes.neo4j.nodes.experiment import Experiment
from graph_lineage.streamlit_ui.db.repository.experiment_repository import (
    CONCLUSION_TYPE_OPTIONS,
    RETRY_POLICY_OPTIONS,
    SCOPE_OPTIONS,
    VALIDATION_SCOPE_OPTIONS,
    ExperimentRepository,
)
from graph_lineage.streamlit_ui.utils.async_helpers import run_async
from graph_lineage.streamlit_ui.utils.errors import UIError
from graph_lineage.streamlit_ui.utils import get_neo4j_client

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════════

_AGENTIC_SECTIONS = {
    "identity": "🔬 Identità e contesto",
    "knowledge": "📊 Conoscenza estratta",
    "navigation": "🗺️ Navigabilità",
    "reliability": "🎯 Affidabilità",
    "costs": "💰 Costi computazionali",
}

_KNOWN_CORE_FIELDS = {
    "id", "created_at", "updated_at", "description", "uri", "base", "deep",
    "name", "chain_id", "status", "exit_status", "exit_msg",
    "strategy", "experiment_type", "model_id", "model_uri",
    "recipe_id", "component_id", "codebase", "changed_files",
    "usable", "manual_save", "metrics_uri", "agentic_metadata",
    # UI-computed lineage fields
    "model_name", "recipe_name", "component_technique", "component_framework",
    "ckp_count", "config_hash",
    # Agentic fields (handled separately)
    "scope", "hypothesis", "motivation", "conclusion", "conclusion_type",
    "evidences", "open_questions", "lessons_learned",
    "is_base", "exploration_priority", "dead_end", "tags",
    "confidence", "retry_policy", "validation_scope",
    "compute_cost", "duration_seconds", "estimated_gain",
}


# ═══════════════════════════════════════════════════════════════════════════════
# SESSION STATE HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def _init_session_state(key: str, default: Any) -> Any:
    if key not in st.session_state:
        st.session_state[key] = default
    return st.session_state[key]


def _clear_session_prefix(prefix: str) -> None:
    """Remove all session state keys starting with prefix."""
    for k in list(st.session_state.keys()):
        if k.startswith(prefix):
            del st.session_state[k]


# ═══════════════════════════════════════════════════════════════════════════════
# UI HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def _status_badge(status: Any, usable: Optional[bool]) -> str:
    status_str = status.value if hasattr(status, "value") else str(status)
    if usable is False:
        return ":gray[HIDDEN]"
    if status_str == "COMPLETED":
        return ":green[COMPLETED]"
    if status_str == "RUNNING":
        return ":orange[RUNNING]"
    if status_str == "FAILED":
        return ":red[FAILED]"
    return f":blue[{status_str or 'UNKNOWN'}]"


def _selectbox_with_none(
    label: str,
    options: List[str],
    current: Optional[str],
    key: str,
) -> Optional[str]:
    display = ["— not set —"] + options
    idx = 0
    if current in options:
        idx = options.index(current) + 1
    chosen = st.selectbox(label, display, index=idx, key=key)
    return None if chosen == "— not set —" else chosen


def _float_or_none(
    label: str,
    current: Optional[float],
    key: str,
    min_v: float = 0.0,
    max_v: float = 1.0,
    step: float = 0.05,
) -> Optional[float]:
    use_it = st.checkbox(
        f"Set {label}", value=current is not None, key=f"{key}_enabled"
    )
    if not use_it:
        return None
    default = float(current) if current is not None else min_v
    return st.slider(
        label, min_value=min_v, max_value=max_v, value=default, step=step, key=key
    )


def _parse_json_textarea(raw: str, field_name: str) -> tuple[Optional[Any], Optional[str]]:
    raw = raw.strip()
    if not raw:
        return None, None
    try:
        return json.loads(raw), None
    except json.JSONDecodeError as exc:
        return None, f"JSON non valido in {field_name}: {exc}"


def _to_json_pretty(value: Any) -> str:
    if value is None:
        return ""
    return json.dumps(value, indent=2, ensure_ascii=False, default=str)


# ═══════════════════════════════════════════════════════════════════════════════
# MULTI-ITEM LIST EDITOR
# ═══════════════════════════════════════════════════════════════════════════════

def _render_multi_item_editor(
    label: str,
    items: Optional[List[str]],
    key: str,
    placeholder: str = "Enter item...",
) -> List[str]:
    """Dynamic list of text items with add/remove. Uses session state."""
    session_key = f"{key}_items"
    if session_key not in st.session_state:
        st.session_state[session_key] = list(items) if items else []

    current_items: List[str] = st.session_state[session_key]

    st.markdown(f"**{label}**")
    to_remove: List[int] = []

    for i, item in enumerate(current_items):
        col1, col2 = st.columns([6, 1])
        with col1:
            current_items[i] = st.text_input(
                f"Item {i+1}",
                value=item,
                key=f"{key}_item_{i}",
                label_visibility="collapsed",
                placeholder=placeholder,
            )
        with col2:
            if st.button("🗑️", key=f"{key}_del_{i}"):
                to_remove.append(i)

    for idx in sorted(to_remove, reverse=True):
        current_items.pop(idx)
        st.rerun()

    if st.button("➕ Add item", key=f"{key}_add"):
        current_items.append("")
        st.rerun()

    return [x.strip() for x in current_items if x.strip()]


def _render_json_array_editor(
    label: str,
    items: Optional[List[Dict[str, Any]]],
    key: str,
    schema_hint: str = '[{"metric": "eval_loss", "value": 0.18}]',
) -> tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    """JSON array editor with validation."""
    st.markdown(f"**{label}**")
    st.caption(f"Array JSON di oggetti. Esempio:\n```json\n{schema_hint}\n```")

    current = items if items else []
    raw = st.text_area(
        f"{label} JSON",
        value=_to_json_pretty(current),
        height=120,
        key=f"{key}_json",
        label_visibility="collapsed",
    )
    if not raw.strip():
        return None, None

    parsed, err = _parse_json_textarea(raw, label)
    if err:
        return None, err
    if not isinstance(parsed, list):
        return None, f"{label} deve essere un array JSON"

    return parsed, None


# ═══════════════════════════════════════════════════════════════════════════════
# DYNAMIC EXTRA FIELDS EDITOR (for agentic metadata sections)
# ═══════════════════════════════════════════════════════════════════════════════

def _render_dynamic_fields_editor(
    section_key: str,
    existing: Dict[str, Any],
) -> Dict[str, Any]:
    """Render UI for adding/removing custom fields within an agentic section.
    
    Returns a dict of extra fields to merge into that section.
    """
    session_key = f"dyn_{section_key}"
    if session_key not in st.session_state:
        # Extract already-existing dynamic fields (not in known agentic fields)
        known_agentic = {
            "scope", "hypothesis", "motivation", "conclusion", "conclusion_type",
            "evidences", "open_questions", "lessons_learned", "is_base", "dead_end",
            "exploration_priority", "tags", "confidence", "retry_policy",
            "validation_scope", "compute_cost", "duration_seconds", "estimated_gain",
        }
        dynamic = {
            k: v for k, v in existing.items()
            if k not in known_agentic and v is not None
        }
        st.session_state[session_key] = dynamic

    dynamic_fields: Dict[str, Any] = st.session_state[session_key]

    st.markdown("---")
    st.markdown("**➕ Custom fields in this section**")
    st.caption("Aggiungi campi arbitrari che verranno salvati in questa sezione.")

    # Display existing
    to_remove: List[str] = []
    for field_name, field_value in list(dynamic_fields.items()):
        col1, col2, col3 = st.columns([3, 6, 1])
        with col1:
            st.text(field_name)
        with col2:
            if isinstance(field_value, bool):
                dynamic_fields[field_name] = st.checkbox(
                    "Value", value=field_value,
                    key=f"{session_key}_{field_name}_val",
                    label_visibility="collapsed",
                )
            elif isinstance(field_value, (int, float)):
                dynamic_fields[field_name] = st.number_input(
                    "Value", value=float(field_value),
                    key=f"{session_key}_{field_name}_val",
                    label_visibility="collapsed",
                )
            elif isinstance(field_value, (list, dict)):
                raw = st.text_area(
                    "Value", value=_to_json_pretty(field_value),
                    height=60,
                    key=f"{session_key}_{field_name}_val",
                    label_visibility="collapsed",
                )
                parsed, err = _parse_json_textarea(raw, field_name)
                if err:
                    st.error(err)
                else:
                    dynamic_fields[field_name] = parsed
            else:
                dynamic_fields[field_name] = st.text_input(
                    "Value",
                    value=str(field_value) if field_value is not None else "",
                    key=f"{session_key}_{field_name}_val",
                    label_visibility="collapsed",
                )
        with col3:
            if st.button("🗑️", key=f"{session_key}_del_{field_name}"):
                to_remove.append(field_name)

    for k in to_remove:
        dynamic_fields.pop(k, None)
        st.rerun()

    # Add new
    st.markdown("**Add new field:**")
    col_name, col_type, col_add = st.columns([3, 2, 1])
    with col_name:
        new_name = st.text_input(
            "Name", key=f"{session_key}_new_name",
            label_visibility="collapsed", placeholder="field_name",
        )
    with col_type:
        new_type = st.selectbox(
            "Type", ["text", "number", "boolean", "json"],
            key=f"{session_key}_new_type",
            label_visibility="collapsed",
        )
    with col_add:
        add_clicked = st.button("➕ Add", key=f"{session_key}_add_btn")

    if add_clicked and new_name:
        if new_name in {
            "scope", "hypothesis", "motivation", "conclusion", "conclusion_type",
            "evidences", "open_questions", "lessons_learned", "is_base", "dead_end",
            "exploration_priority", "tags", "confidence", "retry_policy",
            "validation_scope", "compute_cost", "duration_seconds", "estimated_gain",
        }:
            st.error(f"'{new_name}' is a reserved fixed field.")
        elif new_name in dynamic_fields:
            st.error(f"'{new_name}' already exists.")
        else:
            defaults = {"text": "", "number": 0.0, "boolean": False, "json": []}
            dynamic_fields[new_name] = defaults[new_type]
            st.rerun()

    return dynamic_fields


# ═══════════════════════════════════════════════════════════════════════════════
# EXPERIMENT -> DICT (for UI rendering)
# ═══════════════════════════════════════════════════════════════════════════════

def _experiment_to_dict(exp: Experiment) -> Dict[str, Any]:
    """Convert Experiment to flat dict for UI rendering.
    
    Preserves ALL fields including extras via model_extra.
    """
    base = {
        "id": exp.id,
        "status": exp.status.value if hasattr(exp.status, "value") else exp.status,
        "description": exp.description,
        "usable": exp.usable,
        "created_at": exp.created_at,
        "updated_at": exp.updated_at,
        "name": exp.name,
    }
    # Merge declared fields
    for field_name in exp.model_fields:
        if field_name not in base:
            val = getattr(exp, field_name, None)
            base[field_name] = val

    # FIX: Unisci i campi extra usando model_extra invece di custom_fields
    if exp.model_extra:
        base.update(exp.model_extra)

    return base

# ═══════════════════════════════════════════════════════════════════════════════
# ASYNC DB HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

async def _list_with_lineage(
    status_filter: Optional[str] = None,
    search: Optional[str] = None,
) -> List[Experiment]:
    repo = ExperimentRepository(get_neo4j_client())
    return await repo.list_with_lineage(status_filter=status_filter, search=search)


async def _update_metadata(
    id: str,
    description: Optional[str],
    notes: Optional[str],
    **extra: Any,
) -> Experiment:
    repo = ExperimentRepository(get_neo4j_client())
    return await repo.update_metadata(id=id, description=description, notes=notes, **extra)


async def _get_agentic(id: str) -> Dict[str, Any]:
    repo = ExperimentRepository(get_neo4j_client())
    return await repo.get_agentic_metadata(id)


async def _update_agentic(id: str, agentic_metadata: Dict[str, Any]) -> Experiment:
    repo = ExperimentRepository(get_neo4j_client())
    return await repo.update_agentic_metadata(id, agentic_metadata=agentic_metadata)


# ═══════════════════════════════════════════════════════════════════════════════
# AGENTIC METADATA SECTION RENDERERS
# Each section returns its portion of the nested agentic_metadata dict
# ═══════════════════════════════════════════════════════════════════════════════

def _section_identity(current: Dict[str, Any], key_prefix: str) -> Dict[str, Any]:
    """Gruppo 1 — Identità e contesto."""
    st.markdown("#### 🔬 Identità e contesto")

    scope = _selectbox_with_none(
        "Scope", SCOPE_OPTIONS, current.get("scope"), f"{key_prefix}_scope"
    )
    hypothesis = st.text_area(
        "Hypothesis",
        value=current.get("hypothesis") or "",
        height=80,
        key=f"{key_prefix}_hypothesis",
        help="Claim verificabile scritto PRIMA del run.",
    )
    motivation = st.text_area(
        "Motivation",
        value=current.get("motivation") or "",
        height=80,
        key=f"{key_prefix}_motivation",
        help="Quale osservazione su esperimenti precedenti ha motivato questo run.",
    )

    # Dynamic extra fields for this section
    extra = _render_dynamic_fields_editor(f"{key_prefix}_identity", current)

    result = {
        "scope": scope,
        "hypothesis": hypothesis.strip() or None,
        "motivation": motivation.strip() or None,
    }
    result.update(extra)
    return result


def _section_knowledge(current: Dict[str, Any], key_prefix: str) -> tuple[Dict[str, Any], List[str]]:
    """Gruppo 2 — Conoscenza estratta post-run."""
    st.markdown("#### 📊 Conoscenza estratta post-run")
    errors: List[str] = []

    conclusion = st.text_area(
        "Conclusion",
        value=current.get("conclusion") or "",
        height=100,
        key=f"{key_prefix}_conclusion",
        help="Cosa hai imparato, indipendentemente dal successo.",
    )
    conclusion_type = _selectbox_with_none(
        "Conclusion type",
        CONCLUSION_TYPE_OPTIONS,
        current.get("conclusion_type"),
        f"{key_prefix}_conclusion_type",
    )

    # Multi-lessons learned (array di stringhe)
    lessons_learned = _render_multi_item_editor(
        "Lessons Learned",
        current.get("lessons_learned"),
        f"{key_prefix}_lessons",
        placeholder="What did you learn from this run?",
    )

    # Evidences (JSON array di oggetti)
    evidences, ev_err = _render_json_array_editor(
        "Evidences",
        current.get("evidences"),
        f"{key_prefix}_evidences",
    )
    if ev_err:
        errors.append(ev_err)

    # Open questions (array di stringhe)
    open_questions = _render_multi_item_editor(
        "Open Questions",
        current.get("open_questions"),
        f"{key_prefix}_openq",
        placeholder="What questions remain open?",
    )

    # Dynamic extra fields for this section
    extra = _render_dynamic_fields_editor(f"{key_prefix}_knowledge", current)

    result = {
        "conclusion": conclusion.strip() or None,
        "conclusion_type": conclusion_type,
        "lessons_learned": lessons_learned if lessons_learned else None,
        "evidences": evidences,
        "open_questions": open_questions if open_questions else None,
    }
    result.update(extra)
    return result, errors


def _section_navigation(current: Dict[str, Any], key_prefix: str) -> Dict[str, Any]:
    """Gruppo 3 — Navigabilità del grafo."""
    st.markdown("#### 🗺️ Navigabilità del grafo")

    col1, col2 = st.columns(2)
    with col1:
        is_base = st.checkbox(
            "Is base experiment",
            value=bool(current.get("is_base", False)),
            key=f"{key_prefix}_is_base",
            help="Marca come baseline di riferimento.",
        )
        dead_end = st.checkbox(
            "Dead end",
            value=bool(current.get("dead_end", False)),
            key=f"{key_prefix}_dead_end",
            help="Direzione sterile: non esplorare ulteriormente.",
        )
    with col2:
        exploration_priority = _float_or_none(
            "Exploration priority",
            current.get("exploration_priority"),
            f"{key_prefix}_exploration_priority",
        )

    # Tags come array dinamico
    tags = _render_multi_item_editor(
        "Tags",
        current.get("tags"),
        f"{key_prefix}_tags",
        placeholder="e.g. low-lr, no-warmup",
    )

    # Dynamic extra fields for this section
    extra = _render_dynamic_fields_editor(f"{key_prefix}_navigation", current)

    result = {
        "is_base": is_base,
        "dead_end": dead_end,
        "exploration_priority": exploration_priority,
        "tags": tags if tags else None,
    }
    result.update(extra)
    return result


def _section_reliability(current: Dict[str, Any], key_prefix: str) -> Dict[str, Any]:
    """Gruppo 4 — Riproducibilità e affidabilità."""
    st.markdown("#### 🎯 Affidabilità")

    confidence = _float_or_none(
        "Confidence",
        current.get("confidence"),
        f"{key_prefix}_confidence",
    )
    retry_policy = _selectbox_with_none(
        "Retry policy",
        RETRY_POLICY_OPTIONS,
        current.get("retry_policy"),
        f"{key_prefix}_retry_policy",
    )
    validation_scope = _selectbox_with_none(
        "Validation scope",
        VALIDATION_SCOPE_OPTIONS,
        current.get("validation_scope"),
        f"{key_prefix}_validation_scope",
    )

    # Dynamic extra fields for this section
    extra = _render_dynamic_fields_editor(f"{key_prefix}_reliability", current)

    result = {
        "confidence": confidence,
        "retry_policy": retry_policy,
        "validation_scope": validation_scope,
    }
    result.update(extra)
    return result


def _section_costs(current: Dict[str, Any], key_prefix: str) -> Dict[str, Any]:
    """Gruppo 5 — Metadati computazionali."""
    st.markdown("#### 💰 Costi computazionali")

    col1, col2, col3 = st.columns(3)
    with col1:
        compute_enabled = st.checkbox(
            "Set compute cost",
            value=current.get("compute_cost") is not None,
            key=f"{key_prefix}_compute_enabled",
        )
        compute_cost = (
            st.number_input(
                "Compute cost (GPU-h)",
                min_value=0.0,
                value=float(current.get("compute_cost") or 0.0),
                step=0.5,
                key=f"{key_prefix}_compute_cost",
            )
            if compute_enabled else None
        )
    with col2:
        duration_enabled = st.checkbox(
            "Set duration",
            value=current.get("duration_seconds") is not None,
            key=f"{key_prefix}_duration_enabled",
        )
        duration_seconds = (
            st.number_input(
                "Duration (seconds)",
                min_value=0,
                value=int(current.get("duration_seconds") or 0),
                step=60,
                key=f"{key_prefix}_duration_seconds",
            )
            if duration_enabled else None
        )
    with col3:
        gain_enabled = st.checkbox(
            "Set estimated gain",
            value=current.get("estimated_gain") is not None,
            key=f"{key_prefix}_gain_enabled",
        )
        estimated_gain = (
            st.number_input(
                "Estimated gain (Δ metric)",
                value=float(current.get("estimated_gain") or 0.0),
                step=0.01,
                format="%.4f",
                key=f"{key_prefix}_estimated_gain",
            )
            if gain_enabled else None
        )

    # Dynamic extra fields for this section
    extra = _render_dynamic_fields_editor(f"{key_prefix}_costs", current)

    result = {
        "compute_cost": compute_cost,
        "duration_seconds": int(duration_seconds) if duration_seconds is not None else None,
        "estimated_gain": estimated_gain,
    }
    result.update(extra)
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# TABS
# ═══════════════════════════════════════════════════════════════════════════════

def _render_tab_agentic(experiments_objs: List[Experiment]) -> None:
    """Render agentic metadata tab with nested dict structure."""
    st.subheader("Agentic Metadata")
    st.caption(
        "Compilare questi campi prima e dopo ogni run. "
        "I dati vengono salvati come dizionario nidificato in agentic_metadata."
    )

    if not experiments_objs:
        st.info("Nessun esperimento disponibile.")
        return

    experiments = [_experiment_to_dict(e) for e in experiments_objs]
    # Show name in selectbox, but keep id for lookup
    exp_options = {e.get("name") or e.get("id", "N/A"): e.get("id") for e in experiments}
    selected_name = st.selectbox(
        "Seleziona esperimento",
        list(exp_options.keys()),
        key="ag_exp_select",
    )
    selected_exp_id = exp_options.get(selected_name)
    if not selected_exp_id:
        return

    # Load current agentic metadata
    try:
        current = run_async(_get_agentic(selected_exp_id)) or {}
    except UIError as exc:
        st.error(f"Errore nel caricamento: {exc.user_message}")
        return

    st.divider()

    # ── Sections (all containers, no forms!) ──
    with st.expander("🔬 Identità e contesto (pre-run)", expanded=True):
        identity_vals = _section_identity(current.get("identity", {}), key_prefix="ag_id")

    with st.expander("📊 Conoscenza estratta (post-run)", expanded=True):
        knowledge_vals, knowledge_errors = _section_knowledge(
            current.get("knowledge", {}), key_prefix="ag_kn"
        )

    with st.expander("🗺️ Navigabilità del grafo", expanded=False):
        nav_vals = _section_navigation(current.get("navigation", {}), key_prefix="ag_nv")

    with st.expander("🎯 Affidabilità e riproducibilità", expanded=False):
        reliability_vals = _section_reliability(
            current.get("reliability", {}), key_prefix="ag_rl"
        )

    with st.expander("💰 Costi computazionali", expanded=False):
        cost_vals = _section_costs(current.get("costs", {}), key_prefix="ag_cs")

    # Show validation errors
    for err in knowledge_errors:
        st.error(err)

    st.divider()
    col_save, col_reset = st.columns([2, 1])

    with col_save:
        disabled = bool(knowledge_errors)
        if st.button("💾 Salva metadati agentici", type="primary", disabled=disabled):
            # Build nested agentic_metadata dict
            agentic_metadata = {
                "identity": {k: v for k, v in identity_vals.items() if v is not None},
                "knowledge": {k: v for k, v in knowledge_vals.items() if v is not None},
                "navigation": {k: v for k, v in nav_vals.items() if v is not None},
                "reliability": {k: v for k, v in reliability_vals.items() if v is not None},
                "costs": {k: v for k, v in cost_vals.items() if v is not None},
            }
            # Also flatten top-level for backward compatibility
            # (merge all sections into top-level, section keys as prefixes if collision)
            flat_metadata: Dict[str, Any] = {}
            for section, values in agentic_metadata.items():
                for k, v in values.items():
                    flat_metadata[k] = v

            try:
                # Save as nested dict (primary) + flat fields (backward compat)
                payload = {**flat_metadata, "agentic_metadata": agentic_metadata}
                run_async(_update_agentic(selected_exp_id, payload))
                st.success(f"✅ Metadati salvati per `{selected_name}`")
                _clear_session_prefix("ag_")
                _clear_session_prefix("dyn_ag_")
                st.rerun()
            except UIError as exc:
                st.error(f"Errore: {exc.user_message}")

    with col_reset:
        if st.button("🔄 Ricarica dal DB", key="ag_reload"):
            _clear_session_prefix("ag_")
            _clear_session_prefix("dyn_ag_")
            st.rerun()

    # Preview of current nested structure
    with st.expander("👁 Preview agentic_metadata (corrente in DB)", expanded=False):
        st.json(current)


def _render_tab_edit(experiments_objs: List[Experiment]) -> None:
    """Render edit metadata tab — NO agentic_metadata editing here."""
    st.subheader("Edit Metadata")

    if not experiments_objs:
        st.info("No experiments available to edit.")
        return

    experiments = [_experiment_to_dict(e) for e in experiments_objs]
    exp_options = {e.get("name") or e.get("id", "N/A"): e.get("id") for e in experiments}
    selected_name = st.selectbox(
        "Select Experiment",
        list(exp_options.keys()),
        key="edit_exp",
    )
    selected_exp_id = exp_options.get(selected_name)

    if not selected_exp_id:
        return

    current = next((e for e in experiments if e.get("id") == selected_exp_id), {})
    if not current:
        st.error("Experiment not found")
        return

    # Basic metadata only — NO agentic fields
    st.markdown("#### Basic Metadata")
    description = st.text_area(
        "Description",
        value=current.get("description", "") or "",
        key="edit_description",
    )
    notes = st.text_area(
        "Notes",
        value=current.get("notes", "") or "",
        key="edit_notes",
    )

    # Dynamic extra fields (non-agentic)
    st.markdown("---")
    st.markdown("**Custom fields**")
    st.caption("Campi extra arbitrari (non agentic) da salvare sul nodo.")

    dyn_session_key = "edit_dynamic_fields"
    if dyn_session_key not in st.session_state:
        known = _KNOWN_CORE_FIELDS
        dynamic = {
            k: v for k, v in current.items()
            if k not in known and v is not None
        }
        st.session_state[dyn_session_key] = dynamic

    dynamic_fields: Dict[str, Any] = st.session_state[dyn_session_key]
    to_remove: List[str] = []

    for field_name, field_value in list(dynamic_fields.items()):
        col1, col2, col3 = st.columns([3, 6, 1])
        with col1:
            st.text(field_name)
        with col2:
            if isinstance(field_value, bool):
                dynamic_fields[field_name] = st.checkbox(
                    "Value", value=field_value,
                    key=f"edit_dyn_{field_name}_val",
                    label_visibility="collapsed",
                )
            elif isinstance(field_value, (int, float)):
                dynamic_fields[field_name] = st.number_input(
                    "Value", value=float(field_value),
                    key=f"edit_dyn_{field_name}_val",
                    label_visibility="collapsed",
                )
            else:
                dynamic_fields[field_name] = st.text_input(
                    "Value",
                    value=str(field_value) if field_value is not None else "",
                    key=f"edit_dyn_{field_name}_val",
                    label_visibility="collapsed",
                )
        with col3:
            if st.button("🗑️", key=f"edit_dyn_del_{field_name}"):
                to_remove.append(field_name)

    for k in to_remove:
        dynamic_fields.pop(k, None)
        st.rerun()

    # Add new custom field
    col_name, col_type, col_add = st.columns([3, 2, 1])
    with col_name:
        new_name = st.text_input(
            "Name", key="edit_new_name",
            label_visibility="collapsed", placeholder="field_name",
        )
    with col_type:
        new_type = st.selectbox(
            "Type", ["text", "number", "boolean"],
            key="edit_new_type",
            label_visibility="collapsed",
        )
    with col_add:
        if st.button("➕ Add", key="edit_add_btn") and new_name:
            if new_name in _KNOWN_CORE_FIELDS:
                st.error(f"'{new_name}' is reserved.")
            elif new_name in dynamic_fields:
                st.error(f"'{new_name}' already exists.")
            else:
                defaults = {"text": "", "number": 0.0, "boolean": False}
                dynamic_fields[new_name] = defaults[new_type]
                st.rerun()

    st.divider()
    col_save, col_reset = st.columns([2, 1])

    with col_save:
        if st.button("💾 Save Metadata", type="primary", key="edit_save"):
            try:
                payload = {
                    "description": description.strip() or None,
                    "notes": notes.strip() or None,
                    **{k: v for k, v in dynamic_fields.items() if v is not None},
                }
                payload = {k: v for k, v in payload.items() if v is not None}
                run_async(_update_metadata(selected_exp_id,notes=notes, **payload))
                st.success("Metadata updated successfully!")
                logger.info(f"Updated experiment {selected_exp_id}")
                if dyn_session_key in st.session_state:
                    del st.session_state[dyn_session_key]
                st.rerun()
            except UIError as e:
                st.error(f"Error: {e.user_message}")

    with col_reset:
        if st.button("🔄 Reset", key="edit_reset"):
            if dyn_session_key in st.session_state:
                del st.session_state[dyn_session_key]
            st.rerun()


def _render_tab_browse() -> None:
    """Render browse experiments tab with name display and lineage resolution."""
    st.subheader("Browse Experiments")

    col_filter, col_search = st.columns([1, 2])
    with col_filter:
        status_filter = st.selectbox(
            "Status", ["All", "COMPLETED", "RUNNING", "FAILED"], key="browse_status"
        )
    with col_search:
        search = st.text_input(
            "Search", placeholder="Filter by name or description", key="browse_search"
        )

    try:
        filter_val = None if status_filter == "All" else status_filter
        search_val = search.strip() if search and search.strip() else None
        experiments_objs = run_async(
            _list_with_lineage(status_filter=filter_val, search=search_val)
        )
        experiments = [_experiment_to_dict(e) for e in experiments_objs]

        if experiments:
            for exp in experiments:
                badge = _status_badge(exp.get("status"), exp.get("usable"))
                display_name = exp.get("name") or exp.get("id", "N/A")
                with st.expander(f"{display_name} {badge}"):
                    # Lineage info (resolved via graph traversal)
                    col1, col2 = st.columns(2)
                    with col1:
                        model_name = exp.get("model_name")
                        if model_name:
                            st.markdown(f"**Model:** {model_name}")
                        else:
                            st.markdown("**Model:** *not resolved*")
                        
                        recipe_name = exp.get("recipe_name")
                        if recipe_name:
                            st.markdown(f"**Recipe:** {recipe_name}")
                        else:
                            st.markdown("**Recipe:** *not resolved*")
                        
                        comp_tech = exp.get("component_technique")
                        if comp_tech:
                            comp_fw = exp.get("component_framework", "N/A")
                            st.markdown(f"**Technique:** {comp_tech} ({comp_fw})")
                    
                    with col2:
                        st.markdown(f"**Checkpoints:** {exp.get('ckp_count', 0)}")
                        st.caption(f"ID: `{exp.get('id', 'N/A')}`")
                        st.caption(f"Config hash: {exp.get('config_hash', 'N/A')}")
                        st.caption(f"Created: {exp.get('created_at', 'N/A')}")

                    if exp.get("description"):
                        st.markdown(f"**Description:** {exp.get('description')}")
                    if exp.get("notes"):
                        st.markdown(f"**Notes:** {exp.get('notes')}")

                    # Agentic pills (read-only)
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

                    # Show custom fields (non-agentic)
                    known = _KNOWN_CORE_FIELDS
                    extra = {
                        k: v for k, v in exp.items()
                        if k not in known and v is not None
                    }
                    if extra:
                        with st.popover("🔍 Custom fields"):
                            st.json(extra)
        else:
            st.info("🔬 No experiments found")
            st.caption(
                "Experiments are created automatically when you run a "
                "training function with @lineage_tracker()."
            )
    except UIError as e:
        st.error(f"Error: {e.user_message}")


# ═══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════

def run() -> None:
    """Run experiment management page."""
    st.title("Experiment Management")

    tab_browse, tab_edit, tab_agentic = st.tabs(
        ["Browse", "Edit Metadata", "Agentic Metadata"]
    )

    with tab_browse:
        _render_tab_browse()

    with tab_edit:
        try:
            experiments_objs = run_async(_list_with_lineage())
            _render_tab_edit(experiments_objs)
        except UIError as e:
            st.error(f"Error: {e.user_message}")

    with tab_agentic:
        try:
            experiments_objs = run_async(_list_with_lineage())
            _render_tab_agentic(experiments_objs)
        except UIError as e:
            st.error(f"Error: {e.user_message}")