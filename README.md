# Parks Daily Revenue JE Generator

Turns a "NA Spreadsheet" (Parks cash collector PDF) into a QBO-ready
journal entry CSV — same logic you've been applying by hand all of August.

## One-time setup

```bash
pip install pdfplumber --break-system-packages
```

## Single day

```bash
python3 parks_je.py "NA_Spreadsheet_Aug_01.pdf" --journal-no JJ3317
```

Output CSV lands in `/mnt/user-data/outputs/` by default (use `--output`
to change). It's ready to import into QBO as-is.

## A whole folder at once

```bash
python3 parks_je.py --batch /path/to/pdfs --journal-no JJ3317
```

Sorts files by the date in their filename and assigns JJ3317, JJ3318,
JJ3319... in order. If your real QBO sequence has gaps (like JJ3386 or
JJ3446 did this month), run those specific days separately with the
correct `--journal-no` instead of relying on batch auto-increment.

## The one thing it can't figure out on its own

Every so often a collector row is literally named "Sani" or "Sanistation"
but their dollars were typed into the regular **Camping Fee** columns
instead of the dedicated **Sani Gross/Net/GST** columns (this happened on
Aug 10). The script can't tell the difference between that and a genuine
camping collector named Sani — so it always prints the raw collector rows
above each entry. Skim that list; if you see a Sani/Firewood-named row
with $0.00 in the dedicated Sani/FW columns but real money in the regular
columns, rerun with:

```bash
python3 parks_je.py "NA_Spreadsheet_-_August_10.pdf" --journal-no JJ3326 \
    --manual-sani 322.86,16.14
```

(net, then GST — pulled straight off that collector's row). Same idea
for `--manual-firewood NET,GST`.

## What it posts

```
DR  1002 Petty Cash in safe          = Total Deposit
[DR 6036 Cash Short/Over]            = only if SHORT
    CR  3033 Camping                 = Net Camping Fees
    CR  2029 GST Charged on Sales    = Net GST (camping)
    [CR 3009 Sani Station]           = only if Sani $ present
    [CR 2029 GST Charged on Sales]   = Sani GST
    [CR 3008 Wood Sales]             = only if Firewood $ present
    [CR 2029 GST Charged on Sales]   = Firewood GST
[CR 6036 Cash Short/Over]            = only if OVER
```

Class/Location is tagged `0050-MANNING PARKS` by default (`--location`
to override). Every run prints the debit/credit totals and a balanced
YES/NO check before writing the file — always confirm it says YES.

## Verified against

Every Parks sheet from Aug 1–31 2026 (all 30 days), including the four
Sani-Station days, seven short/over days, and the one fold-into-camping
edge case — output matched the manually-built entries to the penny in
every case.
