"""Setups page — Project scaffold initializer.

Generates downloadable project scaffolds with:
- Template training code per component (framework+technique)
- Pre-filled config.yml with selected recipe, model, output, hardware
- Virgin .lineage/experiment.yml for lineage tracking
"""

from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st
import yaml

from graph_lineage.streamlit_ui.db.repository.component_repository import ComponentRepository
from graph_lineage.streamlit_ui.db.repository.model_repository import ModelRepository
from graph_lineage.streamlit_ui.db.repository.recipe_repository import RecipeRepository
from graph_lineage.streamlit_ui.utils import get_neo4j_client
from graph_lineage.streamlit_ui.utils.async_helpers import run_async

# Base path for setup templates
_SETUPS_DIR = Path(__file__).parent.parent.parent / "setups"
_BASE_DIR = _SETUPS_DIR / "_base"


def _safe_read_file(file_path: Path) -> str:
    """Read file with robust encoding handling.
    
    Tries UTF-8 with error replacement, falls back to latin-1 if needed.
    """
    try:
        return file_path.read_text(encoding='utf-8', errors='replace')
    except Exception:
        try:
            return file_path.read_text(encoding='latin-1', errors='replace')
        except Exception:
            return "[Unable to read file]"


# ---------------------------------------------------------------------------
# Async helpers
# ---------------------------------------------------------------------------

async def _list_components_async() -> list[dict]:
    db = get_neo4j_client()
    repo = ComponentRepository(db)
    return await repo.list_all()


async def _list_models_async() -> list[dict]:
    db = get_neo4j_client()
    repo = ModelRepository(db)
    return await repo.list_all()


async def _list_recipes_async() -> list[dict]:
    db = get_neo4j_client()
    repo = RecipeRepository(db)
    return await repo.list_all()


# ---------------------------------------------------------------------------
# Scaffold generation
# ---------------------------------------------------------------------------

def _generate_config_yml(selections: dict) -> str:
    """Generate config.yml content from form selections."""
    setup_name = selections["setup_name"]
    
    # Use custom cache_dir if provided, otherwise use standard template
    cache_dir = selections.get("cache_dir", "").strip()
    if not cache_dir:
        cache_dir = f"/nfs/training-output/.dpo-cache/${{experiment.name}}/${{experiment.id}}/data"

    config = {
        "model": {
            "model_uri": selections["model_uri"],
            "model_id": selections["model_id"],
            "dataset": {
                "cache_dir": cache_dir,
                "cache_file": "train_dataset",
            },
            "training": {
                "learning_rate": selections.get("learning_rate", 1e-5),
                "lr_scheduler_type": "linear",
                "optim": "paged_adamw_8bit",
                "per_device_train_batch_size": selections.get("batch_size", 1),
                "gradient_accumulation_steps": 16,
                "num_train_epochs": selections.get("epochs", 3),
                "gradient_checkpointing": True,
                "bf16": True,
                "logging_steps": 10,
                "save_steps": 1500,
            },
            "peft": {
                "r": 16,
                "lora_alpha": 32,
                "lora_dropout": 0.05,
                "bias": "none",
                "task_type": "CAUSAL_LM",
                "target_modules": ["q_proj", "v_proj", "k_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
            },
        },
        "recipe": {},
        "output": {
            "output_dir": selections["output_dir"],
        },
        "hardware": selections.get("hardware") or {},
        "model_merging": {
            "enabled": selections.get("merging_enabled", False),
        },
    }

    # Add optional fields
    if selections.get("metrics_uri"):
        config["output"]["metrics_uri"] = selections["metrics_uri"]
    if selections.get("recipe_id"):
        config["recipe"]["recipe_id"] = selections["recipe_id"]
    if selections.get("recipe_name"):
        config["recipe"]["recipe_name"] = selections["recipe_name"]
    if selections.get("merging_enabled"):
        config["model_merging"]["merge_method"] = selections.get("merge_method", "linear")
        config["model_merging"]["sources"] = selections.get("merge_sources", [])

    return yaml.dump(config, default_flow_style=False, sort_keys=False, allow_unicode=True)


def _generate_experiment_yml(setup_name: str, selections: dict) -> str:
    """Generate .lineage/experiment.yml from template.
    
    URI is intentionally null — the tracker sets it to the actual project_root
    on the remote machine at first execution.
    """
    template = _safe_read_file(_BASE_DIR / ".lineage" / "experiment.yml")
    content = template.replace("{{SETUP_NAME}}", setup_name)
    content = content.replace("{{PROJECT_URI}}", "")
    content = content.replace("{{DESCRIPTION}}", selections.get("description", ""))
    content = content.replace("{{COMPONENT_NAME}}", selections.get("component_name", ""))
    return content


def _build_zip(component_uri: str | None, selections: dict) -> bytes:
    """Build zip archive from template (via component_uri) + generated configs.
    
    Args:
        component_uri: URI to the component template directory (from DB).
        selections: Form selections dict.
    
    Returns:
        Zip file bytes.
    """
    buffer = io.BytesIO()

    setup_name = selections["setup_name"]

    # Resolve component URI to Path
    template_dir = None
    if component_uri:
        template_dir = Path(component_uri)
        if not template_dir.exists() or not template_dir.is_dir():
            template_dir = None

    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        # 1. Copy template files recursively (train.py, requirements.txt, modules/, etc.)
        if template_dir:
            for item in template_dir.rglob("*"):
                if item.is_file():
                    rel_path = item.relative_to(template_dir)
                    content = _safe_read_file(item)
                    zf.writestr(f"{setup_name}/{rel_path}", content)

        # 2. Copy base files (Makefile)
        makefile = _BASE_DIR / "Makefile"
        if makefile.exists():
            content = _safe_read_file(makefile)
            zf.writestr(f"{setup_name}/Makefile", content)

        # 3. Generate config.yml on-the-fly
        config_content = _generate_config_yml(selections)
        zf.writestr(f"{setup_name}/config.yml", config_content)

        # 4. Generate .lineage/experiment.yml (uri=null, set by tracker at runtime)
        experiment_content = _generate_experiment_yml(setup_name, selections)
        zf.writestr(f"{setup_name}/.lineage/experiment.yml", experiment_content)

        # 5. Save setup.json metadata
        metadata = {
            "name": setup_name,
            "component_name": selections.get("component_name", ""),
            "recipe_id": selections.get("recipe_id"),
            "model_uri": selections["model_uri"],
            "model_id": selections["model_id"],
            "output_dir": selections["output_dir"],
            "metrics_uri": selections.get("metrics_uri"),
            "hardware": selections.get("hardware"),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        zf.writestr(f"{setup_name}/setup.json", json.dumps(metadata, indent=2))

    buffer.seek(0)
    return buffer.read()


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

def run() -> None:
    """Render the Setups initializer page."""
    st.title("Setup Initializer")
    st.caption("Generate project scaffolds with pre-configured training templates and lineage tracking.")

    tab_create, tab_browse = st.tabs(["Create Setup", "Browse Templates"])

    with tab_create:
        _render_create_form()

    with tab_browse:
        _render_browse_templates()


def _render_create_form() -> None:
    """Render the setup creation form."""
    st.subheader("Configure your training setup")

    # Load entities from DB
    try:
        components = run_async(_list_components_async())
        models = run_async(_list_models_async())
        recipes = run_async(_list_recipes_async())
    except Exception as e:
        st.error(f"Failed to load data from Neo4j: {e}")
        components, models, recipes = [], [], []

    col1, col2 = st.columns(2)

    with col1:
        # Setup name
        setup_name = st.text_input(
            "Setup Name *",
            placeholder="DPO-velvet2B",
            help="Becomes the root folder name in the zip download (overrides component template name)",
        )

        # Component selection — options come from component.name (DB only)
        component_options = [c.get("name", "") for c in components if c.get("name")]
        component_map = {c.get("name", ""): c for c in components}  # Map name -> component object

        selected_component = st.selectbox(
            "Component Name *",
            options=component_options if component_options else [],
            help="Component template from the database",
        )

        # Model
        model_options = [m.get("model_name", "unknown") for m in models]
        model_input_mode = st.radio("Model source", ["Select from DB", "Enter manually"], horizontal=True)

        if model_input_mode == "Select from DB" and model_options:
            selected_model = st.selectbox("Model *", options=model_options)
            model_uri = next((m.get("url", "") for m in models if m.get("model_name") == selected_model), "")
            model_id = selected_model
        else:
            model_uri = st.text_input("Model URI *", placeholder="/nfs/models/velvet-2b/checkpoint")
            model_id = st.text_input("Model ID *", placeholder="velvet-2b_ba53454_t0")

    with col2:
        # Recipe
        recipe_options = {r.get("name"): r for r in recipes}
        selected_recipe_name = st.selectbox(
            "Recipe (optional)",
            options=["None"] + list(recipe_options.keys()),
        )
        recipe_id = None
        recipe_name = None
        if selected_recipe_name != "None":
            recipe_id = recipe_options[selected_recipe_name].get("id")
            recipe_name = selected_recipe_name

        # Description (goes into .lineage/experiment.yml)
        setup_description = st.text_area(
            "Description (optional)",
            placeholder="DPO fine-tune of velvet-2b on curated preference data",
            help="Pre-fills experiment.yml description for lineage tracking",
        )

        # Output
        output_dir = st.text_input(
            "Output Directory *",
            value="/nfs/training-output/.dpo-cache/${experiment.name}/${experiment.id}/checkpoints",
            help="Checkpoints output directory. Supports template variables: ${experiment.name}, ${experiment.id}",
        )
        metrics_uri = st.text_input(
            "Metrics URI (optional)",
            value="/nfs/training-output/.dpo-cache/${experiment.name}/${experiment.id}/metrics",
            help="Metrics output directory. Supports template variables: ${experiment.name}, ${experiment.id}",
        )
        cache_dir = st.text_input(
            "Dataset Cache Directory (optional)",
            value="/nfs/training-output/.dpo-cache/${experiment.name}/${experiment.id}/data",
            help="Dataset cache directory. Supports template variables: ${experiment.name}, ${experiment.id}",
        )

        # Hyperparameters
        st.markdown("**Hyperparameters**")
        learning_rate = st.number_input("Learning Rate", value=2e-4, format="%.2e", step=1e-5)
        batch_size = st.number_input("Batch Size", value=4, min_value=1, step=1)
        epochs = st.number_input("Epochs", value=3, min_value=1, step=1)

    # Hardware (optional)
    with st.expander("Hardware Configuration (optional)"):
        hw_col1, hw_col2 = st.columns(2)
        with hw_col1:
            gpu_type = st.text_input("GPU Type", placeholder="A100-80GB")
            gpu_count = st.number_input("GPU Count", value=1, min_value=1, step=1)
        with hw_col2:
            cpus = st.text_input("CPUs", placeholder="128+")
            memory = st.text_input("Memory", placeholder="216+")

    # Model Merging (optional)
    with st.expander("Model Merging (optional)"):
        merging_enabled = st.checkbox("Enable Model Merging")
        merge_method = st.selectbox("Merge Method", ["linear", "slerp", "ties", "dare", "task_arithmetic"])
        merge_sources = st.text_area("Sources (one per line)", placeholder="checkpoint-1\ncheckpoint-2")

    # Generate button
    st.divider()
    if st.button("Generate & Download", type="primary", disabled=not (setup_name and model_uri and model_id and output_dir)):
        hardware = None
        if gpu_type:
            hardware = {
                "skypilot": {
                    "resources": {
                        "accelerators": f"{gpu_type}:{int(gpu_count)}",
                        "cpus": cpus or None,
                        "memory": memory or None,
                    },
                },
                "gpu": {"type": gpu_type, "count": int(gpu_count)},
            }

        # Get component URI from DB
        selected_component_obj = component_map.get(selected_component)
        component_uri = selected_component_obj.get("uri", "") if selected_component_obj else None

        selections = {
            "setup_name": setup_name,
            "component_name": selected_component,
            "description": setup_description,
            "model_uri": model_uri,
            "model_id": model_id,
            "recipe_id": recipe_id,
            "recipe_name": recipe_name,
            "output_dir": output_dir,
            "metrics_uri": metrics_uri,
            "cache_dir": cache_dir,
            "learning_rate": learning_rate,
            "batch_size": int(batch_size),
            "epochs": int(epochs),
            "hardware": hardware,
            "merging_enabled": merging_enabled,
            "merge_method": merge_method if merging_enabled else None,
            "merge_sources": [s.strip() for s in merge_sources.split("\n") if s.strip()] if merging_enabled else [],
        }

        if component_uri is None:
            st.warning(f"No URI found for component '{selected_component}'. Generating config-only scaffold.")

        zip_bytes = _build_zip(component_uri, selections)

        st.success(f"Scaffold generated: `{setup_name}/` (from template: `{selected_component}`)")
        st.download_button(
            label=f"Download {setup_name}.zip",
            data=zip_bytes,
            file_name=f"{setup_name}.zip",
            mime="application/zip",
        )
    elif not setup_name:
        st.info("Fill in Setup Name, Model, and Output Directory to generate.")


def _render_browse_templates() -> None:
    """Show available templates and their contents."""
    st.subheader("Available Templates")

    templates = [d for d in _SETUPS_DIR.iterdir() if d.is_dir() and not d.name.startswith("_")]

    if not templates:
        st.info("No templates found in `graph_lineage/setups/`.")
        return

    for template_dir in sorted(templates):
        with st.expander(f"{template_dir.name}"):
            for f in sorted(template_dir.rglob("*")):
                if f.is_file():
                    rel_path = f.relative_to(template_dir)
                    st.markdown(f"**{rel_path}**")
                    if f.suffix == ".py":
                        st.code(_safe_read_file(f), language="python")
                    elif f.suffix == ".txt":
                        st.code(_safe_read_file(f), language="text")
                    else:
                        st.text(_safe_read_file(f))
