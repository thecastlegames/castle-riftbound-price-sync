#!/usr/bin/env python3
"""
Daily TCGCSV -> Shopify Riftbound price sync.

Safety:
- Dry-run is the default.
- Live updates require BOTH ENABLE_LIVE_UPDATES=true and
  COMMERCIAL_USE_CONFIRMED=true.
- Do not enable live updates until you have confirmed that your intended
  commercial use of the pricing data is permitted.
- Only updates prices; it never writes inventory, product status, or titles.
"""
import json
import os
import re
import sys
import time
import unicodedata
from decimal import Decimal, InvalidOperation
from urllib.parse import urljoin

import requests

TCGCSV_ROOT = "https://tcgcsv.com/tcgplayer"
CATEGORY_ID = os.getenv("TCGCSV_CATEGORY_ID", "89")
SHOPIFY_STORE = os.environ.get("SHOPIFY_STORE", "").strip().replace("https://", "").rstrip("/")
SHOPIFY_CLIENT_ID = os.environ.get("SHOPIFY_CLIENT_ID", "").strip()
SHOPIFY_CLIENT_SECRET = os.environ.get("SHOPIFY_CLIENT_SECRET", "").strip()
SHOPIFY_API_VERSION = os.getenv("SHOPIFY_API_VERSION", "2026-04")
SHOPIFY_TOKEN = None
ENABLE_LIVE = os.getenv("ENABLE_LIVE_UPDATES", "false").lower() == "true"
COMMERCIAL_CONFIRMED = os.getenv("COMMERCIAL_USE_CONFIRMED", "false").lower() == "true"
USER_AGENT = os.getenv("TCGCSV_USER_AGENT", "CastleGamesRiftboundPriceSync/1.0 (contact: store owner)")
DRY_RUN = not (ENABLE_LIVE and COMMERCIAL_CONFIRMED)

session = requests.Session()
session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})


def norm(value):
    value = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def get_json(url):
    response = session.get(url, timeout=45)
    response.raise_for_status()
    return response.json()


def get_tcgcsv_catalog():
    groups_url = f"{TCGCSV_ROOT}/{CATEGORY_ID}/groups"
    groups_payload = get_json(groups_url)
    groups = groups_payload.get("results", groups_payload if isinstance(groups_payload, list) else [])
    products_by_key = {}
    prices_by_product = {}
    product_count = 0

    for group in groups:
        group_id = group.get("groupId")
        group_name = group.get("name") or group.get("groupName") or ""
        if not group_id or not group_name:
            continue

        base = f"{TCGCSV_ROOT}/{CATEGORY_ID}/{group_id}/"
        try:
            products_payload = get_json(urljoin(base, "products"))
            prices_payload = get_json(urljoin(base, "prices"))
        except requests.RequestException as exc:
            print(f"WARN: Could not fetch group {group_name!r} ({group_id}): {exc}")
            continue

        products = products_payload.get("results", [])
        prices = prices_payload.get("results", [])
        prices_by_id = {}
        for price in prices:
            subtype = (price.get("subTypeName") or "Normal").strip().lower()
            # Prefer Market Price. If it is missing, invalid, or non-positive,
            # fall back to Low Price for the same product and finish.
            market_amount = price.get("marketPrice")
            low_amount = price.get("lowPrice")
            amount = None
            source = None
            try:
                market_value = Decimal(str(market_amount)) if market_amount is not None else None
                if market_value is not None and market_value > 0:
                    amount, source = market_value, "market"
            except InvalidOperation:
                pass
            if amount is None:
                try:
                    low_value = Decimal(str(low_amount)) if low_amount is not None else None
                    if low_value is not None and low_value > 0:
                        amount, source = low_value, "low"
                except InvalidOperation:
                    pass
            if amount is not None:
                prices_by_id[(str(price.get("productId")), subtype)] = (amount, source)

        for product in products:
            product_id = str(product.get("productId", ""))
            if not product_id:
                continue
            extended = {
                str(item.get("name", "")).strip().lower(): str(item.get("value", "")).strip()
                for item in product.get("extendedData", []) if isinstance(item, dict)
            }
            number = extended.get("number", "")
            # Ignore sealed products; they normally have no card number.
            if not number:
                continue
            for subtype in ("normal", "foil"):
                price_record = prices_by_id.get((product_id, subtype))
                if price_record is None:
                    continue
                price, price_source = price_record
                if price <= 0:
                    continue
                key = (norm(group_name), norm(number), subtype)
                # Do not overwrite duplicate keys silently; mark ambiguous.
                if key in products_by_key:
                    products_by_key[key] = None
                else:
                    products_by_key[key] = {
                        "group": group_name,
                        "number": number,
                        "subtype": subtype,
                        "price": price,
                        "price_source": price_source,
                        "product_name": product.get("name", ""),
                        "product_id": product_id,
                    }
            product_count += 1
        time.sleep(0.25)

    print(f"TCGCSV groups checked: {len(groups)}; card products seen: {product_count}; price keys: {len(products_by_key)}", flush=True)
    return products_by_key


def get_shopify_access_token():
    """Generate a short-lived token using Shopify Dev Dashboard credentials."""
    if not SHOPIFY_STORE or not SHOPIFY_CLIENT_ID or not SHOPIFY_CLIENT_SECRET:
        raise RuntimeError("Set SHOPIFY_STORE, SHOPIFY_CLIENT_ID, and SHOPIFY_CLIENT_SECRET.")
    url = f"https://{SHOPIFY_STORE}/admin/oauth/access_token"
    response = requests.post(
        url,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "grant_type": "client_credentials",
            "client_id": SHOPIFY_CLIENT_ID,
            "client_secret": SHOPIFY_CLIENT_SECRET,
        },
        timeout=45,
    )
    response.raise_for_status()
    payload = response.json()
    token = payload.get("access_token")
    if not token:
        raise RuntimeError(f"Shopify did not return an access token: {payload}")
    print(f"Shopify token generated; expires in {payload.get('expires_in', 'unknown')} seconds.", flush=True)
    return token


def shopify_graphql(query, variables=None):
    global SHOPIFY_TOKEN
    if not SHOPIFY_TOKEN:
        SHOPIFY_TOKEN = get_shopify_access_token()
    url = f"https://{SHOPIFY_STORE}/admin/api/{SHOPIFY_API_VERSION}/graphql.json"
    response = requests.post(
        url,
        headers={
            "X-Shopify-Access-Token": SHOPIFY_TOKEN,
            "Content-Type": "application/json",
            "User-Agent": "CastleGamesRiftboundPriceSync/1.0",
        },
        json={"query": query, "variables": variables or {}},
        timeout=60,
    )
    response.raise_for_status()
    data = response.json()
    if data.get("errors"):
        raise RuntimeError(json.dumps(data["errors"], indent=2))
    return data["data"]


def get_shopify_riftbound_products():
    query = """
    query Products($cursor: String) {
      products(first: 100, after: $cursor, query: "tag:Riftbound") {
        edges {
          cursor
          node {
            id
            title
            tags
            variants(first: 20) {
              edges {
                node { id title sku price selectedOptions { name value } }
              }
            }
          }
        }
        pageInfo { hasNextPage endCursor }
      }
    }
    """
    cursor = None
    output = []
    while True:
        data = shopify_graphql(query, {"cursor": cursor})["products"]
        for edge in data["edges"]:
            product = edge["node"]
            for variant_edge in product["variants"]["edges"]:
                variant = variant_edge["node"]
                output.append({
                    "product_id": product["id"],
                    "title": product["title"],
                    "tags": product["tags"],
                    "variant_id": variant["id"],
                    "variant_title": variant["title"],
                    "selected_options": variant.get("selectedOptions") or [],
                    "sku": variant.get("sku") or "",
                    "current_price": variant.get("price"),
                })
        if not data["pageInfo"]["hasNextPage"]:
            break
        cursor = data["pageInfo"]["endCursor"]
    return output


def card_number_from_tags(tags):
    for tag in tags:
        if tag.lower().startswith("card number:"):
            return tag.split(":", 1)[1].strip()
    return ""


def set_name_from_tags(tags):
    # In the generated CSV, the set name is one of the tags, e.g. Radiance.
    # We match only if exactly one tag maps to a TCGCSV group name.
    return [tag.strip() for tag in tags if tag.strip()]


CONDITION_MULTIPLIERS = {
    "near mint": Decimal("1.00"),
    "lightly played": Decimal("0.95"),
    "moderately played": Decimal("0.80"),
    "heavily played": Decimal("0.70"),
    "damaged": Decimal("0.65"),
}


def variant_pricing_options(item):
    """Return (TCGCSV finish, condition multiplier, error). Never infer foil from card name."""
    options = {str(opt.get("name", "")).strip().lower(): str(opt.get("value", "")).strip().lower()
               for opt in item.get("selected_options", [])}
    # Support the new two-option Shopify structure only; default/unknown options are not safe to price.
    condition = options.get("condition", "")
    foil = options.get("foil", "")
    if condition not in CONDITION_MULTIPLIERS:
        return None, None, f"unsupported or missing condition option: {condition!r}"
    if foil in ("non-foil", "non foil", "normal"):
        subtype = "normal"
    elif foil in ("foil", "holofoil", "holo foil"):
        subtype = "foil"
    else:
        return None, None, f"unsupported or missing foil option: {foil!r}"
    return subtype, CONDITION_MULTIPLIERS[condition], None


def main():
    if not SHOPIFY_STORE or not SHOPIFY_CLIENT_ID or not SHOPIFY_CLIENT_SECRET:
        print("ERROR: Set SHOPIFY_STORE, SHOPIFY_CLIENT_ID, and SHOPIFY_CLIENT_SECRET.", flush=True)
        sys.exit(2)

    print("Mode:", "DRY RUN (no Shopify writes)" if DRY_RUN else "LIVE PRICE UPDATES", flush=True)
    if not (ENABLE_LIVE and COMMERCIAL_CONFIRMED):
        print("Safety gate: live updates are disabled. Set both flags only after verifying commercial data rights.")

    tcg = get_tcgcsv_catalog()
    groups_by_norm = {}
    for key, entry in tcg.items():
        group_norm, number_norm, subtype = key
        groups_by_norm.setdefault(group_norm, set()).add(group_norm)

    shopify_products = get_shopify_riftbound_products()
    print(f"Shopify variants checked: {len(shopify_products)}", flush=True)
    updates = []
    unchanged = 0
    no_card_number = 0
    set_not_identified = 0
    no_price_match = 0
    ambiguous = 0
    unmatched_samples = []

    for item in shopify_products:
        number = card_number_from_tags(item["tags"])
        if not number:
            no_card_number += 1
            if len(unmatched_samples) < 50:
                unmatched_samples.append((item, "missing Card Number tag"))
            continue
        number_norm = norm(number)
        subtype, condition_multiplier, option_error = variant_pricing_options(item)
        if option_error:
            no_price_match += 1
            if len(unmatched_samples) < 50:
                unmatched_samples.append((item, option_error))
            continue

        # Require exact card number, set-name, and finish match. Avoid fuzzy title matching.
        set_candidates = [tag for tag in set_name_from_tags(item["tags"]) if norm(tag) in {k[0] for k in tcg.keys()}]
        if len(set_candidates) != 1:
            set_not_identified += 1
            if len(unmatched_samples) < 50:
                unmatched_samples.append((item, f"expected exactly one set tag match; found {len(set_candidates)}"))
            continue
        key = (norm(set_candidates[0]), number_norm, subtype)
        if key not in tcg:
            # Do not fall back from Foil to Normal or vice versa.
            no_price_match += 1
            if len(unmatched_samples) < 50:
                unmatched_samples.append((item, f"no TCGCSV price key for set={set_candidates[0]!r}, number={number!r}, subtype={subtype}"))
            continue
        entry = tcg[key]
        if entry is None:
            ambiguous += 1
            continue
        try:
            current = Decimal(str(item["current_price"]))
        except (InvalidOperation, TypeError):
            current = None
        # Use finish-specific market price when available; otherwise the catalog
        # entry is based on Low Price. Apply the chosen condition multiplier.
        target = (entry["price"] * condition_multiplier).quantize(Decimal("0.01"))
        if current == target:
            unchanged += 1
            continue
        updates.append((item, target, entry))

    unmatched = no_card_number + set_not_identified + no_price_match
    print(f"Matched price updates: {len(updates)}; unchanged: {unchanged}; unmatched: {unmatched}; ambiguous skipped: {ambiguous}", flush=True)
    print("Base price priority: Market Price first; Low Price fallback when Market Price is unavailable.", flush=True)
    print("Condition pricing: Near Mint 100%; Lightly Played 95%; Moderately Played 80%; Heavily Played 70%; Damaged 65%", flush=True)
    print(f"Unmatched reasons: missing card number={no_card_number}; set not identified={set_not_identified}; no exact TCGCSV price key={no_price_match}", flush=True)
    if unmatched_samples:
        print(f"First {len(unmatched_samples)} unmatched examples (SKU | product | reason):", flush=True)
        for sample_item, reason in unmatched_samples:
            print(f"[UNMATCHED] {sample_item['sku']} | {sample_item['title']} | {reason}", flush=True)
    for item, target, entry in updates[:100]:
        print(f"{'[DRY RUN] ' if DRY_RUN else ''}{item['sku']} | {item['title']} | {entry['group']} #{entry['number']} [{entry['subtype']}; base={entry['price_source']}] ${item['current_price']} -> ${target}")
    if len(updates) > 100:
        print(f"... plus {len(updates) - 100} additional proposed updates.")

    if DRY_RUN:
        print("Dry run complete. No Shopify data was changed.", flush=True)
        return

    mutation = """
    mutation UpdateVariantPrice($productId: ID!, $variants: [ProductVariantsBulkInput!]!) {
      productVariantsBulkUpdate(productId: $productId, variants: $variants) {
        productVariants { id price }
        userErrors { field message }
      }
    }
    """
    # Batch by parent product. Only pass variant id + price; inventory is untouched.
    by_product = {}
    for item, target, entry in updates:
        by_product.setdefault(item["product_id"], []).append({
            "id": item["variant_id"],
            "price": str(target),
        })

    success = 0
    for product_id, variants in by_product.items():
        result = shopify_graphql(mutation, {"productId": product_id, "variants": variants})
        payload = result["productVariantsBulkUpdate"]
        if payload.get("userErrors"):
            print("ERROR updating", product_id, json.dumps(payload["userErrors"]))
        else:
            success += len(payload.get("productVariants", []))
        time.sleep(0.25)

    print(f"Live sync complete. Variants updated: {success}")


if __name__ == "__main__":
    main()
