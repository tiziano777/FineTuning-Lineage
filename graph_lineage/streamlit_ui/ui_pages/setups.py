"""Setups page — Project scaffold initializer.

Generates downloadable project scaffolds with:
- Template training code scope(training/inference/evaluation/merging)
- Choose your model, recipe, and component (framework + technique)
- Pre-filled config.yml with selected recipe, model, output, hardware
- Virgin .lineage/experiment.yml for lineage tracking
"""
from __future__ import annotations
import io
import json
import zipfile
from datetime import datetime, timezone
import uuid
from pathlib import Path
import streamlit as st
import yaml

from graph_lineage.data_classes.neo4j.nodes.code.enum.run_type import RunType
from graph_lineage.data_classes.neo4j.nodes.code.training.component import Component
from graph_lineage.data_classes.neo4j.nodes.code.training.model import Model
from graph_lineage.streamlit_ui.db.repository.component_repository import ComponentRepository
from graph_lineage.streamlit_ui.db.repository.model_repository import ModelRepository
from graph_lineage.streamlit_ui.db.repository.recipe_repository import RecipeRepository
from graph_lineage.streamlit_ui.db.repository.recipe_repository import Recipe
from typing import Optional


from graph_lineage.streamlit_ui.utils.async_helpers import run_async

import logging  
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_SETUPS_ROOT_DIR = Path(__file__).parent.parent.parent / "setups"

# File visibili nel tab "Browse Templates"
_BROWSE_ALLOWED_FILES = {"requirements.txt", "prepare.py", "train.py", "config.yml"}
 
def _get_setups_dir(experiment_type: RunType) -> Path:
    """Setups directory scoped al experiment type selezionato nel wizard."""
    return _SETUPS_ROOT_DIR / experiment_type.value
 
def _get_base_dir() -> Path:
    """Base directory (file comuni: Makefile, modules/, .lineage templates) — shared across all experiment types."""
    return _SETUPS_ROOT_DIR / "_base"
  
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
 
async def _fetch_recipe_for_scaffold(
    recipe_name: str,
    recipe_repo: "RecipeRepository",
) -> Optional[Recipe]:
    """Retrieve a Recipe by name from the DB and return it as a validated dataclass.

    Args:
        recipe_name: Nome della recipe selezionata dall'utente nella selectbox.
        recipe_repo: Istanza di RecipeRepository per l'accesso al DB.

    Returns:
        Recipe (pydantic model) se trovata, None altrimenti.

    Raises:
        UIError: Se la riga recuperata dal DB non supera la validazione del modello.
    """
    recipe = await recipe_repo.get_by_name(recipe_name)
    if recipe is None:
        return None
    return recipe

async def _list_components_async() -> list[Component]:
    """List all components asynchronously. Returns list of Component dataclasses."""
    db = st.session_state.db_client
    repo = ComponentRepository(db)
    return await repo.list_all()
 
async def _list_models_async() -> list[Model]:
    """List all models asynchronously. Returns list of Model dataclasses."""
    db = st.session_state.db_client
    repo = ModelRepository(db)
    return await repo.list_all()
 
async def _list_recipes_async() -> list[dict]:
    """List all recipes asynchronously."""
    db = st.session_state.db_client
    repo = RecipeRepository(db)
    return await repo.list_all()
 
# ---------------------------------------------------------------------------
# Scaffold generation
# ---------------------------------------------------------------------------

def _deep_merge_dicts(base: dict, override: dict) -> dict:
    """Deep merge override dict into base dict (override takes priority).
    
    Recursively merges dicts. For non-dict values, override wins.
    Preserves None values in override if explicitly present.
    """
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge_dicts(result[key], value)
        else:
            result[key] = value
    return result

def _parse_accelerators(gpu_type: str, gpu_count: int) -> str | dict | list:
    """
    Parse gpu_type input into a valid SkyPilot accelerators value.
    Supports:
      - "A100-80GB"           → "A100-80GB:1"  (single, count from gpu_count)
      - "A100-80GB:4"         → "A100-80GB:4"  (single with inline count, ignores gpu_count)
      - "{A100:1, V100:1}"    → {"A100": 1, "V100": 1}  (unordered set → dict)
      - "[L4:1, H100:1]"      → ["L4:1", "H100:1"]      (ordered list)
    """
    gpu_type = gpu_type.strip()
 
    # Case 1: unordered set  {A100:1, V100:1}
    if gpu_type.startswith("{") and gpu_type.endswith("}"):
        inner = gpu_type[1:-1]
        result = {}
        for item in inner.split(","):
            item = item.strip()
            if ":" in item:
                name, count = item.rsplit(":", 1)
                result[name.strip()] = int(count.strip())
            else:
                result[item] = 1
        return result
 
    # Case 2: ordered list  [L4:1, H100:1, A100:1]
    if gpu_type.startswith("[") and gpu_type.endswith("]"):
        inner = gpu_type[1:-1]
        return [item.strip() for item in inner.split(",") if item.strip()]
 
    # Case 3: single with inline count  A100-80GB:4
    if ":" in gpu_type:
        return gpu_type  # already in "NAME:COUNT" format
 
    # Case 4: plain name  A100-80GB  → append gpu_count
    return f"{gpu_type}:{int(gpu_count)}"
 
# ---------------------------------------------------------------------------
# SCAFFOLD GENERATION LOGIC (Business Logic — UI-independent)
# ---------------------------------------------------------------------------
# These functions implement the core scaffold generation pipeline.
# They can be reused by different UI frameworks (Streamlit, FastAPI, etc.)

# STEP 1: Config Generation (model + recipe merge)
def _generate_config_yml(selections: dict, recipe: Recipe, template_config: dict | None = None) -> str:
    """Generate config.yml with smart merging of template + user selections.
    
    Merge strategy (priority: highest → lowest):
        1. User-selected values (always override)
        2. Template config.yml (if exists)
        3. Generated defaults
    
    Args:
        selections: User form selections with model_uri, model_id, output_dir, etc.
        recipe: Recipe object from DB (None if not selected)
        template_config: Template config.yml dict (None if no template)
    
    Returns:
        config.yml as YAML string
    """
    setup_name = selections["setup_name"]
    cache_dir = selections.get("cache_dir", "").strip()
    if not cache_dir:
        cache_dir = f"/nfs/training-output/.dpo-cache/${{experiment.name}}/${{experiment.id}}/data"
 
    # STEP 1a: Build initial config with user selections (highest priority)
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
                "num_train_epochs": selections.get("epochs", 1),
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
    }
 
    # STEP 1b: Add optional output fields
    if selections.get("metrics_uri"):
        config["output"]["metrics_uri"] = selections["metrics_uri"]
    if selections.get("plot_dir"):
        config["output"]["plot_dir"] = selections["plot_dir"]
    
    # STEP 1c: Inject recipe if selected, else keep empty
    if recipe is not None:
        config["recipe"] = recipe.model_dump(mode="json", exclude_none=True)
    else:
        # Preserve fallback fields if recipe_id or recipe_name provided
        if selections.get("recipe_id"):
            config["recipe"]["recipe_id"] = selections["recipe_id"]
        if selections.get("recipe_name"):
            config["recipe"]["recipe_name"] = selections["recipe_name"]
    
    # STEP 1d: Add model merging if enabled
    if selections.get("merging_enabled"):
        config.setdefault("model_merging", {})
        config["model_merging"]["merge_method"] = selections.get("merge_method", "linear")
        config["model_merging"]["sources"] = selections.get("merge_sources", [])
    
    # STEP 1e: Deep merge with template (template provides non-critical fields)
    if template_config:
        # CRITICAL: Remove recipe skeleton from template BEFORE merge
        # Otherwise recursive merge will preserve skeleton even if config["recipe"] = {}
        if recipe is None and "recipe" in template_config:
            del template_config["recipe"]
        
        config = _deep_merge_dicts(template_config, config)
        
        # Re-enforce critical fields from user selection (must always win)
        config["model"]["model_uri"] = selections["model_uri"]
        config["model"]["model_id"] = selections["model_id"]
        config["output"]["output_dir"] = selections["output_dir"]
        if recipe is not None:
            config["recipe"] = recipe.model_dump(mode="json", exclude_none=True)
        else:
            config["recipe"] = {}
 
    return yaml.dump(config, default_flow_style=False, sort_keys=False, allow_unicode=True)

# STEP 2: Other manifest generation
def _generate_experiment_yml(experiment_type: RunType, setup_name: str, selections: dict) -> str:
    """Generate .lineage/experiment.yml from template with user values."""
    template = _safe_read_file(_get_base_dir() / ".lineage" / "experiment.yml")
    content = template.replace("{{SETUP_NAME}}", setup_name)
    content = content.replace("{{PROJECT_URI}}", "")
    content = content.replace("{{DESCRIPTION}}", selections.get("description", ""))
    content = content.replace("{{COMPONENT_NAME}}", selections.get("component_name", ""))
    content = content.replace("{{RECIPE_NAME}}", selections.get("recipe_name", "") or "")
    content = content.replace("{{MODEL_ID}}", selections.get("model_id", ""))
    content = content.replace("{{EXPERIMENT_TYPE}}", experiment_type.value)
    return content

def _generate_server_yml(experiment_type: RunType, selections: dict) -> str:
    """Generate .lineage/server.yml from template with user values."""
    template = _safe_read_file(_get_base_dir() / ".lineage" / "server.yml")
    template = template.replace("{{SERVER_URL}}", selections.get("server_url", "http://localhost:8502"))
    template = template.replace("{{PROTOCOL}}", selections.get("protocol", "http"))
    template = template.replace("{{TIMEOUT}}", str(selections.get("timeout", 30)))
    template = template.replace("{{RETRIES}}", str(selections.get("retry", 3)))
    template = template.replace("{{BLOCKING}}", str(selections.get("blocking", True)).lower())
    return template

# STEP 3: Zip packaging
def _build_zip(experiment_type: RunType, component_uri: str | None, selections: dict, recipe: Recipe) -> bytes:
    """Build zip archive: template + generated configs.
    
    Packaging logic (order matters):
        1. Exclude config.yml from template copy (will be generated)
        2. Copy base files (shared across all experiment types)
        3. Generate config.yml dynamically (with template merge if needed)
        4. Generate lineage manifests (.lineage/experiment.yml, .lineage/server.yml)
        5. Save setup.json metadata
    
    Args:
        experiment_type: TRAINING, EVALUATION, INFERENCE, or MERGING
        component_uri: Path to component template (or None)
        selections: User form selections dict
        recipe: Recipe object (or None)
    
    Returns:
        Zip file bytes
    """
    buffer = io.BytesIO()
    setup_name = selections["setup_name"]
    base_dir = _get_base_dir()
    
    # Resolve component URI to Path
    template_dir = None
    if component_uri:
        uri_path = Path(component_uri)
        if uri_path.is_absolute() and uri_path.exists():
            template_dir = uri_path
        else:
            # Try extracting component name and building from experiment_type setups
            component_name = uri_path.name
            template_dir = _get_setups_dir(experiment_type) / component_name
            if not template_dir.exists():
                template_dir = None
    
    logger.info(f"Building zip: setup='{setup_name}', template_dir={template_dir}, base_dir={base_dir}")
 
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        # STEP 3.1: Copy template files (excluding config.yml — we generate it dynamically)
        if template_dir:
            for item in template_dir.rglob("*"):
                if item.is_file() and item.name != "config.yml":
                    rel_path = item.relative_to(template_dir)
                    content = _safe_read_file(item)
                    zf.writestr(f"{setup_name}/{rel_path}", content)
 
        # STEP 3.2: Copy base files (Makefile, modules/, etc.) — shared across all experiment types
        if base_dir.exists():
            for item in base_dir.rglob("*"):
                if item.is_file() and ".lineage" not in item.parts:
                    rel_path = item.relative_to(base_dir)
                    content = _safe_read_file(item)
                    zf.writestr(f"{setup_name}/{rel_path}", content)
 
        # STEP 3.3: Generate config.yml dynamically (merge template if exists)
        template_config = None
        if template_dir:
            template_config_path = template_dir / "config.yml"
            if template_config_path.exists():
                try:
                    template_yaml = _safe_read_file(template_config_path)
                    template_config = yaml.safe_load(template_yaml) or {}
                except Exception as e:
                    logger.warning(f"Failed to parse template config.yml: {e}")
                    template_config = None
        
        config_content = _generate_config_yml(selections, recipe, template_config=template_config)
        zf.writestr(f"{setup_name}/config.yml", config_content)
 
        # STEP 3.4: Generate lineage manifests
        experiment_content = _generate_experiment_yml(experiment_type, setup_name, selections)
        zf.writestr(f"{setup_name}/.lineage/experiment.yml", experiment_content)
        
        server_config_content = _generate_server_yml(experiment_type, selections)
        zf.writestr(f"{setup_name}/.lineage/server.yml", server_config_content)
 
        # STEP 3.5: Save setup.json metadata
        metadata = {
            "name": setup_name,
            "experiment_type": experiment_type.value,
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
# UI — Wizard entrypoint
# ---------------------------------------------------------------------------
 
def run() -> None:
    """Render the Setups initializer page (wizard)."""
    st.title("Setup Initializer")
    st.caption("Generate project scaffolds with pre-configured training templates and lineage tracking.")
 
    if "wizard_experiment_type" not in st.session_state:
        st.session_state.wizard_experiment_type = None
 
    if st.session_state.wizard_experiment_type is None:
        _render_experiment_type_step()
        return
 
    experiment_type: RunType = st.session_state.wizard_experiment_type
 
    header_col, reset_col = st.columns([5, 1])
    with header_col:
        st.info(f"Experiment Type selezionato: **{experiment_type.value}**")
    with reset_col:
        if st.button("Cambia tipo"):
            st.session_state.wizard_experiment_type = None
            st.rerun()
 
    tab_create, tab_browse = st.tabs(["Create Setup", "Browse Templates"])
 
    with tab_create:
        if experiment_type == RunType.TRAINING:
            _render_create_form_training()
        elif experiment_type == RunType.EVALUATION:
            _render_create_form_evaluation()
        elif experiment_type == RunType.INFERENCE:
            _render_create_form_inference()
        elif experiment_type == RunType.MERGING:
            _render_create_form_merging()
 
    with tab_browse:
        _render_browse_templates(experiment_type)
 
def _render_experiment_type_step() -> None:
    """Step 1 del wizard: sola selezione del experiment type."""
    st.subheader("Step 1 — Seleziona l'Experiment Type")
    st.caption("Il passo successivo mostrerà solo i campi rilevanti per il use case scelto.")
 
    options = list(RunType)
    selected = st.radio(
        "Experiment Type",
        options=options,
        format_func=lambda e: e.value.capitalize(),
        horizontal=True,
    )
 
    if st.button("Avanti →", type="primary"):
        st.session_state.wizard_experiment_type = selected
        st.rerun()
 
# ---------------------------------------------------------------------------
# UI — Create form (TRAINING)
# ---------------------------------------------------------------------------
 
def _render_create_form_training() -> None:
    """Render the setup creation form — TRAINING use case."""
    experiment_type = RunType.TRAINING
 
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
        setup_name = st.text_input(
            "Setup Name *",
            placeholder="DPO-velvet2B",
            help="Becomes the root folder name in the zip download (overrides component template name)",
        )
 
        component_options = [c.name for c in components if c.name]
        component_map = {c.name: c for c in components}
 
        selected_component = st.selectbox(
            "Component Name *",
            options=component_options if component_options else [],
            help="Component template from the database",
        )
 
        model_options = [m.model_name for m in models]
        model_input_mode = st.radio("Model source", ["Select from DB", "Enter manually"], horizontal=True)
 
        if model_input_mode == "Select from DB" and model_options:
            selected_model = st.selectbox("Model *", options=model_options)
            model_uri = next((m.uri or "" for m in models if m.model_name == selected_model), "")
            model_id = selected_model
        else:
            model_uri = st.text_input("Model URI *", placeholder="/nfs/models/velvet-2b/checkpoint")
            model_id = st.text_input("Model ID *", placeholder="velvet-2b_ba53454_t0")
 
    with col2:
        recipe_options = {r.name: r for r in recipes}
        selected_recipe_name = st.selectbox(
            "Recipe (optional)",
            options=["None"] + list(recipe_options.keys()),
        )
        
        # Initialize recipe variables to prevent NameError when building selections dict
        recipe: Optional[Recipe] = None
        recipe_id: str | None = None
        recipe_name: str | None = None
        recipe_repo = RecipeRepository(st.session_state.db_client)
        if selected_recipe_name and selected_recipe_name != "None":
            recipe = run_async(_fetch_recipe_for_scaffold(selected_recipe_name, recipe_repo))
            if recipe is not None:
                recipe_id = recipe.id
                recipe_name = recipe.name
 
        setup_description = st.text_area(
            "Description (optional)",
            placeholder="DPO fine-tune of velvet-2b on curated preference data",
            help="Pre-fills experiment.yml description for lineage tracking",
        )
 
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
        plot_dir = st.text_input(
            "Plots URI (optional)",
            value="/nfs/merge-output/${experiment.name}/${experiment.id}/plots",
            help="Plots output directory. Supports template variables: ${experiment.name}, ${experiment.id}",
        )
        cache_dir = st.text_input(
            "Dataset Cache Directory (optional)",
            value="/nfs/training-output/.dpo-cache/${experiment.name}/data",
            help="Dataset cache directory. Supports template variables: ${experiment.name}",
        )
 
        st.markdown("**Hyperparameters**")
        learning_rate = st.number_input("Learning Rate", value=2e-4, format="%.2e", step=1e-5)
        batch_size = st.number_input("Batch Size", value=4, min_value=1, step=1)
        epochs = st.number_input("Epochs", value=1.0, min_value=0.1, step=0.1)
 
    with st.expander("Hardware Configuration (optional, skypilot-based)"):
        hw_col1, hw_col2 = st.columns(2)
        with hw_col1:
            gpu_type = st.text_input(
                "GPU Type", placeholder="A100-80GB",
                help=(
                    "Specifica il tipo di acceleratore. Formati supportati:\n\n"
                    "• A100-80GB → usa il valore di 'GPU Count'\n"
                    "• A100-80GB:4 → conteggio inline, 'GPU Count' viene IGNORATO\n"
                    "• {A100:1, V100:1} → set non ordinato, 'GPU Count' viene IGNORATO\n"
                    "• [L4:1, H100:1, A100:1] → lista ordinata, 'GPU Count' viene IGNORATO\n\n"
                    "⚠️ A100 (40GB) e A100-80GB sono hardware distinti e non intercambiabili.\n\n"
                    "Docs: https://docs.skypilot.co/en/latest/compute/gpus.html"
                )
            )
            count_is_inline = (
                ":" in gpu_type or
                gpu_type.strip().startswith("{") or
                gpu_type.strip().startswith("[")
            )
            gpu_count = st.number_input(
                "GPU Count", value=1, min_value=1, step=1, disabled=count_is_inline,
                help=""" [Ignorato se GPU Type contiene già il conteggio (es. A100:4, {A100:1}, [L4:1]).] \n Numero di GPU per nodo. Inserisci un numero intero (es. 1, 4, 8).\n Se specificato insieme al GPU Type, usa il formato combinato <NOME>:<QUANTITÀ> nel campo GPU Type (es. A100-80GB:4). \n DOCS URL: https://docs.skypilot.co/en/latest/reference/yaml-spec.html#resources-accelerators"""
            )
        with hw_col2:
            cpus = st.text_input("CPUs", placeholder="128+", help="""Numero di vCPU per nodo.\nFormati accettati: \n4 — esattamente 4 vCPU \n4+ — almeno 4 vCPU (SkyPilot sceglierà l'istanza più economica con ≥ 4 vCPU)\nEsempio: 128+ significa "almeno 128 vCPU".\n DOCS URL: https://docs.skypilot.co/en/latest/reference/yaml-spec.html#resources-cpus """)
            memory = st.text_input("Memory", placeholder="216+", help="""Quantità di RAM per nodo.\nFormati accettati:\n64 — esattamente 64 GB\n64+ — almeno 64 GB\nCon unità: 1024MB, 64GB, 2TB\nUnità supportate (case-insensitive): KB, MB, GB (default), TB, PB.\nEsempio: 216+ significa "almeno 216 GB di RAM". \n DOCS URL: https://docs.skypilot.co/en/latest/reference/yaml-spec.html#resources-memory""")
 
    with st.expander("Server Options (optional, else default to http://localhost:8502)"):
        server_url = st.text_input("Server URL", placeholder="http://localhost:8502", help="URL of the server to connect to.")
        protocol = st.selectbox("Protocol", ["http", "https", "gRPC"], help="Protocol to use for server communication.")
        timeout = st.number_input("Timeout (seconds)", value=30, min_value=1, step=1, help="Timeout for server requests.")
        retry = st.number_input("Retry Attempts", value=3, min_value=0, step=1, help="Number of retry attempts for server requests.")
        blocking = st.checkbox("Blocking Mode", value=True, help="Whether to use blocking mode for server requests.")
 
    st.divider()
    if st.button("Generate & Download", type="primary", disabled=not (setup_name and model_uri and model_id and output_dir)):
        hardware = None
        if gpu_type:
            accelerators = _parse_accelerators(gpu_type, int(gpu_count))
            hardware = {
                "skypilot": {
                    "resources": {
                        "accelerators": accelerators,
                        "cpus": cpus or None,
                        "memory": memory or None,
                    },
                },
                "gpu": {
                    "type": gpu_type,
                    "count": int(gpu_count),
                },
            }
 
        selected_component_obj = component_map.get(selected_component)
        component_uri = selected_component_obj.uri if selected_component_obj else None
 
        scaffold_uuid = str(uuid.uuid4())
 
        selections = {
            "setup_name": setup_name,
            "component_name": selected_component,
            "description": setup_description,
            "experiment_type": experiment_type.value,
            "model_uri": model_uri,
            "model_id": model_id,
            "recipe_id": recipe_id,
            "recipe_name": recipe_name,
            "output_dir": output_dir,
            "metrics_uri": metrics_uri,
            "plot_dir": plot_dir,
            "cache_dir": cache_dir,
            "learning_rate": learning_rate,
            "batch_size": int(batch_size),
            "epochs": float(epochs),
            "hardware": hardware,
            "injected_experiment_uuid": scaffold_uuid,
            "server_url": server_url if server_url else "http://localhost:8502",
            "protocol": protocol if protocol else "http",
            "timeout": int(timeout) if timeout is not None else 30,
            "retry": int(retry) if retry is not None else 3,
            "blocking": bool(blocking) if blocking is not None else True,
        }
 
        if component_uri is None:
            st.warning(f"No URI found for component '{selected_component}'. Generating config-only scaffold.")
 
        zip_bytes = _build_zip(experiment_type=experiment_type, component_uri= component_uri, selections= selections, recipe=recipe)
 
        st.success(f"Scaffold generated: `{setup_name}/` (from template: `{selected_component}`)")
        st.download_button(
            label=f"Download {setup_name}.zip",
            data=zip_bytes,
            file_name=f"{setup_name}.zip",
            mime="application/zip",
        )
    elif not setup_name:
        st.info("Fill in Setup Name, Model, and Output Directory to generate.")
 
# ---------------------------------------------------------------------------
# UI — Create form (EVALUATION)
# ---------------------------------------------------------------------------
 
def _render_create_form_evaluation() -> None:
    """Render the setup creation form — EVALUATION use case."""
    experiment_type = RunType.EVALUATION
 
    st.subheader("Configure your evaluation setup")
 
    try:
        components = run_async(_list_components_async())
        models = run_async(_list_models_async())
        recipes = run_async(_list_recipes_async())
    except Exception as e:
        st.error(f"Failed to load data from Neo4j: {e}")
        components, models, recipes = [], [], []
 
    col1, col2 = st.columns(2)
 
    with col1:
        setup_name = st.text_input(
            "Setup Name *",
            placeholder="EVAL-velvet2B",
            help="Becomes the root folder name in the zip download (overrides component template name)",
        )
 
        component_options = [c.name for c in components if c.name]
        component_map = {c.name: c for c in components}
 
        selected_component = st.selectbox(
            "Component Name *",
            options=component_options if component_options else [],
            help="Component template from the database",
        )
 
        model_options = [m.model_name for m in models]
        model_input_mode = st.radio("Model source", ["Select from DB", "Enter manually"], horizontal=True)
 
        if model_input_mode == "Select from DB" and model_options:
            selected_model = st.selectbox("Model *", options=model_options)
            model_uri = next((m.uri or "" for m in models if m.model_name == selected_model), "")
            model_id = selected_model
        else:
            model_uri = st.text_input("Model URI *", placeholder="/nfs/models/velvet-2b/checkpoint")
            model_id = st.text_input("Model ID *", placeholder="velvet-2b_ba53454_t0")
 
    with col2:
        recipe_options = {r.name: r for r in recipes}
        selected_recipe_name = st.selectbox(
            "Recipe (optional)",
            options=["None"] + list(recipe_options.keys()),
        )
        # Initialize recipe variables to prevent NameError when building selections dict
        recipe: Optional[Recipe] = None
        recipe_id: str | None = None
        recipe_name: str | None = None
        recipe_repo = RecipeRepository(st.session_state.db_client)
        if selected_recipe_name and selected_recipe_name != "None":
            recipe = run_async(_fetch_recipe_for_scaffold(selected_recipe_name, recipe_repo))
            if recipe is not None:
                recipe_id = recipe.id
                recipe_name = recipe.name
 
        setup_description = st.text_area(
            "Description (optional)",
            placeholder="Evaluation run of velvet-2b on benchmark suite X",
            help="Pre-fills experiment.yml description for lineage tracking",
        )
 
        output_dir = st.text_input(
            "Output Directory *",
            value="/nfs/eval-output/${experiment.name}/${experiment.id}/results",
            help="Evaluation results output directory. Supports template variables: ${experiment.name}, ${experiment.id}",
        )
        metrics_uri = st.text_input(
            "Metrics URI (optional)",
            value="/nfs/eval-output/${experiment.name}/${experiment.id}/metrics",
            help="Metrics output directory. Supports template variables: ${experiment.name}, ${experiment.id}",
        )
        plot_dir = st.text_input(
            "Plots URI (optional)",
            value="/nfs/merge-output/${experiment.name}/${experiment.id}/plots",
            help="Plots output directory. Supports template variables: ${experiment.name}, ${experiment.id}",
        )
        cache_dir = st.text_input(
            "Dataset Cache Directory (optional)",
            value="/nfs/eval-output/${experiment.name}/data",
            help="Dataset cache directory. Supports template variables: ${experiment.name}",
        )
 
        st.markdown("**Hyperparameters**")
        learning_rate = st.number_input("Learning Rate", value=2e-4, format="%.2e", step=1e-5)
        batch_size = st.number_input("Batch Size", value=4, min_value=1, step=1)
        epochs = st.number_input("Epochs", value=1.0, min_value=0.1, step=0.1)
 
    with st.expander("Hardware Configuration (optional, skypilot-based)"):
        hw_col1, hw_col2 = st.columns(2)
        with hw_col1:
            gpu_type = st.text_input(
                "GPU Type", placeholder="A100-80GB",
                help=(
                    "Specifica il tipo di acceleratore. Formati supportati:\n\n"
                    "• A100-80GB → usa il valore di 'GPU Count'\n"
                    "• A100-80GB:4 → conteggio inline, 'GPU Count' viene IGNORATO\n"
                    "• {A100:1, V100:1} → set non ordinato, 'GPU Count' viene IGNORATO\n"
                    "• [L4:1, H100:1, A100:1] → lista ordinata, 'GPU Count' viene IGNORATO\n\n"
                    "⚠️ A100 (40GB) e A100-80GB sono hardware distinti e non intercambiabili.\n\n"
                    "Docs: https://docs.skypilot.co/en/latest/compute/gpus.html"
                )
            )
            count_is_inline = (
                ":" in gpu_type or
                gpu_type.strip().startswith("{") or
                gpu_type.strip().startswith("[")
            )
            gpu_count = st.number_input(
                "GPU Count", value=1, min_value=1, step=1, disabled=count_is_inline,
                help=""" [Ignorato se GPU Type contiene già il conteggio (es. A100:4, {A100:1}, [L4:1]).] \n Numero di GPU per nodo. Inserisci un numero intero (es. 1, 4, 8).\n Se specificato insieme al GPU Type, usa il formato combinato <NOME>:<QUANTITÀ> nel campo GPU Type (es. A100-80GB:4). \n DOCS URL: https://docs.skypilot.co/en/latest/reference/yaml-spec.html#resources-accelerators"""
            )
        with hw_col2:
            cpus = st.text_input("CPUs", placeholder="128+", help="""Numero di vCPU per nodo.\nFormati accettati: \n4 — esattamente 4 vCPU \n4+ — almeno 4 vCPU (SkyPilot sceglierà l'istanza più economica con ≥ 4 vCPU)\nEsempio: 128+ significa "almeno 128 vCPU".\n DOCS URL: https://docs.skypilot.co/en/latest/reference/yaml-spec.html#resources-cpus """)
            memory = st.text_input("Memory", placeholder="216+", help="""Quantità di RAM per nodo.\nFormati accettati:\n64 — esattamente 64 GB\n64+ — almeno 64 GB\nCon unità: 1024MB, 64GB, 2TB\nUnità supportate (case-insensitive): KB, MB, GB (default), TB, PB.\nEsempio: 216+ significa "almeno 216 GB di RAM". \n DOCS URL: https://docs.skypilot.co/en/latest/reference/yaml-spec.html#resources-memory""")
 
    with st.expander("Server Options (optional)"):
        server_url = st.text_input("Server URL", placeholder="http://localhost:8502", help="URL of the server to connect to.")
        protocol = st.selectbox("Protocol", ["http", "https", "gRPC"], help="Protocol to use for server communication.")
        timeout = st.number_input("Timeout (seconds)", value=30, min_value=1, step=1, help="Timeout for server requests.")
        retry = st.number_input("Retry Attempts", value=3, min_value=0, step=1, help="Number of retry attempts for server requests.")
        blocking = st.checkbox("Blocking Mode", value=True, help="Whether to use blocking mode for server requests.")
    
    st.divider()
    if st.button("Generate & Download", type="primary", disabled=not (setup_name and model_uri and model_id and output_dir)):
        hardware = None
        if gpu_type:
            accelerators = _parse_accelerators(gpu_type, int(gpu_count))
            hardware = {
                "skypilot": {
                    "resources": {
                        "accelerators": accelerators,
                        "cpus": cpus or None,
                        "memory": memory or None,
                    },
                },
                "gpu": {
                    "type": gpu_type,
                    "count": int(gpu_count),
                },
            }
 
        selected_component_obj = component_map.get(selected_component)
        component_uri = selected_component_obj.uri if selected_component_obj else None
 
        scaffold_uuid = str(uuid.uuid4())
 
        selections = {
            "setup_name": setup_name,
            "component_name": selected_component,
            "description": setup_description,
            "experiment_type": experiment_type.value,
            "model_uri": model_uri,
            "model_id": model_id,
            "recipe_id": recipe_id,
            "recipe_name": recipe_name,
            "output_dir": output_dir,
            "metrics_uri": metrics_uri,
            "plot_dir": plot_dir,
            "cache_dir": cache_dir,
            "learning_rate": learning_rate,
            "batch_size": int(batch_size),
            "epochs": float(epochs),
            "hardware": hardware,
            "injected_experiment_uuid": scaffold_uuid,
            "server_url": server_url if server_url else "http://localhost:8502",
            "protocol": protocol if protocol else "http",
            "timeout": int(timeout) if timeout is not None else 30,
            "retry": int(retry) if retry is not None else 3,
            "blocking": bool(blocking) if blocking is not None else True,
        }
 
        if component_uri is None:
            st.warning(f"No URI found for component '{selected_component}'. Generating config-only scaffold.")
 
        zip_bytes = _build_zip(experiment_type=experiment_type, component_uri= component_uri, selections= selections, recipe=recipe)
 
        st.success(f"Scaffold generated: `{setup_name}/` (from template: `{selected_component}`)")
        st.download_button(
            label=f"Download {setup_name}.zip",
            data=zip_bytes,
            file_name=f"{setup_name}.zip",
            mime="application/zip",
        )
    elif not setup_name:
        st.info("Fill in Setup Name, Model, and Output Directory to generate.")
 
# ---------------------------------------------------------------------------
# UI — Create form (INFERENCE)
# ---------------------------------------------------------------------------
 
def _render_create_form_inference() -> None:
    """Render the setup creation form — INFERENCE use case."""
    experiment_type = RunType.INFERENCE
 
    st.subheader("Configure your inference setup")
 
    try:
        components = run_async(_list_components_async())
        models = run_async(_list_models_async())
        recipes = run_async(_list_recipes_async())
    except Exception as e:
        st.error(f"Failed to load data from Neo4j: {e}")
        components, models, recipes = [], [], []
 
    col1, col2 = st.columns(2)
 
    with col1:
        setup_name = st.text_input(
            "Setup Name *",
            placeholder="INFER-velvet2B",
            help="Becomes the root folder name in the zip download (overrides component template name)",
        )
 
        component_options = [c.name for c in components if c.name]
        component_map = {c.name: c for c in components}
 
        selected_component = st.selectbox(
            "Component Name *",
            options=component_options if component_options else [],
            help="Component template from the database",
        )
 
        model_options = [m.model_name for m in models]
        model_input_mode = st.radio("Model source", ["Select from DB", "Enter manually"], horizontal=True)
 
        if model_input_mode == "Select from DB" and model_options:
            selected_model = st.selectbox("Model *", options=model_options)
            model_uri = next((m.uri or "" for m in models if m.model_name == selected_model), "")
            model_id = selected_model
        else:
            model_uri = st.text_input("Model URI *", placeholder="/nfs/models/velvet-2b/checkpoint")
            model_id = st.text_input("Model ID *", placeholder="velvet-2b_ba53454_t0")
 
    with col2:
        recipe_options = {r.name: r for r in recipes}
        selected_recipe_name = st.selectbox(
            "Recipe (optional)",
            options=["None"] + list(recipe_options.keys()),
        )
        # Initialize recipe variables to prevent NameError when building selections dict
        recipe: Optional[Recipe] = None
        recipe_id: str | None = None
        recipe_name: str | None = None
        recipe_repo = RecipeRepository(st.session_state.db_client)
        if selected_recipe_name and selected_recipe_name != "None":
            recipe = run_async(_fetch_recipe_for_scaffold(selected_recipe_name, recipe_repo))
            if recipe is not None:
                recipe_id = recipe.id
                recipe_name = recipe.name
 
        setup_description = st.text_area(
            "Description (optional)",
            placeholder="Batch inference of velvet-2b on dataset Y",
            help="Pre-fills experiment.yml description for lineage tracking",
        )
 
        output_dir = st.text_input(
            "Output Directory *",
            value="/nfs/inference-output/${experiment.name}/${experiment.id}/predictions",
            help="Predictions output directory. Supports template variables: ${experiment.name}, ${experiment.id}",
        )
        metrics_uri = st.text_input(
            "Metrics URI (optional)",
            value="/nfs/inference-output/${experiment.name}/${experiment.id}/metrics",
            help="Metrics output directory. Supports template variables: ${experiment.name}, ${experiment.id}",
        )
        plot_dir = st.text_input(
            "Plots URI (optional)",
            value="/nfs/merge-output/${experiment.name}/${experiment.id}/plots",
            help="Plots output directory. Supports template variables: ${experiment.name}, ${experiment.id}",
        )
        cache_dir = st.text_input(
            "Dataset Cache Directory (optional)",
            value="/nfs/inference-output/${experiment.name}/data",
            help="Dataset cache directory. Supports template variables: ${experiment.name}",
        )
 
        st.markdown("**Hyperparameters**")
        learning_rate = st.number_input("Learning Rate", value=2e-4, format="%.2e", step=1e-5)
        batch_size = st.number_input("Batch Size", value=4, min_value=1, step=1)
        epochs = st.number_input("Epochs", value=1.0, min_value=0.1, step=0.1)
 
    with st.expander("Hardware Configuration (optional, skypilot-based)"):
        hw_col1, hw_col2 = st.columns(2)
        with hw_col1:
            gpu_type = st.text_input(
                "GPU Type", placeholder="A100-80GB",
                help=(
                    "Specifica il tipo di acceleratore. Formati supportati:\n\n"
                    "• A100-80GB → usa il valore di 'GPU Count'\n"
                    "• A100-80GB:4 → conteggio inline, 'GPU Count' viene IGNORATO\n"
                    "• {A100:1, V100:1} → set non ordinato, 'GPU Count' viene IGNORATO\n"
                    "• [L4:1, H100:1, A100:1] → lista ordinata, 'GPU Count' viene IGNORATO\n\n"
                    "⚠️ A100 (40GB) e A100-80GB sono hardware distinti e non intercambiabili.\n\n"
                    "Docs: https://docs.skypilot.co/en/latest/compute/gpus.html"
                )
            )
            count_is_inline = (
                ":" in gpu_type or
                gpu_type.strip().startswith("{") or
                gpu_type.strip().startswith("[")
            )
            gpu_count = st.number_input(
                "GPU Count", value=1, min_value=1, step=1, disabled=count_is_inline,
                help=""" [Ignorato se GPU Type contiene già il conteggio (es. A100:4, {A100:1}, [L4:1]).] \n Numero di GPU per nodo. Inserisci un numero intero (es. 1, 4, 8).\n Se specificato insieme al GPU Type, usa il formato combinato <NOME>:<QUANTITÀ> nel campo GPU Type (es. A100-80GB:4). \n DOCS URL: https://docs.skypilot.co/en/latest/reference/yaml-spec.html#resources-accelerators"""
            )
        with hw_col2:
            cpus = st.text_input("CPUs", placeholder="128+", help="""Numero di vCPU per nodo.\nFormati accettati: \n4 — esattamente 4 vCPU \n4+ — almeno 4 vCPU (SkyPilot sceglierà l'istanza più economica con ≥ 4 vCPU)\nEsempio: 128+ significa "almeno 128 vCPU".\n DOCS URL: https://docs.skypilot.co/en/latest/reference/yaml-spec.html#resources-cpus """)
            memory = st.text_input("Memory", placeholder="216+", help="""Quantità di RAM per nodo.\nFormati accettati:\n64 — esattamente 64 GB\n64+ — almeno 64 GB\nCon unità: 1024MB, 64GB, 2TB\nUnità supportate (case-insensitive): KB, MB, GB (default), TB, PB.\nEsempio: 216+ significa "almeno 216 GB di RAM". \n DOCS URL: https://docs.skypilot.co/en/latest/reference/yaml-spec.html#resources-memory""")
 

    with st.expander("Server Options (optional)"):
        server_url = st.text_input("Server URL", placeholder="http://localhost:8502", help="URL of the server to connect to.")
        protocol = st.selectbox("Protocol", ["http", "https", "gRPC"], help="Protocol to use for server communication.")
        timeout = st.number_input("Timeout (seconds)", value=30, min_value=1, step=1, help="Timeout for server requests.")
        retry = st.number_input("Retry Attempts", value=3, min_value=0, step=1, help="Number of retry attempts for server requests.")
        blocking = st.checkbox("Blocking Mode", value=True, help="Whether to use blocking mode for server requests.")
 
    st.divider()
    if st.button("Generate & Download", type="primary", disabled=not (setup_name and model_uri and model_id and output_dir)):
        hardware = None
        if gpu_type:
            accelerators = _parse_accelerators(gpu_type, int(gpu_count))
            hardware = {
                "skypilot": {
                    "resources": {
                        "accelerators": accelerators,
                        "cpus": cpus or None,
                        "memory": memory or None,
                    },
                },
                "gpu": {
                    "type": gpu_type,
                    "count": int(gpu_count),
                },
            }
 
        selected_component_obj = component_map.get(selected_component)
        component_uri = selected_component_obj.uri if selected_component_obj else None
 
        scaffold_uuid = str(uuid.uuid4())
 
        selections = {
            "setup_name": setup_name,
            "component_name": selected_component,
            "description": setup_description,
            "experiment_type": experiment_type.value,
            "model_uri": model_uri,
            "model_id": model_id,
            "recipe_id": recipe_id,
            "recipe_name": recipe_name,
            "output_dir": output_dir,
            "metrics_uri": metrics_uri,
            "plot_dir": plot_dir,
            "cache_dir": cache_dir,
            "learning_rate": learning_rate,
            "batch_size": int(batch_size),
            "epochs": float(epochs),
            "hardware": hardware,
            "injected_experiment_uuid": scaffold_uuid,
            "server_url": server_url if server_url else "http://localhost:8502",
            "protocol": protocol if protocol else "http",
            "timeout": int(timeout) if timeout is not None else 30,
            "retry": int(retry) if retry is not None else 3,
            "blocking": bool(blocking) if blocking is not None else True,
        }
 
        if component_uri is None:
            st.warning(f"No URI found for component '{selected_component}'. Generating config-only scaffold.")
 
        zip_bytes = _build_zip(experiment_type=experiment_type, component_uri= component_uri, selections= selections, recipe=recipe)
 
        st.success(f"Scaffold generated: `{setup_name}/` (from template: `{selected_component}`)")
        st.download_button(
            label=f"Download {setup_name}.zip",
            data=zip_bytes,
            file_name=f"{setup_name}.zip",
            mime="application/zip",
        )
    elif not setup_name:
        st.info("Fill in Setup Name, Model, and Output Directory to generate.") 
 
# ---------------------------------------------------------------------------
# UI — Create form (MERGING)
# ---------------------------------------------------------------------------
 
def _render_create_form_merging() -> None:
    """Render the setup creation form — MERGING use case."""
    experiment_type = RunType.MERGING
 
    st.subheader("Configure your merging setup")
 
    # Initialize recipe variables to prevent NameError when building selections dict
    recipe: Optional[Recipe] = None
    recipe_id: str | None = None
    recipe_name: str | None = None
 
    try:
        components = run_async(_list_components_async())
        models = run_async(_list_models_async())
    except Exception as e:
        st.error(f"Failed to load data from Neo4j: {e}")
        components, models, recipes = [], [], []
 
    col1, col2 = st.columns(2)
 
    with col1:
        setup_name = st.text_input(
            "Setup Name *",
            placeholder="MERGE-velvet2B",
            help="Becomes the root folder name in the zip download (overrides component template name)",
        )
 
        component_options = [c.name for c in components if c.name]
        component_map = {c.name: c for c in components}
 
        selected_component = st.selectbox(
            "Component Name *",
            options=component_options if component_options else [],
            help="Component template from the database",
        )
 
        model_options = [m.model_name for m in models]
        model_input_mode = st.radio("Model source", ["Select from DB", "Enter manually"], horizontal=True)
 
        if model_input_mode == "Select from DB" and model_options:
            selected_model = st.selectbox("Model *", options=model_options)
            model_uri = next((m.uri or "" for m in models if m.model_name == selected_model), "")
            model_id = selected_model
        else:
            model_uri = st.text_input("Model URI *", placeholder="/nfs/models/velvet-2b/checkpoint")
            model_id = st.text_input("Model ID *", placeholder="velvet-2b_ba53454_t0")
 
    with col2:
        
 
        setup_description = st.text_area(
            "Description (optional)",
            placeholder="Merge of checkpoint-1 and checkpoint-2 via task_arithmetic",
            help="Pre-fills experiment.yml description for lineage tracking",
        )
 
        output_dir = st.text_input(
            "Output Directory *",
            value="/nfs/merge-output/${experiment.name}/${experiment.id}/checkpoints",
            help="Merged checkpoint output directory. Supports template variables: ${experiment.name}, ${experiment.id}",
        )
        metrics_uri = st.text_input(
            "Metrics URI (optional)",
            value="/nfs/merge-output/${experiment.name}/${experiment.id}/metrics",
            help="Metrics output directory. Supports template variables: ${experiment.name}, ${experiment.id}",
        )
        plot_dir = st.text_input(
            "Plots URI (optional)",
            value="/nfs/merge-output/${experiment.name}/${experiment.id}/plots",
            help="Plots output directory. Supports template variables: ${experiment.name}, ${experiment.id}",
        )
        cache_dir = st.text_input(
            "Dataset Cache Directory (optional)",
            value="/nfs/merge-output/${experiment.name}/data",
            help="Dataset cache directory. Supports template variables: ${experiment.name}",
        )
 
        st.markdown("**Hyperparameters**")
        learning_rate = st.number_input("Learning Rate", value=2e-4, format="%.2e", step=1e-5)
        batch_size = st.number_input("Batch Size", value=4, min_value=1, step=1)
        epochs = st.number_input("Epochs", value=1.0, min_value=0.1, step=0.1)
 
    with st.expander("Hardware Configuration (optional, skypilot-based)"):
        hw_col1, hw_col2 = st.columns(2)
        with hw_col1:
            gpu_type = st.text_input(
                "GPU Type", placeholder="A100-80GB",
                help=(
                    "Specifica il tipo di acceleratore. Formati supportati:\n\n"
                    "• A100-80GB → usa il valore di 'GPU Count'\n"
                    "• A100-80GB:4 → conteggio inline, 'GPU Count' viene IGNORATO\n"
                    "• {A100:1, V100:1} → set non ordinato, 'GPU Count' viene IGNORATO\n"
                    "• [L4:1, H100:1, A100:1] → lista ordinata, 'GPU Count' viene IGNORATO\n\n"
                    "⚠️ A100 (40GB) e A100-80GB sono hardware distinti e non intercambiabili.\n\n"
                    "Docs: https://docs.skypilot.co/en/latest/compute/gpus.html"
                )
            )
            count_is_inline = (
                ":" in gpu_type or
                gpu_type.strip().startswith("{") or
                gpu_type.strip().startswith("[")
            )
            gpu_count = st.number_input(
                "GPU Count", value=1, min_value=1, step=1, disabled=count_is_inline,
                help=""" [Ignorato se GPU Type contiene già il conteggio (es. A100:4, {A100:1}, [L4:1]).] \n Numero di GPU per nodo. Inserisci un numero intero (es. 1, 4, 8).\n Se specificato insieme al GPU Type, usa il formato combinato <NOME>:<QUANTITÀ> nel campo GPU Type (es. A100-80GB:4). \n DOCS URL: https://docs.skypilot.co/en/latest/reference/yaml-spec.html#resources-accelerators"""
            )
        with hw_col2:
            cpus = st.text_input("CPUs", placeholder="128+", help="""Numero di vCPU per nodo.\nFormati accettati: \n4 — esattamente 4 vCPU \n4+ — almeno 4 vCPU (SkyPilot sceglierà l'istanza più economica con ≥ 4 vCPU)\nEsempio: 128+ significa "almeno 128 vCPU".\n DOCS URL: https://docs.skypilot.co/en/latest/reference/yaml-spec.html#resources-cpus """)
            memory = st.text_input("Memory", placeholder="216+", help="""Quantità di RAM per nodo.\nFormati accettati:\n64 — esattamente 64 GB\n64+ — almeno 64 GB\nCon unità: 1024MB, 64GB, 2TB\nUnità supportate (case-insensitive): KB, MB, GB (default), TB, PB.\nEsempio: 216+ significa "almeno 216 GB di RAM". \n DOCS URL: https://docs.skypilot.co/en/latest/reference/yaml-spec.html#resources-memory""")
 
    with st.expander("Model Merging"):
        merging_enabled = st.checkbox("Enable Model Merging", value=True)
        merge_method = st.selectbox("Merge Method", ["linear", "slerp", "ties", "dare", "task_arithmetic"])
        merge_sources = st.text_area("Sources (one per line)", placeholder="checkpoint-1\ncheckpoint-2")
 
    with st.expander("Server Options (optional)"):
        server_url = st.text_input("Server URL", placeholder="http://localhost:8502", help="URL of the server to connect to.")
        protocol = st.selectbox("Protocol", ["http", "https", "gRPC"], help="Protocol to use for server communication.")
        timeout = st.number_input("Timeout (seconds)", value=30, min_value=1, step=1, help="Timeout for server requests.")
        retry = st.number_input("Retry Attempts", value=3, min_value=0, step=1, help="Number of retry attempts for server requests.")
        blocking = st.checkbox("Blocking Mode", value=True, help="Whether to use blocking mode for server requests.")
 
    st.divider()
    if st.button("Generate & Download", type="primary", disabled=not (setup_name and model_uri and model_id and output_dir)):
        hardware = None
        if gpu_type:
            accelerators = _parse_accelerators(gpu_type, int(gpu_count))
            hardware = {
                "skypilot": {
                    "resources": {
                        "accelerators": accelerators,
                        "cpus": cpus or None,
                        "memory": memory or None,
                    },
                },
                "gpu": {
                    "type": gpu_type,
                    "count": int(gpu_count),
                },
            }
 
        selected_component_obj = component_map.get(selected_component)
        component_uri = selected_component_obj.uri if selected_component_obj else None
 
        scaffold_uuid = str(uuid.uuid4())
 
        selections = {
            "setup_name": setup_name,
            "component_name": selected_component,
            "description": setup_description,
            "experiment_type": experiment_type.value,
            "model_uri": model_uri,
            "model_id": model_id,
            "recipe_id": recipe_id,
            "recipe_name": recipe_name,
            "output_dir": output_dir,
            "metrics_uri": metrics_uri,
            "plot_dir": plot_dir,
            "cache_dir": cache_dir,
            "learning_rate": learning_rate,
            "batch_size": int(batch_size),
            "epochs": float(epochs),
            "hardware": hardware,
            "merging_enabled": merging_enabled,
            "merge_method": merge_method if merging_enabled else None,
            "merge_sources": [s.strip() for s in merge_sources.split("\n") if s.strip()] if merging_enabled else [],
            "injected_experiment_uuid": scaffold_uuid,
            "server_url": server_url if server_url else "http://localhost:8502",
            "protocol": protocol if protocol else "http",
            "timeout": int(timeout) if timeout is not None else 30,
            "retry": int(retry) if retry is not None else 3,
            "blocking": bool(blocking) if blocking is not None else True,
        }
 
        if component_uri is None:
            st.warning(f"No URI found for component '{selected_component}'. Generating config-only scaffold.")
 
        zip_bytes = _build_zip(experiment_type=experiment_type, component_uri= component_uri, selections= selections, recipe=recipe)
 
        st.success(f"Scaffold generated: `{setup_name}/` (from template: `{selected_component}`)")
        st.download_button(
            label=f"Download {setup_name}.zip",
            data=zip_bytes,
            file_name=f"{setup_name}.zip",
            mime="application/zip",
        )
    elif not setup_name:
        st.info("Fill in Setup Name, Model, and Output Directory to generate.")
 
# ---------------------------------------------------------------------------
# UI — Browse templates (scoped al experiment type del wizard)
# ---------------------------------------------------------------------------
 
def _render_browse_templates(experiment_type: RunType) -> None:
    """Show available templates and their contents, per experiment type."""
    st.subheader(f"Available Templates — {experiment_type.value.capitalize()}")
 
    setups_dir = _get_setups_dir(experiment_type)
 
    if not setups_dir.exists():
        st.info(f"No templates found in `graph_lineage/setups/{experiment_type.value}/`.")
        return
 
    templates = [d for d in setups_dir.iterdir() if d.is_dir() and not d.name.startswith("_")]
 
    if not templates:
        st.info(f"No templates found in `graph_lineage/setups/{experiment_type.value}/`.")
        return
 
    for template_dir in sorted(templates):
        with st.expander(f"{template_dir.name}"):
            for f in sorted(template_dir.rglob("*")):
                if f.is_file() and f.name in _BROWSE_ALLOWED_FILES:
                    rel_path = f.relative_to(template_dir)
                    st.markdown(f"**{rel_path}**")
                    if f.suffix == ".py":
                        st.code(_safe_read_file(f), language="python")
                    elif f.suffix == ".txt":
                        st.code(_safe_read_file(f), language="text")
                    elif f.suffix in (".yml", ".yaml"):
                        st.code(_safe_read_file(f), language="yaml")
                    else:
                        st.text(_safe_read_file(f))
