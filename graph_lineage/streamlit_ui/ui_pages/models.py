import streamlit as st
import asyncio
from typing import Dict, Any

from graph_lineage.data_classes.neo4j.nodes.model import Model, ModelType
from graph_lineage.streamlit_ui.utils import get_neo4j_client
from graph_lineage.streamlit_ui.db.repository.model_repository import ModelRepository
from graph_lineage.streamlit_ui.utils.async_helpers import run_async
from graph_lineage.streamlit_ui.utils.errors import UIError
import logging
logger = logging.getLogger(__name__)

# Mapping for display labels
labels_mapping = {
    ModelType.UNKNOWN: "🔍 Unknown",
    ModelType.FOUNDATIONAL: "🏗️ Foundational",
    ModelType.BASE: "🏠 Base",
    ModelType.INSTRUCT: "🎓 Instruct",
    ModelType.THINKING: "🧠 Thinking",
    ModelType.DOMAIN_SPECIFIC: "🎯 Domain Specific",
    ModelType.FINE_TUNED: "🔧 Fine-Tuned",
    ModelType.MERGED: "🔀 Merged",
    ModelType.DISTILLED: "🧪 Distilled",
    ModelType.QUANTIZED: "📉 Quantized",
    ModelType.MULTIMODAL: "👁️ Multimodal",
}

KIND_OPTIONS = [
    ModelType.UNKNOWN, ModelType.BASE, ModelType.INSTRUCT, ModelType.THINKING,
    ModelType.DOMAIN_SPECIFIC, ModelType.FINE_TUNED, ModelType.MERGED,
    ModelType.DISTILLED, ModelType.QUANTIZED, ModelType.MULTIMODAL
]

def build_model_from_form(
    model_name: str,
    version: str,
    uri: str,
    url: str,
    doc_url: str,
    description: str,
    kind: ModelType,
    architecture_info_ref: str,
    custom_fields: Dict[str, Any],
    existing_id: str = None
) -> Model:
    """Build a Model instance from form data, including custom fields."""
    model_data = {
        "model_name": model_name,
        "version": version,
        "uri": uri,
        "url": url,
        "doc_url": doc_url,
        "description": description,
        "kind": kind,
        "architecture_info_ref": architecture_info_ref,
    }

    # Merge custom fields - they will be absorbed as extra fields thanks to ConfigDict(extra='allow')
    if custom_fields:
        model_data.update(custom_fields)

    if existing_id:
        model_data["id"] = existing_id

    return Model(**model_data)

def display_model_card(model: Model):
    """Display a model card with all fields including custom ones."""
    with st.container(border=True):
        col1, col2 = st.columns([3, 1])
        with col1:
            st.write(f"**{model.model_name}**  --- **{labels_mapping.get(model.kind, model.kind)}**")
            if model.version:
                st.caption(f"Version: {model.version}")
            if model.uri:
                st.caption(f"URI: {model.uri}")
            if model.description:
                st.caption(f"📝 {model.description}")
        with col2:
            st.caption(f"Created: {model.created_at.strftime('%Y-%m-%d %H:%M') if hasattr(model.created_at, 'strftime') else model.created_at}")
            st.caption(f"Updated: {model.updated_at.strftime('%Y-%m-%d %H:%M') if hasattr(model.updated_at, 'strftime') else model.updated_at}")

        # Display custom fields if any
        custom = model.custom_fields
        if custom:
            with st.expander("🔧 Custom Metadata", expanded=False):
                for k, v in sorted(custom.items()):
                    st.caption(f"**{k}**: {v}")

async def create_model_async(model: Model) -> Model:
    """Create model asynchronously. Returns Model dataclass."""
    db_client = get_neo4j_client()
    repo = ModelRepository(db_client)
    return await repo.create_model(model)

async def list_models_async() -> list[Model]:
    """List models asynchronously. Returns list of Model dataclasses."""
    db_client = get_neo4j_client()
    repo = ModelRepository(db_client)
    return await repo.list_models()

async def get_model_async(model_id: str) -> Model | None:
    """Get model asynchronously. Returns Model dataclass or None."""
    db_client = get_neo4j_client()
    repo = ModelRepository(db_client)
    return await repo.get_model(model_id)

async def update_model_async(model: Model) -> Model:
    """Update model asynchronously. Returns updated Model dataclass."""
    db_client = get_neo4j_client()
    repo = ModelRepository(db_client)
    return await repo.update_model(model)

async def upsert_model_async(model: Model) -> Model:
    """Upsert model by name asynchronously. Returns created/updated Model dataclass."""
    db_client = get_neo4j_client()
    repo = ModelRepository(db_client)
    return await repo.upsert_by_name(model)

async def delete_model_async(model_id: str) -> None:
    """Delete model asynchronously."""
    db_client = get_neo4j_client()
    repo = ModelRepository(db_client)
    await repo.delete_model(model_id)

async def check_model_deps_async(model_id: str) -> int:
    """Check model dependencies asynchronously."""
    db_client = get_neo4j_client()
    repo = ModelRepository(db_client)
    return await repo.check_model_dependencies(model_id)

def run() -> None:
    """Run model management page."""
    # Initialize session state for custom fields
    if "create_custom_fields" not in st.session_state:
        st.session_state.create_custom_fields = {}
    if "edit_custom_fields" not in st.session_state:
        st.session_state.edit_custom_fields = {}
    
    st.title("🤖 Model Management")
    st.caption("Manage your ML models with extensible metadata")

    tab_create, tab_browse, tab_edit, tab_delete = st.tabs(["➕ Create", "📋 Browse", "✏️ Edit", "🗑️ Delete"])

    # ─────────────────────────────────────────────────────────────
    # TAB 1: CREATE
    # ─────────────────────────────────────────────────────────────
    with tab_create:
        st.subheader("Create New Model")

        model_name = st.text_input("Model Name *", placeholder="e.g. gpt2-large, llama-3-8b")

        col1, col2 = st.columns(2)
        with col1:
            version = st.text_input("Version", value="", placeholder="1.0.0")
        with col2:
            kind = st.selectbox(
                "Kind",
                options=KIND_OPTIONS,
                index=KIND_OPTIONS.index(ModelType.UNKNOWN),
                format_func=lambda x: labels_mapping[x],
                key="create_kind"
            )

        uri = st.text_input("URI", value="", placeholder="s3://bucket/model or local path")
        url = st.text_input("URL", value="", placeholder="https://huggingface.co/...")
        doc_url = st.text_input("Documentation URL", value="", placeholder="https://docs.example.com")
        description = st.text_area("Description", value="", placeholder="Brief description of the model...")
        architecture_info_ref = st.text_input("Architecture Info Reference", value="", placeholder="Link to architecture doc or paper")

        # Custom fields editor
        st.divider()
        st.markdown("**Custom Metadata / Hyperparameters**")
        st.caption("Add custom metadata fields (e.g., hyperparameters, tags, configs)")
        
        col_add, col_remove = st.columns([3, 1])
        with col_add:
            new_field_key = st.text_input(
                "Custom Field Key",
                key="create_custom_key_input",
                placeholder="e.g., learning_rate, batch_size"
            )
        with col_remove:
            st.write("")
            if st.button("➕ Add Field", key="create_add_custom_field"):
                if new_field_key and new_field_key.strip():
                    key = new_field_key.strip()
                    if key not in st.session_state.create_custom_fields:
                        st.session_state.create_custom_fields[key] = ""
                        st.rerun()
        
        # Display existing custom fields
        if st.session_state.create_custom_fields:
            st.markdown("#### Existing Custom Fields")
            for field_key in list(st.session_state.create_custom_fields.keys()):
                col_val, col_del = st.columns([4, 1])
                with col_val:
                    st.session_state.create_custom_fields[field_key] = st.text_input(
                        f"Value for '{field_key}'",
                        value=st.session_state.create_custom_fields[field_key],
                        key=f"create_custom_val_{field_key}"
                    )
                with col_del:
                    st.write("")
                    if st.button("🗑️ Remove", key=f"create_remove_custom_{field_key}"):
                        del st.session_state.create_custom_fields[field_key]
                        st.rerun()
        
        custom_fields = st.session_state.create_custom_fields.copy()

        st.divider()
        upsert_mode = st.checkbox("🔄 Upsert mode (update if exists by name)")
        if upsert_mode:
            st.info("Model will be created if new, or updated if a model with this name already exists.")

        submitted = st.button("💾 Save Model", type="primary", use_container_width=True)

        if submitted:
            if not model_name.strip():
                st.error("Model name is required")
            else:
                try:
                    model = build_model_from_form(
                        model_name=model_name,
                        version=version,
                        uri=uri,
                        url=url,
                        doc_url=doc_url,
                        description=description,
                        kind=kind,
                        architecture_info_ref=architecture_info_ref,
                        custom_fields=custom_fields
                    )

                    if upsert_mode:
                        result = run_async(upsert_model_async(model))
                        st.success(f"✅ Model '{result.model_name}' upserted successfully!")
                    else:
                        result = run_async(create_model_async(model))
                        st.success(f"✅ Model '{result.model_name}' created successfully!")

                    st.toast("Model saved!", icon="🎉")
                    # Clear custom fields state after successful creation
                    st.session_state.create_custom_fields = {}

                except UIError as e:
                    st.error(f"❌ Error: {e.user_message}")
                except asyncio.TimeoutError:
                    st.error("⏱️ Request timed out. Please try again.")
                    logger.exception("Timeout in create_model")
                except Exception as e:
                    st.error(f"💥 Unexpected error: {str(e)}")
                    logger.exception("Uncaught exception in create_model")

    with tab_browse:
        st.subheader("Browse Models")
        try:
            models = run_async(list_models_async())

            if models:
                st.metric("Total Models", len(models))
                for model in models:
                    display_model_card(model)
            else:
                st.info("📭 No models found. Create your first model above!")
        except UIError as e:
            st.error(f"❌ Error: {e.user_message}")
        except Exception as e:
            st.error(f"💥 Unexpected error: {str(e)}")

    with tab_edit:
        st.subheader("Update Model")
        try:
            models = run_async(list_models_async())
            model_names = {m.model_name: m for m in models}

            selected_name = st.selectbox("Select Model to Edit", ["" ] + list(model_names.keys()), index=0, key="edit_select_model")

            if selected_name:
                selected_model = model_names[selected_name]
                model_id = selected_model.id
                model = run_async(get_model_async(model_id))

                if model is None:
                    st.error(f"❌ Model not found: {selected_name} (id={model_id})")
                else:
                    st.markdown(f"**Editing:** `{model.model_name}`")

                    col1, col2 = st.columns(2)
                    with col1:
                        version = st.text_input("Version", value=model.version or "")
                    with col2:
                        kind_options = KIND_OPTIONS
                        current_kind = model.kind if model.kind else ModelType.UNKNOWN
                        default_index = kind_options.index(current_kind) if current_kind in kind_options else 0
                        kind = st.selectbox(
                            "Kind",
                            options=kind_options,
                            index=default_index,
                            format_func=lambda x: labels_mapping[x],
                            key="edit_kind"
                        )

                    uri = st.text_input("URI", value=model.uri or "")
                    url = st.text_input("URL", value=model.url or "")
                    doc_url = st.text_input("Doc URL", value=model.doc_url or "")
                    description = st.text_area("Description", value=model.description or "")
                    architecture_info_ref = st.text_input("Architecture Info Ref", value=model.architecture_info_ref or "")

                    # Custom fields editor
                    st.divider()
                    st.markdown("**Custom Metadata / Hyperparameters**")
                    st.caption("Edit custom metadata fields")
                    
                    # Initialize edit state with existing custom fields if first time
                    if f"edit_state_{model_id}" not in st.session_state:
                        st.session_state[f"edit_state_{model_id}"] = model.custom_fields.copy() if hasattr(model, 'custom_fields') else {}
                    
                    edit_custom_fields_state = st.session_state[f"edit_state_{model_id}"]
                    
                    col_add, col_remove = st.columns([3, 1])
                    with col_add:
                        new_edit_field_key = st.text_input(
                            "Custom Field Key",
                            key=f"edit_custom_key_{model_id}",
                            placeholder="e.g., learning_rate, batch_size"
                        )
                    with col_remove:
                        st.write("")
                        if st.button("➕ Add Field", key=f"edit_add_custom_{model_id}"):
                            if new_edit_field_key and new_edit_field_key.strip():
                                key = new_edit_field_key.strip()
                                if key not in edit_custom_fields_state:
                                    edit_custom_fields_state[key] = ""
                                    st.rerun()
                    
                    # Display existing custom fields
                    if edit_custom_fields_state:
                        st.markdown("#### Existing Custom Fields")
                        for field_key in list(edit_custom_fields_state.keys()):
                            col_val, col_del = st.columns([4, 1])
                            with col_val:
                                edit_custom_fields_state[field_key] = st.text_input(
                                    f"Value for '{field_key}'",
                                    value=edit_custom_fields_state[field_key],
                                    key=f"edit_custom_val_{model_id}_{field_key}"
                                )
                            with col_del:
                                st.write("")
                                if st.button("🗑️ Remove", key=f"edit_remove_custom_{model_id}_{field_key}"):
                                    del edit_custom_fields_state[field_key]
                                    st.rerun()
                    
                    custom_fields = edit_custom_fields_state.copy()

                    submitted = st.button("💾 Update Model", type="primary", use_container_width=True)

                    if submitted:
                        try:
                            updated_model = build_model_from_form(
                                model_name=model.model_name,  # Preserve original name
                                version=version,
                                uri=uri,
                                url=url,
                                doc_url=doc_url,
                                description=description,
                                kind=kind,
                                architecture_info_ref=architecture_info_ref,
                                custom_fields=custom_fields,
                                existing_id=model_id
                            )

                            result = run_async(update_model_async(updated_model))
                            st.success("✅ Model updated successfully!")
                            st.toast("Changes saved!", icon="🎉")
                            # Clear edit state
                            st.session_state[f"edit_state_{model_id}"] = {}
                            st.rerun()
                        except UIError as e:
                            st.error(f"❌ Error: {e.user_message}")
                        except Exception as e:
                            st.error(f"💥 Unexpected error: {str(e)}")
                            logger.exception("Error in update_model")
        except UIError as e:
            st.error(f"❌ Error: {e.user_message}")
        except Exception as e:
            st.error(f"💥 Unexpected error: {str(e)}")

    with tab_delete:
        st.subheader("Delete Model")
        try:
            models = run_async(list_models_async())
            model_names = {m.model_name: m for m in models}

            selected_name = st.selectbox("Select Model to Delete", [""] + list(model_names.keys()), key="delete", index=0)

            if selected_name:
                selected_model = model_names[selected_name]
                model_id = selected_model.id

                try:
                    db_client = get_neo4j_client()
                    repo = ModelRepository(db_client)
                    is_deletable = run_async(repo.is_deletable(model_id))

                    if not is_deletable:
                        st.warning(
                            "⚠️ This model cannot be deleted because:"
                            "• It has been selected for experiments, OR"
                            "• It has been used as base for model merging"
                            "Remove dependent experiments/models first."
                        )
                    else:
                        st.success("✅ No dependencies found. Safe to delete.")

                        # Show model details before deletion
                        with st.expander("Model Details", expanded=True):
                            display_model_card(selected_model)

                        confirm = st.checkbox(f"I confirm deletion of model **'{selected_name}'**", key="confirm_delete")
                        if confirm and st.button("🗑️ Delete Model", type="primary", use_container_width=True):
                            try:
                                run_async(delete_model_async(model_id))
                                st.success("✅ Model deleted successfully!")
                                st.toast("Model removed", icon="🗑️")
                                st.rerun()
                            except UIError as e:
                                st.error(f"❌ Error: {e.user_message}")
                except Exception as e:
                    st.error(f"❌ Error checking dependencies: {str(e)}")
                    logger.exception("Error in delete check")
        except UIError as e:
            st.error(f"❌ Error: {e.user_message}")
        except Exception as e:
            st.error(f"💥 Unexpected error: {str(e)}")
