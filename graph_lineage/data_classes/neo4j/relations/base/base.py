"""base/base_relation.py — classe base per gli edge (relazioni) del grafo Neo4j."""
from __future__ import annotations
import re
from typing import ClassVar, Optional, Type, Any
from pydantic import BaseModel, Field, model_validator, ConfigDict

from ...nodes.base.base import BaseNode

_CAMEL_RE = re.compile(r"(?<!^)(?=[A-Z])")


def _camel_to_snake_upper(name: str) -> str:
    """UsesData -> USES_DATA, DerivedFrom -> DERIVED_FROM."""
    return _CAMEL_RE.sub("_", name).upper()


class BaseRelation(BaseModel):
    """Base per ogni relazione (edge) del grafo.

    - Il `label` Neo4j e' per convenzione il nome della classe (snake_upper),
      salvo `label_override` esplicito.
    - `source_type` / `target_type` sono vincoli statici sui tipi di nodo ammessi.
    - Le sottoclassi possono solo RESTRINGERE (mai allargare) i vincoli ereditati:
      controllo enforced a tempo di definizione classe via __init_subclass__.
    """

    model_config = ConfigDict(extra="allow")

    source_type: ClassVar[Type[BaseNode]] = BaseNode
    target_type: ClassVar[Type[BaseNode]] = BaseNode
    label_override: ClassVar[Optional[str]] = None

    source: BaseNode = Field(..., exclude=True, description="Nodo sorgente dell'edge")
    target: BaseNode = Field(..., exclude=True, description="Nodo destinazione dell'edge")

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)

        parent = cls.__mro__[1]
        parent_source = getattr(parent, "source_type", BaseNode)
        parent_target = getattr(parent, "target_type", BaseNode)

        if not issubclass(cls.source_type, parent_source):
            raise TypeError(
                f"{cls.__name__}.source_type ({cls.source_type.__name__}) deve restringere "
                f"{parent.__name__}.source_type ({parent_source.__name__}), non allargarlo"
            )
        if not issubclass(cls.target_type, parent_target):
            raise TypeError(
                f"{cls.__name__}.target_type ({cls.target_type.__name__}) deve restringere "
                f"{parent.__name__}.target_type ({parent_target.__name__}), non allargarlo"
            )

    @model_validator(mode="after")
    def _validate_endpoints(self) -> "BaseRelation":
        if not isinstance(self.source, self.source_type):
            raise TypeError(
                f"{type(self).__name__}: source deve essere {self.source_type.__name__}, "
                f"ricevuto {type(self.source).__name__}"
            )
        if not isinstance(self.target, self.target_type):
            raise TypeError(
                f"{type(self).__name__}: target deve essere {self.target_type.__name__}, "
                f"ricevuto {type(self.target).__name__}"
            )
        return self

    @property
    def __label__(self) -> str:
        return self.label_override or _camel_to_snake_upper(type(self).__name__)

    def to_neo4j_props(self) -> dict:
        """Proprieta' opzionali dell'edge (source/target esclusi: impliciti nel MATCH)."""
        return self.model_dump(exclude={"source", "target"})