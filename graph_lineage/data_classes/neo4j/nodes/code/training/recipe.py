"""Pydantic models for Recipe entity."""

from __future__ import annotations
import json
from pathlib import Path
from pydantic import BaseModel, Field, model_validator, field_validator, ConfigDict
from typing import Optional, Dict, Any, List
from ..generic.run_setup import Setup

class RecipeEntry(BaseModel):
    """Metadata for a single distribution/dataset entry in a recipe."""

    chat_type: Optional[str] = Field(None, min_length=1, description="Chat conversation type")
    dist_id: Optional[str] = Field(None, min_length=1, description="Distribution unique identifier")
    dist_name: Optional[str] = Field(None, min_length=1, description="Human-readable distribution name")
    dist_uri: str = Field(..., min_length=1, description="Path or URI to distribution")
    replica: Optional[int] = Field(1, ge=1, description="Replication factor (N× oversampling)")
    samples: Optional[int] = Field(None, ge=0, description="Total number of samples in distribution")
    system_prompt: Optional[Dict[str, str]] = Field(None, description="System prompt name: content templates")
    tokens: Optional[int] = Field(None, ge=0, description="Total token count")
    words: Optional[int] = Field(None, ge=0, description="Total word count")
    validation_error: Optional[str] = Field(None, description="Validation error if any")

    model_config = ConfigDict(extra='allow')
    
    @property
    def custom_fields(self) -> Dict[str, Any]:
        """
        Estrae i campi extra non definiti né nella classe base né nel nodo figlio.
        Usa self.__class__ in modo corretto per guardare i campi del modello finale istanziato.
        """
        return {
            k: v for k, v in self.__dict__.items() 
            if k not in self.__class__.model_fields
        }

class Recipe(Setup):
    """Configuration for recipe/distribution Setup.

    Maps dataset paths to their metadata entries with optional scope, tasks, tags, and derived_from.
    """

    # Corretto in Optional[str] o str | None perché il default è None
    name: str = Field(..., min_length=1, description="Recipe name (must be unique)")
    description: Optional[str] = Field(None, description="Recipe description")
    scope: Optional[str] = Field(None, description="Scope for this recipe (e.g., 'sft', 'preference', 'rl')")
    tasks: Optional[list[str]] = Field(default_factory=list, description="Tasks associated with this recipe")
    tags: Optional[list[str]] = Field(default_factory=list, description="Tags for categorizing recipes")
    derived_from: Optional[str] = Field(None, description="Optional UUID of parent recipe this was derived from")
    
    entries: List[RecipeEntry] = Field(
        ...,
        description="List of distribution metadata objects (REQUIRED)"
    )

    @field_validator("entries", mode="before")
    @classmethod
    def deserialize_entries(cls, v):
        """Deserializza 'entries' da stringa JSON (es. da Neo4j) in lista di RecipeEntry.
        
        Supporta il nuovo formato dove ogni entry ha:
        - system_prompt: Dict[str, str] (mappa {prompt_name: prompt_content})
        
        Quando una stringa è ricevuta da Neo4j, viene parsata come JSON e
        convertita in liste di dict che Pydantic valida in RecipeEntry objects.
        """
        if isinstance(v, str):
            v = v.strip()
            if not v:
                return []
            try:
                deserialized = json.loads(v)
                # Validazione: atteso una lista di dict (entries)
                if not isinstance(deserialized, list):
                    raise ValueError(f"Expected list of entries, got {type(deserialized).__name__}")
                return deserialized
            except json.JSONDecodeError as e:
                raise ValueError(
                    f"Impossibile parsare la stringa 'entries' in JSON valido: {e}"
                )
        return v
    
    @model_validator(mode="after")
    def validate_recipe_name(self) -> Recipe:
        """Validate that name is not empty if provided and follows naming rules."""
        if self.name is not None and not self.name.strip():
            raise ValueError("Recipe name cannot be empty or whitespace")
        return self

    def ensure_name(self, filename: str) -> None:
        """Extract recipe name from filename and set if name is currently None."""
        if self.name is not None:
            return

        path = Path(filename)
        name_with_extension = path.name
        if "." in name_with_extension:
            extracted_name = name_with_extension.rsplit(".", 1)[0]
        else:
            extracted_name = name_with_extension

        if not extracted_name or not extracted_name.strip():
            raise ValueError(
                f"Recipe name required: provide 'name' field in YAML or upload file with valid filename"
            )

        self.name = extracted_name
