"""Pydantic models for Component entity."""

from __future__ import annotations
from typing import Optional
from pydantic import Field
from ..generic.run_setup import Setup 


class Component(Setup):
    """Component entity -- (technique, framework) pair from capability matrix.

    A Component represents a validated combination of technique + framework.
    If a (technique, framework) combo is not supported, the Component doesn't exist.
    This enforces compatibility at the data model level.

    Example: (grpo, unsloth) exists, (unknown, unsloth) doesn't exist → query returns None
    """

    name: str = Field(..., min_length=1, description="Component name = setup template folder name (e.g. dpo_trl)")
    uri: Optional[str] = Field("", description="Internal URI to setup template: ./graph_lineage/setups/{name}")

    description: Optional[str] = Field("", description="Component description")

    technique_code: Optional[str] = Field(..., min_length=1, description="Technique code (e.g., grpo, sft)")
    framework_code: Optional[str] = Field(..., min_length=1, description="Framework code (e.g., unsloth, trl)")
    opt_code: Optional[str] = Field("", description="Optimization code, Lora, Qlora, etc")

    docs_url: Optional[str] = Field("", description="Documentation URL")
    
