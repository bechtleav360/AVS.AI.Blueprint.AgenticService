"""Asset-Modelle für den Harmonizing-Agenten.

Diese Modelle definieren das kanonische Asset-Schema, das vom Harmonizing-Agenten verwendet wird.
"""

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class AssetType:
    """Konstanten für Asset-Typen."""

    SOFTWARE = "software"
    HARDWARE = "hardware"


class AssetStatus:
    """Konstanten für Asset-Status."""

    DRAFT = "draft"
    UNTAGGED = "untagged"
    UNSCORED = "unscored"
    SCORED = "scored"


class Reference(BaseModel):
    """Verweis auf ein anderes Asset."""

    id: Optional[str] = Field(None, description="ID des referenzierten Assets")
    relation: Optional[str] = Field(
        None, description="Beziehung (z. B. dependsOn, providedBy)"
    )


class HardwareExtension(BaseModel):
    """Hardware-spezifische Erweiterungsfelder."""

    manufacturer: Optional[str] = Field(None, description="Name des Herstellers")
    model: Optional[str] = Field(None, description="Bezeichnung/Modell der Hardware")


class SoftwareExtension(BaseModel):
    """Software-spezifische Erweiterungsfelder."""

    manufacturer: Optional[str] = Field(None, description="Name des Herstellers")
    version: Optional[str] = Field(None, description="Softwareversion")
    licenseType: Optional[str] = Field(
        None, description="Lizenztyp der Software"
    )


class AssetHarmonizingOutput(BaseModel):
    """Kanonisches Asset-Schema für harmonisierte Daten.

    Dies ist das einheitliche Schema, in das alle Quelldaten harmonisiert werden.
    """

    # Basic fields
    id: Optional[str] = Field(None, description="ID des Assets")
    name: Optional[str] = Field(None, description="Name des Assets")
    description: Optional[str] = Field(
        None, description="weiterführende Beschreibung des Assets"
    )
    type: Optional[
        Literal[
            AssetType.SOFTWARE,
            AssetType.HARDWARE,
        ]
    ] = Field(None, description="übergeordneter Asset-Typ")

    externalId: Optional[Dict[str, str]] = Field(
        default=None,
        description="Kennungen aus Quellsystemen (Schlüssel: Quellsystem, Wert: externe ID)",
    )
    status: Optional[
        Literal[
            AssetStatus.DRAFT,
            AssetStatus.UNTAGGED,
            AssetStatus.UNSCORED,
            AssetStatus.SCORED,
        ]
    ] = Field(None, description="aktueller Status dieses Assets")

    # After-harmonizing policy: these must be null
    tags: Optional[List[str]] = Field(
        default=None,
        description="Liste von Tags, die diesem Asset zugeordnet sind (nach der Harmonisierung null)",
    )
    references: Optional[List[Reference]] = Field(
        default=None,
        description="Verweise auf andere Assets (nach der Harmonisierung null)",
    )
    additionalProperties: Optional[Dict[str, Any]] = Field(
        default=None, description="Wörterbuch unverarbeiteter Quell-Eigenschaften"
    )

    # Extensions -  for easy handling the different types we just treat them as optional. we then load them to top level when using to_json().
    # TODO: maybe this is more prone to errors as the llm needs to think which fields to use.
    hardware: Optional[HardwareExtension] = None
    software: Optional[SoftwareExtension] = None

    def to_json(self) -> Dict[str, Any]:
        """Gibt ein JSON-bereites Dict zurück, bei dem Erweiterungsfelder auf die oberste Ebene abgeflacht sind.

        - Schließt None-Werte aus.
        - Führt Felder aus `hardware` und `software` auf Root-Ebene zusammen.
        """
        data: Dict[str, Any] = self.model_dump(exclude_none=True)

        # Extract and flatten extension fields
        for ext_name in ("hardware", "software"):
            ext = data.pop(ext_name, None)
            if isinstance(ext, dict):
                # Merge extension fields into the top-level dict
                data.update(ext)

        return data
