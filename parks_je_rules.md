# Manning Park Resort — Parks Daily Revenue Journal Entry: Automation Rules

## What this is

Each day, Parks collectors (rangers/staff collecting camping fees, sani
station fees, firewood sales, etc.) turn in cash and their totals get
summarized on a "NA Spreadsheet" PDF (one page per day). This needs to
become one balanced journal entry per day, formatted as a QBO-importable
CSV, following the exact conventions below.

## Source document layout (the PDF)

Each PDF has a collector-by-collector table, then three summary lines
at the bottom that are the ONLY numbers actually needed to build the
journal entry (the per-collector rows are for human sanity-checking
only, not for building the JE):

```
Sub Total   <17-18 numeric columns — see below>
Total Deposit   <amount>
DEPOSIT REQUIRED   <amount>
DIFFERENCE:   <amount>   OVER or UNDER
```

### The "Sub Total" row columns, in order

This order has been verified against every sheet in August 2026 and is
stable:

1. Gross Cash Fees
2. (filler, always 0.00)
3. Gross Reservations in $$
4. (filler, always 0.00)
5. (filler, always 0.00 — Refunds)
6. **Net Camping Fees** ← needed
7. **Net GST** (on camping) ← needed
8. Firewood (gross)
9. **FW Net** ← needed
10. **FW GST** ← needed
11. (filler, always 0.00)
12. Sani Gross
13. **Sani Net** ← needed
14. **Sani GST** ← needed
15. US $
16. POS CAD $ (= Total Deposit, sanity check)
17. (filler, always 0.00)
18. **Over & Short** ← needed (signed: positive = OVER, negative = UNDER)

Some sheets may have a slightly different column count if formatting
changes — if the column count isn't 18, flag it and require manual
review rather than guessing.

### The three key totals

- **Total Deposit** = actual cash/POS turned in for the day (this is
  what physically went into the safe)
- **DEPOSIT REQUIRED** = Net Camping + Net GST + Sani Net + Sani GST +
  FW Net + FW GST (what SHOULD have been turned in, per the math)
- **DIFFERENCE** = Total Deposit − DEPOSIT REQUIRED
  - Positive / "OVER" = extra cash was turned in
  - Negative / "UNDER" = cash is short

## The journal entry to build (per day)

One journal entry, `*JournalDate` = the date on that day's sheet,
Memo/Description = `Parks Daily Revenue <Month Day Year>` (e.g. "Parks
Daily Revenue Aug 10 2026"), Class = `0050-MANNING PARKS` on every line.

```
DR  1002 Petty Cash in safe          = Total Deposit
[DR 6036 Cash Short/Over]            = only if DIFFERENCE is negative (SHORT), amount = abs(difference)
    CR  3033 Camping                 = Net Camping Fees
    CR  2029 GST Charged on Sales    = Net GST (the camping one)
    [CR 3009 Sani Station]           = only if Sani Net is non-zero
    [CR 2029 GST Charged on Sales]   = Sani GST, only if Sani Net is non-zero
    [CR 3008 Wood Sales]             = only if FW Net is non-zero
    [CR 2029 GST Charged on Sales]   = FW GST, only if FW Net is non-zero
[CR 6036 Cash Short/Over]            = only if DIFFERENCE is positive (OVER), amount = difference
```

Lines with a $0.00 amount are omitted entirely — don't post zero-dollar
lines. There can be up to two separate "2029 GST Charged on Sales"
credit lines in one entry (one for camping GST, one for Sani or FW GST)
— that's expected and correct, not a duplicate to merge.

**Every entry must balance: total debits = total credits, to the
penny.** Treat any entry that doesn't balance as a parsing error to
investigate, never round or force-balance it.

## CSV output format

Match the existing QBO journal-entry-import template exactly:

```
*JournalNo,*JournalDate,Memo,*AccountName,Debits,Credits,Description,Name,Location,Class
```

- `*JournalNo` and `*JournalDate` and `Memo` are only populated on the
  FIRST line of each journal entry; blank on subsequent lines of that
  same entry (this is how QBO's import groups lines into one JE).
- `Description` repeats the memo text on every line.
- `Name` and `Location` columns stay blank; `Class` = `0050-MANNING
  PARKS` on every line.
- Date format: `DD-MM-YYYY` (matches existing imports).
- Two decimal places on every dollar amount, no currency symbols, no
  thousands separators.

## The one thing that requires human judgment — cannot be automated blindly

Occasionally a collector row is literally named "Sani" or
"Sanistation" (or similarly for Firewood), but their dollars were
typed into the regular **Camping Fee** columns instead of the
dedicated **Sani Gross/Net/GST** (or Firewood) columns. When this
happens, the dedicated Sani/FW columns show $0.00 even though real
Sani/Firewood revenue occurred that day — it's hiding inside "Net
Camping Fees" instead.

There is no way to detect this purely from the Sub Total numbers —
it requires reading the individual collector-name rows. Any
automation should:

1. Always print/display the raw collector rows alongside the parsed
   totals, so a human can glance at collector names before the entry
   is finalized.
2. Support a manual override that lets the operator specify "pull $X
   net / $Y GST out of Camping and into Sani (or Firewood) instead" —
   this then reduces the Camping/GST credit lines by that amount and
   adds Sani Station/GST (or Wood Sales/GST) lines for it.
3. Never guess or auto-detect this from the collector name string
   alone — a "Sani" named collector's money is CORRECTLY in the
   Camping columns most days; it only needs pulling out on the rare
   day it was miskeyed into the wrong columns. This has to be a human
   call, made by comparing the dedicated Sani column values against
   the collector list.

## Journal number sequencing

Journal numbers (e.g. `JJ3317`) are usually sequential day-to-day, but
NOT always — QBO interleaves numbers from other outlets/transactions,
so gaps happen (e.g. Aug 26 was JJ3342, but Aug 27 jumped to JJ3386,
then Aug 29 jumped again to JJ3446). Any automation should:

- Accept an explicit journal number per day/run, OR
- Auto-increment sequentially as a convenience default, but flag this
  clearly as a guess that needs confirming against QBO before import
  — never assume auto-increment is correct without a human check.

## GL account reference (Manning Park Resort chart of accounts)

- `1002 Petty Cash in safe` — debit, actual cash/POS deposit
- `3033 Camping` — credit, net camping fee revenue
- `2029 GST Charged on Sales` — credit, GST liability (used for
  camping, Sani, and Firewood GST — same account each time)
- `3009 Sani Station` — credit, net sani station revenue
- `3008 Wood Sales` — credit, net firewood revenue
- `6036 Cash Short/Over` — debit if short, credit if over

## Validation checklist for every generated entry

- [ ] Total debits = total credits (exact match, to the penny)
- [ ] Total Deposit on the debit side matches the PDF's "Total
      Deposit" line exactly
- [ ] Zero-dollar lines are omitted, not posted
- [ ] Cash Short/Over only appears once, on the correct side (debit
      if short, credit if over), and only if DIFFERENCE ≠ 0
- [ ] Sani/Firewood lines only appear if their dedicated Net columns
      are non-zero (or a manual override was explicitly applied)
- [ ] Collector rows were reviewed for any Sani/Firewood-named
      collector whose money might be sitting in the wrong columns
