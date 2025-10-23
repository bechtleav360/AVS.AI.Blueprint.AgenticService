"""Data Transfer Objects (DTOs) for REST API endpoints."""

from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, Field


class AssetData(BaseModel):
    """Asset data from connector with type and properties."""

    type: Literal["software", "hardware"] = Field(
        description="Type of the asset: software or hardware"
    )
    properties: Dict[str, Any] = Field(
        default_factory=dict,
        description="Raw key/value pairs from the connector (unstructured data)",
    )


class HarmonizingInputPayload(BaseModel):
    """Input payload for harmonizing handler from connector events.

    Structure matches the event data from connectors.
    """

    subject: Optional[str] = Field(
        default=None,
        description="Optional subject field (not required)",
    )
    data: AssetData = Field(
        description="Asset data containing type and properties from connector"
    )

    class Config:
        json_schema_extra = {
            "examples": [
                {
                    "subject": None,
                    "data": {
                        "properties": {
                            "id": "S4905156",
                            "name": "HP EliteBook 8 Flip G1i 13 U5 16/512 GB",
                            "availability_view": {
                                "orderable": True,
                                "availability_id": "immediately",
                                "lead_time": 4,
                                "delivery_info_text": "Lieferung ab 6. Oktober. ",
                                "delivery_hint_text": "1 Stück verfügbar",
                                "stock_type_class": "",
                                "available_quantity": 1
                            },
                            "details_url": "/shop/hp-elitebook-8-flip-g1i-13-u5-16-512-gb--S4905156--p",
                            "image_path": "https://media.bechtle.com/is/180712/1c4b3d4ee288fc9434f5175bf56070570/c3/picture/de8528b762bc4f398f5c2e66e691ceb7?version=0",
                            "thumbnail_path": "https://media.bechtle.com/is/180712/1c4b3d4ee288fc9434f5175bf56070570/c3/thumbnail/de8528b762bc4f398f5c2e66e691ceb7?version=0",
                            "energy_efficiency": None,
                            "manufacturer_product_id": ".AD3G0ET#ABD",
                            "manufacturer": {
                                "manufacturer_name": "HP",
                                "manufacturer_image_path": "https://media.bechtle.com/is/180712/1c4b3d4ee288fc9434f5175bf56070570/c3/picture/3526cb94faf24e7da4bdbfde4ea64c62?version=0"
                            },
                            "description": "Displaygröße: 33,8 cm (13,3\"), Prozessormodell: Intel Core Ultra 5 225U, 1,5 GHz, Arbeitsspeicher: 16 GB, SSD: 512 GB, Akkulaufzeit (bis zu): 18 Stunden",
                            "top_features": {
                                "Displaygröße": "33,8 cm (13,3\")",
                                "Prozessormodell": "Intel Core Ultra 5 225U, 1,5 GHz",
                                "Arbeitsspeicher": "16 GB",
                                "SSD": "512 GB",
                                "Akkulaufzeit (bis zu)": "18 Stunden"
                            },
                            "price": {
                                "netto": 1191,
                                "brutto": 1417.29,
                                "eliminated_price": 1459,
                                "eliminated_percent": "-18",
                                "vat": 226.29,
                                "symbol": "€",
                                "currency_id": "EUR",
                                "country_iso": "de",
                                "language_iso": "de",
                                "fees": [],
                                "is_family": False,
                                "is_bios_price": False,
                                "is_cloud": False,
                                "billing_period": None
                            },
                            "item_type": "Notebooks",
                            "product_edition": {
                                "title": "Ausführung",
                                "value": "Deutsch"
                            },
                            "total_hits": 1,
                            "add_to_cart_status": " ",
                            "customer_id": None,
                            "search_type": "CATEGORY",
                            "outlet_image_path": "img/b_ware.png",
                            "ratings_view_opt": None,
                            "end_of_life": False,
                            "tracking_info": {
                                "categories": "hardware/mobile-computing/notebooks",
                                "manufacturer_id": "HEW"
                            },
                            "badges": [
                                {
                                    "text": "b-ware",
                                    "type": "bstock"
                                }
                            ],
                            "login_required": False,
                            "stock_type": "B",
                            "has_fast_lane": False,
                            "successor_link": None,
                            "has_accessories": False,
                            "information": None
                        },
                        "type": "hardware"
                    }
                }
            ]
        }

