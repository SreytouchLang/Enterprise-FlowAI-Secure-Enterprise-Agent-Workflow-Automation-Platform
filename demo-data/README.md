# Synthetic demonstration fixtures

Every person, business, property, invoice and agreement is fictional. The property state `XX` and postal code `00000` are intentionally non-real examples. Historical workflow records created by `app.seed` are explicitly demonstration history, not measured production activity.

`manifest.json` records expected invoice values and document metadata. The reproducible generator is `generate.py`. `make seed` imports these fixtures through the application seeder. The dataset includes 20 PDF invoices, 10 HR policies, 10 legal agreements and 30 properties with multiple source records. Ten properties deliberately conflict on bedroom counts, ten are missing bedrooms, and ten are internally consistent. Invoice amounts use Decimal arithmetic.

All login credentials published in the development realm are public fixture values. Never import these users or files into a real employee-data environment.
