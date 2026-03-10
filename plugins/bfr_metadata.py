"""
BFR KiCad Library Manager - Metadata Enrichment
Scrapes LCSC/JLCPCB for component metadata (part numbers, pricing, etc.)
Inspired by Bouni's kicad-jlcpcb-tools LCSC API approach.
"""

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Optional
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from urllib.parse import quote

logger = logging.getLogger("bfr_plugin")

# Browser User-Agent to avoid being blocked (same approach as Bouni)
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}


@dataclass
class PartMetadata:
    """Enriched part metadata from web lookups."""
    lcsc_part: str = ""
    digikey_part: str = ""
    manufacturer: str = ""
    mpn: str = ""
    description: str = ""
    package: str = ""
    category: str = ""
    subcategory: str = ""
    price: str = ""  # price string e.g. "0.0123"
    stock: int = 0
    datasheet_url: str = ""
    # For passives
    value: str = ""
    # Raw response data
    raw_data: dict = field(default_factory=dict)
    # Extra electrical attributes from JLCPCB (Voltage, Speed, etc)
    extra_attributes: dict = field(default_factory=dict)


def _make_request(url: str, payload: dict = None, timeout: int = 10) -> Optional[dict]:
    """Make an HTTP GET or POST request and return JSON response."""
    try:
        import ssl
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        
        headers = HEADERS.copy()
        data_bytes = None
        method = "GET"
        
        if payload:
            headers["Content-Type"] = "application/json"
            data_bytes = json.dumps(payload).encode("utf-8")
            method = "POST"
            
        req = Request(url, data=data_bytes, headers=headers, method=method)
        with urlopen(req, timeout=timeout, context=ctx) as response:
            if response.status == 200:
                return json.loads(response.read().decode("utf-8"))
    except (URLError, HTTPError, json.JSONDecodeError, TimeoutError) as e:
        logger.warning(f"Request failed for {url}: {e}")
    return None


def lookup_lcsc(lcsc_number: str) -> Optional[PartMetadata]:
    """
    Look up a part by LCSC number using the JLCPCB API.
    Same endpoint Bouni uses in kicad-jlcpcb-tools.
    """
    if not lcsc_number:
        return None

    # Normalize LCSC number
    lcsc_number = lcsc_number.strip().upper()
    if not lcsc_number.startswith("C"):
        lcsc_number = f"C{lcsc_number}"

    url = (
        f"https://cart.jlcpcb.com/shoppingCart/smtGood/"
        f"getComponentDetail?componentCode={lcsc_number}"
    )

    logger.info(f"Looking up LCSC part: {lcsc_number}")
    data = _make_request(url)

    if not data or not data.get("data"):
        logger.warning(f"No data returned for LCSC {lcsc_number}")
        return None

    part_data = data["data"]
    meta = PartMetadata(raw_data=part_data)

    meta.lcsc_part = lcsc_number
    meta.mpn = part_data.get("componentModelEn", "")
    meta.manufacturer = part_data.get("componentBrandEn", part_data.get("brandNameEn", ""))
    meta.description = part_data.get("describe", "")
    meta.package = part_data.get("componentSpecificationEn", "")
    meta.datasheet_url = part_data.get("dataManualUrl", "")
    meta.stock = part_data.get("stockCount", 0)
    meta.category = part_data.get("firstTypeNameEn", part_data.get("catalogName", ""))
    meta.subcategory = part_data.get("secondTypeNameEn", part_data.get("parentCatalogName", ""))

    # Extract all dynamic attributes (e.g. Voltage - Supply, Switch Circuit, Bandwidth, etc)
    attributes = part_data.get("attributes", [])
    if isinstance(attributes, list):
        for attr in attributes:
            name = attr.get("attribute_name_en", "")
            value = attr.get("attribute_value_name", "")
            if name and value:
                meta.extra_attributes[name] = value

    # Extract pricing from price list
    prices = part_data.get("prices", part_data.get("jlcPrices", []))
    if prices:
        # Get the price for smallest quantity
        try:
            if isinstance(prices, list) and len(prices) > 0:
                first_price = prices[0]
                if isinstance(first_price, dict):
                    meta.price = str(first_price.get("productPrice", ""))
                elif isinstance(first_price, (int, float)):
                    meta.price = str(first_price)
        except (IndexError, KeyError):
            pass

    logger.info(f"LCSC lookup success: {meta.mpn} ({meta.manufacturer})")
    return meta


def search_lcsc_by_mpn(mpn: str) -> Optional[PartMetadata]:
    """
    Search LCSC by manufacturer part number.
    Uses the JLCPCB search API.
    """
    if not mpn or len(mpn) < 3:
        return None

    # Try the search endpoint (POST requires JSON body now)
    search_url = (
        f"https://jlcpcb.com/api/overseas-pcb-order/v1/shoppingCart/"
        f"smtGood/selectSmtComponentList"
    )
    payload = {
        "keyword": mpn,
        "currentPage": 1,
        "pageSize": 5
    }

    logger.info(f"Searching LCSC for MPN: {mpn}")
    data = _make_request(search_url, payload=payload)

    if not data or not data.get("data"):
        # Fallback: try the simpler component detail search
        fallback_url = (
            f"https://cart.jlcpcb.com/shoppingCart/smtGood/"
            f"getComponentDetail?componentCode={quote(mpn)}"
        )
        data = _make_request(fallback_url)

    if not data or not data.get("data"):
        logger.info(f"No LCSC results for MPN: {mpn}")
        return None

    part_data = data["data"]

    # Handle list results
    if isinstance(part_data, dict) and "componentPageInfo" in part_data:
        records = part_data.get("componentPageInfo", {}).get("list", [])
        if records:
            # Use the first result's LCSC number for a detailed lookup
            # In the new POST JSON, it's called 'componentCode' usually
            first_lcsc = records[0].get("componentCode", "")
            if first_lcsc:
                return lookup_lcsc(first_lcsc)
    elif isinstance(part_data, dict) and part_data.get("componentCode"):
        return lookup_lcsc(part_data["componentCode"])

    return None


def extract_lcsc_from_properties(properties: dict) -> str:
    """Try to find an LCSC part number in component properties."""
    lcsc_keys = ["lcsc", "lcsc#", "lcsc_part", "jlcpcb", "jlc", "lcsc part", "lcsc part#"]

    for key, value in properties.items():
        if key.lower().strip() in lcsc_keys:
            return value.strip()

    # Search in all property values for LCSC-like pattern (C followed by digits)
    for value in properties.values():
        match = re.search(r'\bC(\d{4,})\b', str(value))
        if match:
            return f"C{match.group(1)}"

    return ""


def extract_digikey_from_properties(properties: dict) -> str:
    """Try to find a DigiKey part number in component properties."""
    dk_keys = ["digikey", "digikey#", "digi-key", "digikey_pn", "digi-key_pn", "dk"]

    for key, value in properties.items():
        if key.lower().strip().replace(" ", "_") in dk_keys:
            return value.strip()

    return ""


def enrich_component(component) -> dict:
    """
    Enrich a ComponentData with metadata from web lookups.
    Returns a dict of properties to add to the symbol.
    """
    enriched_props = {}

    # 1. Check if LCSC number is already in properties
    lcsc_num = extract_lcsc_from_properties(component.properties)
    digikey_num = extract_digikey_from_properties(component.properties)

    # 2. Try LCSC lookup
    meta = None
    if lcsc_num:
        meta = lookup_lcsc(lcsc_num)
    elif component.mpn:
        meta = search_lcsc_by_mpn(component.mpn)
    elif component.name:
        # Last resort: try the component name
        meta = search_lcsc_by_mpn(component.name)

    if meta:
        if meta.lcsc_part:
            enriched_props["LCSC"] = meta.lcsc_part
        if meta.mpn and not component.mpn:
            enriched_props["MPN"] = meta.mpn
        if meta.manufacturer and not component.manufacturer:
            enriched_props["Manufacturer"] = meta.manufacturer
        if meta.package:
            enriched_props["Package"] = meta.package
        if meta.price:
            enriched_props["Price"] = meta.price
        if meta.description and not component.description:
            enriched_props["Description"] = meta.description
        if meta.datasheet_url and not component.datasheet:
            enriched_props["Datasheet"] = meta.datasheet_url
            
        # Add all the extra JLCPCB attributes (Voltage, Speed, etc)
        if meta.extra_attributes:
            for attr_key, attr_val in meta.extra_attributes.items():
                if attr_key not in enriched_props and attr_key not in component.properties:
                    enriched_props[attr_key] = attr_val

    if digikey_num:
        enriched_props["DigiKey_PN"] = digikey_num

    logger.info(f"Enrichment found {len(enriched_props)} additional properties")
    return enriched_props
