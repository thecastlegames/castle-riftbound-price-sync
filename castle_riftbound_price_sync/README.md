# Castle Games — Riftbound daily Shopify price sync

This starter workflow checks TCGCSV's public Riftbound price feed daily and proposes updates to existing Shopify products. It does **not** change inventory, product status, titles, descriptions, images, or tags.

## Important commercial-use gate

TCGCSV describes itself as a public mirror of TCGplayer data, but that does not itself establish permission to use the data commercially. TCGplayer's published API terms restrict automated collection and use of its content and also restrict obtaining data from third parties that collected it using automated means. **Do not enable live updates until you have written confirmation or another clear legal basis that covers your intended commercial use.**

The GitHub workflow is intentionally configured for dry-run mode. It will not write prices unless both `ENABLE_LIVE_UPDATES` and `COMMERCIAL_USE_CONFIRMED` are changed to `true` in the workflow after the rights question is resolved.

## What this version does

- Runs daily with GitHub Actions and can also be started manually.
- Reads TCGCSV category 89, downloads group products/prices, and uses `marketPrice`.
- Matches conservatively using exact set/group tag + exact card-number tag + finish.
- Leaves the current Shopify price unchanged when the price is missing, ambiguous, or cannot be matched.
- Skips ambiguous matches instead of guessing.
- Only sends `id` and `price` to Shopify, so inventory is not modified.
- Starts in dry-run mode and prints proposed changes in the Actions log.

## Important catalog limitation

The CSV imported earlier contains one default Shopify variant per card and does not appear to have separate foil variants. This script therefore treats those default variants as **Normal** unless the product/variant title or tags explicitly say Foil/Holofoil. It will not turn a Normal price into a Foil price. To price foil copies independently, create distinct foil products or explicit Normal/Foil variants and ensure the variant title/options identify the finish.

## Set up

1. Create a private GitHub repository, e.g. `castle-riftbound-price-sync`.
2. Upload these files while preserving the `.github/workflows/daily-price-sync.yml` path.
3. In Shopify Admin, create a custom app with read-products and write-products access. Install it and copy the Admin API access token. Shopify's app/token UI changes over time; do not share the token in chat or commit it to Git.
4. In GitHub, open **Settings → Secrets and variables → Actions → New repository secret** and add:
   - `SHOPIFY_STORE`: your `your-store.myshopify.com` hostname only (no `https://`).
   - `SHOPIFY_ADMIN_TOKEN`: the Admin API access token.
5. Run **Actions → Daily Riftbound Price Sync → Run workflow**. The workflow is dry-run by default. Review the log and verify set/number/finish matching before considering any live run.
6. Verify commercial-use permission for the pricing data. Until then, leave both safety flags set to `false`.

## Safety checks before live use

- Confirm the Shopify custom app has only the required product scopes and is installed.
- Test a small sample and inspect logs.
- Verify matching for every set in your catalog. Set names and numbering formats may differ between the catalog source and TCGCSV; unmatched or ambiguous entries are intentionally skipped.
- Back up/export Shopify products before first live use.
- Only after commercial rights are verified, change both workflow environment values to `true`:
  - `ENABLE_LIVE_UPDATES`
  - `COMMERCIAL_USE_CONFIRMED`

## Data source

TCGCSV documentation: https://tcgcsv.com/docs  
TCGplayer API terms: https://help.tcgplayer.com/hc/en-us/articles/360061115874-TCGplayer-API-Terms-Conditions  
Shopify GraphQL Admin API: https://shopify.dev/docs/api/admin-graphql/latest

This project is not affiliated with or endorsed by TCGplayer, Riot Games, or Shopify.
