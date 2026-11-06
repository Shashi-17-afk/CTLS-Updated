from typing import Sequence


class InvoiceRangeCompressor:
    """Compresses a list of invoice numbers into the standardized format specified by PRD §5.3.

    Rules:
    - Sequence with a hyphen: end of range is shortened by keeping the differing suffix.
      Examples:
      - ['1250510479', '1250510480'] -> '1250510479-480'
      - ['2250501854', '2250501855', '2250501856'] -> '2250501854-56'
      - ['2250601397', '2250601398', '2250601399', '2250601400'] -> '2250601397-400'
      - ['1001', '1002', '1003'] -> '1001-1003'
    - Non-sequential numbers: separated with comma and space.
      Example: ['1001', '1005', '1009'] -> '1001, 1005, 1009'
    - Mixed sequences: sequential sub-ranges compressed, outliers comma-separated.
      Example: ['1001', '1002', '1003', '1008'] -> '1001-1003, 1008'
    """

    @classmethod
    def compress(cls, invoice_numbers: Sequence[str]) -> str:
        if not invoice_numbers:
            return ""

        # Deduplicate while preserving order of first appearance, then parse
        unique_raw: list[str] = []
        for inv in invoice_numbers:
            cleaned = str(inv).strip()
            if cleaned and cleaned not in unique_raw:
                unique_raw.append(cleaned)

        if not unique_raw:
            return ""

        # Check if all numbers are numeric and can be sorted numerically
        if all(item.isdigit() for item in unique_raw):
            sorted_items = sorted(unique_raw, key=lambda x: (len(x), int(x)))
        else:
            sorted_items = sorted(unique_raw)

        # Group consecutive sequential integers
        runs: list[list[str]] = []
        current_run: list[str] = [sorted_items[0]]

        for i in range(1, len(sorted_items)):
            prev = sorted_items[i - 1]
            curr = sorted_items[i]

            if (
                prev.isdigit()
                and curr.isdigit()
                and len(prev) == len(curr)
                and int(curr) == int(prev) + 1
            ):
                current_run.append(curr)
            else:
                runs.append(current_run)
                current_run = [curr]
        runs.append(current_run)

        # Format each run
        formatted_runs: list[str] = []
        for run in runs:
            if len(run) == 1:
                formatted_runs.append(run[0])
            else:
                start = run[0]
                end = run[-1]

                # Shorten end of range if long digits (> 4)
                if len(start) > 4 and len(start) == len(end):
                    # Find index where start and end first differ
                    diff_idx = 0
                    while diff_idx < len(start) and start[diff_idx] == end[diff_idx]:
                        diff_idx += 1
                    shortened_end = end[diff_idx:]
                    # Ensure shortened suffix is at least 2 digits if available
                    if len(shortened_end) < 2 and len(end) >= 2:
                        shortened_end = end[-2:]
                    # On tens rollover ending in 0 (e.g. 479 to 480 per PRD §5.3), preserve 3-digit hundred context
                    elif len(shortened_end) == 2 and end.endswith("0") and len(end) >= 3:
                        shortened_end = end[-3:]
                    formatted_runs.append(f"{start}-{shortened_end}")
                else:
                    # For 4 digits or fewer, keep full end (e.g. 1001-1003 per PRD §5.3)
                    formatted_runs.append(f"{start}-{end}")

        return ", ".join(formatted_runs)
