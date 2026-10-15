# Castle Games — Riftbound daily Shopify price sync

This starter workflow checks TCGCSV's public Riftbound price feed daily and proposes updates to existing Shopify products. It does **not** change inventory, product status, titles, descriptions, images, or tags.

## Important commercial-use gate

TCGCSV is a public mirror of TCGplayer data, but that does not itself establish permission for commercial use. TCGplayer's published API terms restrict automated collection and certain third-party uses of its data. **Do not enable live updates until you have verified a clear legal basis or written permission covering your intended commercial use.**

The GitHub workflow is intentionally configured for dry-run mode. It will not write prices unless both `ENABLE_LIVE_UPDATES` and `COMMERCIAL_USE_CONFIRMED` are changed to `true` after the rights question is resolved.

## Condition pricing rules

The script applies these multipliers to the matching finish-specific TCGCSV base price (Market Price first, then Low Price fallback):

- Near Mint: 100%
- Lightly Played: 95%
- Moderately Played: 80%
- Heavily Played: 70%
- Damaged: 65%

TCGCSV does not provide separate market prices for every condition; these are the configured condition adjustments.

## What this version does

- Runs daily with GitHub Actions and can also be started manually.
- Generates a Shopify access token automatically using your Dev Dashboard app's Client ID and Client Secret.
- Reads TCGCSV category 89, downloads group products/prices, and prefers `marketPrice` and falls back to `lowPrice` when Market Price is missing or invalid.
- Matches conservatively using exact set/group tag + exact card-number tag + finish.
- Leaves the current Shopify price unchanged when the price is missing, ambiguous, or cannot be matched.
- Skips ambiguous matches instead of guessing.
- Only sends `id` and `price` to Shopify, so inventory is not modified.
- Starts in dry-run mode and prints proposed changes in the Actions log.

## Set up

1. Create a private GitHub repository, e.g. `castle-riftbound-price-sync`.
2. Upload these files while preserving the `.github/workflows/daily-price-sync.yml` path.
3. In Shopify Dev Dashboard, confirm the app version has `read_products` and `write_products` access scopes, and that the installed app has been approved for those scopes.
4. In GitHub, open **Settings → Secrets and variables → Actions → New repository secret** and add:
   - `SHOPIFY_STORE`: your full `your-store.myshopify.com` hostname, without `https://`.
   - `SHOPIFY_CLIENT_ID`: the Client ID from the app's Settings page.
   - `SHOPIFY_CLIENT_SECRET`: the Client Secret from the app's Settings page.
5. Run **Actions → Daily Riftbound Price Sync → Run workflow**. The workflow is dry-run by default. Review the log and verify set/number/finish matching before considering any live run.

## Important Shopify authentication limitation

Shopify's client credentials grant works only when the app and target store belong to the **same Shopify organization**. If the workflow reports `shop_not_permitted`, check that the app and store appear under the same organization in Dev Dashboard. App installation alone does not guarantee this.

## Catalog and matching limitations

The script supports Shopify variants with explicit **Condition** and **Foil** options. It uses the selected finish (Normal or Foil) and applies the configured condition multiplier. It will not turn a Normal price into a Foil price. If an option value is missing or unsupported, that variant is skipped.

Set names and numbering formats may differ between the catalog source and TCGCSV. Unmatched or ambiguous entries are intentionally skipped.

## Safety checks before live use

- Verify commercial-use permission for the pricing data.
- Test a small sample and inspect logs.
- Verify matching for every set in your catalog.
- Back up/export Shopify products before first live use.
- Only after commercial rights are verified, change both workflow environment values to `true`:
  - `ENABLE_LIVE_UPDATES`
  - `COMMERCIAL_USE_CONFIRMED`

## Documentation

- Shopify client credentials grant: https://shopify.dev/docs/apps/build/authentication-authorization/client-credentials-grant
- Shopify GraphQL Admin API: https://shopify.dev/docs/api/admin-graphql/latest
- TCGCSV documentation: https://tcgcsv.com/docs
- TCGplayer API terms: https://help.tcgplayer.com/hc/en-us/articles/360061115874-TCGplayer-API-Terms-Conditions

This project is not affiliated with or endorsed by TCGplayer, Riot Games, or Shopify.
