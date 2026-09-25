#!/usr/bin/env python3
"""
Manning Park Resort — Parks Daily Revenue Journal Entry Generator
====================================================================

Reads a "NA Spreadsheet" (Parks cash collector summary) PDF and produces
a QBO-ready journal entry CSV, following the exact posting logic used
for the manual Aug 2026 entries:

  DR  1002 Petty Cash in safe          = Total Deposit (actual cash/POS turned in)
  [DR 6036 Cash Short/Over]            = only if deposit is SHORT vs required
      CR  3033 Camping                 = Sub Total "Net Camping Fees"
      CR  2029 GST Charged on Sales    = Sub Total "Net GST" (camping)
      [CR 3009 Sani Station]           = only if Sani Gross/Net/GST columns are non-zero
      [CR 2029 GST Charged on Sales]   = Sani GST, if Sani used
      [CR 3008 Wood Sales]             = only if Firewood columns are non-zero
      [CR 2029 GST Charged on Sales]   = FW GST, if Firewood used
  [CR 6036 Cash Short/Over]            = only if deposit is OVER vs required

Key convention: the "Sub Total" row's Net Camping/GST/Firewood/Sani
columns already reflect only genuine dedicated-column Sani/Firewood
activity. When a collector's Sani/Firewood proceeds were entered into
the regular Camping Fee columns instead of the dedicated Sani/Firewood
columns (happens occasionally — e.g. a row literally named "Sani" or
"Sanistation" with $0.00 in every dedicated Sani column), this script
CANNOT detect that by itself — a human must eyeball the collector rows
and use --manual-sani / --manual-firewood to override. The script always
prints the raw collector rows so you can sanity-check this in one glance.

USAGE
-----
    python3 parks_je.py <pdf_path> --journal-no JJ3448 [options]

    Required:
      pdf_path                 Path to the NA Spreadsheet PDF
      --journal-no             QBO journal number, e.g. JJ3448

    Optional:
      --output DIR             Output directory (default: /mnt/user-data/outputs)
      --location "0050-MANNING PARKS"   Location/Class tag (default matches convention)
      --manual-sani NET,GST    Override: force these Sani amounts (net, gst) onto
                                the entry, pulling them OUT of the Camping line.
                                Use when a "Sani"-named collector's $ landed in the
                                Camping columns instead of the dedicated Sani columns.
      --manual-firewood NET,GST  Same idea, for Firewood.
      --date YYYY-MM-DD         Override the journal date (default: parsed from filename,
                                 falls back to today if not found)

EXAMPLES
--------
    # Standard day, no overrides needed
    python3 parks_je.py "NA_Spreadsheet_Aug_01.pdf" --journal-no JJ3317

    # A "Sani" collector's money is sitting in the Camping columns (dedicated
    # Sani columns show 0.00) — pull $322.86 net / $16.14 GST out into Sani
    python3 parks_je.py "NA_Spreadsheet_-_August_10.pdf" --journal-no JJ3326 \\
        --manual-sani 322.86,16.14

Run with --batch to process every PDF in a folder in one shot (still prints
each day's collector rows so you can catch the manual-override cases).
"""

import argparse
import csv
import os
import re
import sys
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP

try:
    import pdfplumber
except ImportError:
    sys.exit("Missing dependency. Run: pip install pdfplumber --break-system-packages")


# ---------------------------------------------------------------------------
# GL account mapping — edit here if the chart of accounts changes
# ---------------------------------------------------------------------------
ACCT_PETTY_CASH = "1002 Petty Cash in safe"
ACCT_CAMPING = "3033 Camping"
ACCT_GST = "2029 GST Charged on Sales"
ACCT_SANI = "3009 Sani Station"
ACCT_FIREWOOD = "3008 Wood Sales"
ACCT_SHORT_OVER = "6036 Cash Short/Over"

DEFAULT_LOCATION = "0050-MANNING PARKS"


def money(x) -> Decimal:
    """Parse a dollar string like '1,234.56' or '-2.00' into Decimal."""
    if x is None:
        return Decimal("0.00")
    s = str(x).replace(",", "").replace("$", "").strip()
    if s in ("", "-"):
        return Decimal("0.00")
    try:
        return Decimal(s).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except Exception:
        return Decimal("0.00")


def extract_text(pdf_path: str) -> str:
    with pdfplumber.open(pdf_path) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)


def parse_sheet(text: str) -> dict:
    """
    Pull the figures we actually need off the summary lines:
        Sub Total <gross cash> <gross resv> <cash2nd> <resv2nd> <refunds>
                  <net camping> <net gst> <total resv> <fw> <fw net> <fw gst>
                  <sani gross> <sani net> <sani gst> <pos cad> <us$> <over&short>
        Total Deposit <amount>
        DEPOSIT REQUIRED <amount>
        DIFFERENCE: <amount> [OVER|UNDER]
    Column count in "Sub Total" varies slightly across sheets (blank cells
    sometimes collapse), so we anchor on DEPOSIT REQUIRED / Total Deposit /
    DIFFERENCE lines, which are always present and unambiguous, and parse
    Net Camping / Net GST / Sani Net / Sani GST / FW Net / FW GST off the
    Sub Total row using labeled column positions where possible, falling
    back to a positional parse.
    """
    result = {}

    # --- Total Deposit (= actual cash/POS turned in = our Petty Cash debit)
    m = re.search(r"Total Deposit\s+([\d,]+\.\d{2})", text)
    if not m:
        raise ValueError("Could not find 'Total Deposit' line in PDF")
    result["total_deposit"] = money(m.group(1))

    # --- DEPOSIT REQUIRED (= net camping + gst + sani net + sani gst + fw net + fw gst)
    m = re.search(r"DEPOSIT REQUIRED\s+([\d,]+\.\d{2})", text)
    if not m:
        raise ValueError("Could not find 'DEPOSIT REQUIRED' line in PDF")
    result["deposit_required"] = money(m.group(1))

    # --- DIFFERENCE (signed; OVER = actual > required, UNDER = actual < required)
    m = re.search(r"DIFFERENCE:\s*(-?[\d,]+\.\d{2})\s*(OVER|UNDER)?", text, re.IGNORECASE)
    if m:
        diff = money(m.group(1))
        tag = (m.group(2) or "").upper()
        # Normalize sign: positive = OVER, negative = UNDER
        if tag == "UNDER" and diff > 0:
            diff = -diff
        elif tag == "OVER" and diff < 0:
            diff = -diff
        result["difference"] = diff
    else:
        result["difference"] = result["total_deposit"] - result["deposit_required"]

    # --- Sub Total row: grab every number on that line
    m = re.search(r"Sub Total\s+((?:-?[\d,]+\.\d{2}\s*)+)", text)
    if not m:
        raise ValueError("Could not find 'Sub Total' line in PDF")
    nums = [money(x) for x in m.group(1).split()]

    # Verified column order for the "Sub Total" row, confirmed against
    # every known sheet (Aug 1-31 2026), always 18 numeric tokens:
    #   0  gross_cash_fees
    #   1  (blank/0 filler — Cash 2nd Vehicles)
    #   2  gross_reservations
    #   3  (blank/0 filler — Resvn 2nd Vehicles)
    #   4  (blank/0 filler — Refunds)
    #   5  net_camping           <- Net Camping Fees
    #   6  net_gst               <- Net GST (on camping)
    #   7  total_reservation     (not posted)
    #   8  firewood_gross
    #   9  fw_net
    #   10 fw_gst
    #   11 sani_gross
    #   12 sani_net
    #   13 sani_gst
    #   14 us_dollar
    #   15 pos_cad               <- also equals Total Deposit
    #   16 (blank/0 filler)
    #   17 over_short
    labels_18 = [
        "gross_cash_fees", "_f1", "gross_reservations", "_f2", "_f3",
        "net_camping", "net_gst", "total_reservation", "firewood_gross", "fw_net", "fw_gst",
        "sani_gross", "sani_net", "sani_gst", "us_dollar", "pos_cad", "_f5",
        "over_short",
    ]

    parsed = {}
    if len(nums) == 18:
        parsed = dict(zip(labels_18, nums))
    else:
        # Layout drifted from every sheet seen so far — don't guess silently.
        print(f"  [!] Sub Total column count = {len(nums)} (expected 18) — "
              f"parsing may be WRONG. Verify every figure against the source PDF "
              f"before importing this entry.")
        # Best-effort: pad/truncate against the known label order so the
        # script still produces *something* to eyeball, clearly flagged above.
        padded = (nums + [Decimal("0.00")] * len(labels_18))[:len(labels_18)]
        parsed = dict(zip(labels_18, padded))

    # keep only the fields build_je_rows() actually needs
    for key in ("net_camping", "net_gst", "sani_gross", "sani_net", "sani_gst",
                "firewood_gross", "fw_net", "fw_gst"):
        result[key] = parsed.get(key, Decimal("0.00"))

    return result


def build_je_rows(journal_no: str, journal_date: str, journal_date_human: str,
                   location: str, figures: dict, manual_sani=None, manual_firewood=None):
    """
    Returns list of row dicts for the CSV, following the exact template
    used in the manual entries (JJ3317 .. JJ3448).
    """
    net_camping = figures["net_camping"]
    net_gst_camping = figures["net_gst"]
    sani_net = figures["sani_net"]
    sani_gst = figures["sani_gst"]
    fw_net = figures["fw_net"]
    fw_gst = figures["fw_gst"]
    total_deposit = figures["total_deposit"]
    difference = figures["difference"]  # positive = OVER, negative = UNDER

    # Manual overrides: pull sani/firewood dollars OUT of the camping bucket
    # (used when a "Sani"/"Sanistation" collector's takings were entered into
    # the regular Camping Fee columns rather than the dedicated Sani columns)
    if manual_sani is not None:
        m_net, m_gst = manual_sani
        net_camping -= m_net
        net_gst_camping -= m_gst
        sani_net = m_net
        sani_gst = m_gst

    if manual_firewood is not None:
        m_net, m_gst = manual_firewood
        net_camping -= m_net
        net_gst_camping -= m_gst
        fw_net = m_net
        fw_gst = m_gst

    memo = f"Parks Daily Revenue {journal_date_human}"

    rows = []

    def add(account, debit=None, credit=None):
        rows.append({
            "*JournalNo": journal_no,
            "*JournalDate": journal_date if not rows else "",
            "Memo": memo if not rows else "",
            "*AccountName": account,
            "Debits": f"{debit:.2f}" if debit is not None else "",
            "Credits": f"{credit:.2f}" if credit is not None else "",
            "Description": memo,
            "Name": "",
            "Location": "",
            "Class": location,
        })

    # 1. Petty Cash debit = actual total deposit
    add(ACCT_PETTY_CASH, debit=total_deposit)

    # 2. If cash is SHORT (difference negative), debit Cash Short/Over
    if difference < 0:
        add(ACCT_SHORT_OVER, debit=abs(difference))

    # 3. Camping revenue + GST (always present if non-zero)
    if net_camping != 0:
        add(ACCT_CAMPING, credit=net_camping)
    if net_gst_camping != 0:
        add(ACCT_GST, credit=net_gst_camping)

    # 4. Sani Station (only if non-zero)
    if sani_net != 0:
        add(ACCT_SANI, credit=sani_net)
    if sani_gst != 0:
        add(ACCT_GST, credit=sani_gst)

    # 5. Firewood (only if non-zero)
    if fw_net != 0:
        add(ACCT_FIREWOOD, credit=fw_net)
    if fw_gst != 0:
        add(ACCT_GST, credit=fw_gst)

    # 6. If cash is OVER (difference positive), credit Cash Short/Over
    if difference > 0:
        add(ACCT_SHORT_OVER, credit=difference)

    return rows


def write_csv(rows, out_path):
    fieldnames = ["*JournalNo", "*JournalDate", "Memo", "*AccountName",
                  "Debits", "Credits", "Description", "Name", "Location", "Class"]
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, lineterminator="\r\n")
        w.writeheader()
        w.writerows(rows)


def check_balance(rows):
    debits = sum(Decimal(r["Debits"]) for r in rows if r["Debits"])
    credits = sum(Decimal(r["Credits"]) for r in rows if r["Credits"])
    return debits, credits, (debits - credits) == 0


def guess_date_from_filename(pdf_path: str, year_hint: int = None):
    """
    Try to pull a date out of filenames like:
      NA_Spreadsheet_Aug_01.pdf, NA_Spreadsheet_-_August_27.pdf,
      NA_Spreadsheet_August_25th.pdf, NA_Spreadsheet_-_August_9.pdf
    Returns a date object, or None if it can't confidently parse one.
    """
    name = os.path.basename(pdf_path)
    months = {
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
        "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    }
    m = re.search(r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)"
                  r"[a-z]*[_\-\s]+0?(\d{1,2})(?:st|nd|rd|th)?(?:[_\-\.\s]|$)",
                  name, re.IGNORECASE)
    if not m:
        return None
    month = months[m.group(1)[:3].lower()]
    day = int(m.group(2))
    year = year_hint or date.today().year
    try:
        return date(year, month, day)
    except ValueError:
        return None


def print_collector_preview(text: str):
    """
    Print the raw collector-row region so a human can eyeball for
    'Sani'/'Sanistation'/'Firewood'-named rows sitting in the wrong columns
    (the one thing this script cannot verify automatically).
    """
    print("  --- Collector rows (for manual Sani/Firewood sanity check) ---")
    lines = text.splitlines()
    started = False
    for line in lines:
        if line.strip().startswith("COLLECTORS NAME") or re.match(r"^[A-Za-z]", line.strip()):
            started = True
        if started:
            if line.strip().startswith("Sub Total"):
                break
            if line.strip() and not line.strip().startswith(("Gross", "COLLECTORS")):
                print(f"    {line.strip()}")
    print("  ----------------------------------------------------------")


def process_one(pdf_path, journal_no, location, output_dir,
                 manual_sani=None, manual_firewood=None, date_override=None,
                 show_preview=True):
    print(f"\n>> {os.path.basename(pdf_path)}  (Journal No: {journal_no})")
    text = extract_text(pdf_path)

    if show_preview:
        print_collector_preview(text)

    figures = parse_sheet(text)

    if date_override:
        jdate = datetime.strptime(date_override, "%Y-%m-%d").date()
    else:
        jdate = guess_date_from_filename(pdf_path) or date.today()
    jdate_str = jdate.strftime("%d-%m-%Y")
    jdate_human = jdate.strftime("%b %d %Y").replace(" 0", " ")  # "Aug 01" -> "Aug 1"

    rows = build_je_rows(journal_no, jdate_str, jdate_human, location, figures,
                          manual_sani=manual_sani, manual_firewood=manual_firewood)

    debits, credits, balanced = check_balance(rows)

    print(f"   Total Deposit: ${figures['total_deposit']}   "
          f"Deposit Required: ${figures['deposit_required']}   "
          f"Difference: ${figures['difference']}")
    print(f"   Debits: ${debits}   Credits: ${credits}   "
          f"Balanced: {'YES' if balanced else 'NO — CHECK MANUALLY'}")

    os.makedirs(output_dir, exist_ok=True)
    out_name = f"{journal_no}_Parks_{jdate.isoformat()}.csv"
    out_path = os.path.join(output_dir, out_name)
    write_csv(rows, out_path)
    print(f"   -> {out_path}")

    return out_path, balanced


def parse_manual_pair(s):
    if s is None:
        return None
    parts = s.split(",")
    if len(parts) != 2:
        raise argparse.ArgumentTypeError("Expected format NET,GST e.g. 322.86,16.14")
    return money(parts[0]), money(parts[1])


def main():
    ap = argparse.ArgumentParser(
        description="Generate a QBO-ready Parks Daily Revenue journal entry CSV from a NA Spreadsheet PDF.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("pdf_path", nargs="?", help="Path to the NA Spreadsheet PDF")
    ap.add_argument("--journal-no", help="QBO journal number, e.g. JJ3448")
    ap.add_argument("--output", default="/mnt/user-data/outputs", help="Output directory")
    ap.add_argument("--location", default=DEFAULT_LOCATION, help="Location/Class value")
    ap.add_argument("--manual-sani", type=parse_manual_pair, default=None,
                     help="Override Sani NET,GST (pulls these $ out of Camping)")
    ap.add_argument("--manual-firewood", type=parse_manual_pair, default=None,
                     help="Override Firewood NET,GST (pulls these $ out of Camping)")
    ap.add_argument("--date", dest="date_override", default=None,
                     help="Override journal date as YYYY-MM-DD")
    ap.add_argument("--batch", metavar="FOLDER",
                     help="Process every PDF in FOLDER. Journal numbers auto-increment "
                          "from --journal-no (e.g. JJ3317, JJ3318, ...). Sorts files by "
                          "date parsed from filename.")
    args = ap.parse_args()

    if args.batch:
        if not args.journal_no:
            sys.exit("--batch requires a starting --journal-no")
        pdfs = [os.path.join(args.batch, f) for f in os.listdir(args.batch)
                if f.lower().endswith(".pdf")]
        # sort by parsed date where possible
        pdfs.sort(key=lambda p: guess_date_from_filename(p) or date.max)

        # parse starting journal number into prefix + integer
        m = re.match(r"([A-Za-z]+)(\d+)$", args.journal_no)
        if not m:
            sys.exit("--journal-no must look like JJ3317 for --batch auto-increment")
        prefix, start_num = m.group(1), int(m.group(2))

        results = []
        for i, pdf in enumerate(pdfs):
            jno = f"{prefix}{start_num + i}"
            try:
                out_path, balanced = process_one(
                    pdf, jno, args.location, args.output,
                    date_override=None, show_preview=True,
                )
                results.append((pdf, jno, balanced))
            except Exception as e:
                print(f"   [ERROR] {pdf}: {e}")
                results.append((pdf, jno, False))

        print("\n=== Batch summary ===")
        for pdf, jno, ok in results:
            status = "OK" if ok else "CHECK"
            print(f"  [{status}] {jno}  {os.path.basename(pdf)}")
        return

    if not args.pdf_path or not args.journal_no:
        ap.print_help()
        sys.exit(1)

    process_one(
        args.pdf_path, args.journal_no, args.location, args.output,
        manual_sani=args.manual_sani, manual_firewood=args.manual_firewood,
        date_override=args.date_override, show_preview=True,
    )


if __name__ == "__main__":
    main()
