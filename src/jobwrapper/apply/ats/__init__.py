from ...autofill import Catalog
from .adapters import ADAPTERS, GenericAdapter
from .base import ATSAdapter, StepResult

BY_NAME = {cls.name: cls for cls in ADAPTERS}


def adapter_for(name: str = "", url: str = "", html: str = "",
                catalog: Catalog | None = None) -> ATSAdapter:
    """Explicit vendor name wins; otherwise sniff the page."""
    catalog = catalog or Catalog()
    if name and name in BY_NAME:
        return BY_NAME[name](catalog)
    for cls in ADAPTERS:
        if cls is GenericAdapter:
            continue
        if cls.detect(url, html, catalog):
            return cls(catalog)
    return GenericAdapter(catalog)


__all__ = ["ADAPTERS", "ATSAdapter", "BY_NAME", "GenericAdapter", "StepResult", "adapter_for"]
