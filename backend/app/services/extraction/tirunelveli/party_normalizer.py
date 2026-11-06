import re

# Domain keywords for logistics parties, locations, and entities in Tamil Nadu / South India
PARTY_WORDS = [
    "ENTERPRISES",
    "ENTERPRISE",
    "PRIVATE",
    "LIMITED",
    "PAPER",
    "MART",
    "AGENCIES",
    "AGENCY",
    "TRADERS",
    "TRADING",
    "MEENAKSHI",
    "KAUSIKA",
    "SESHASAYEE",
    "BOARDS",
    "MILLS",
    "SOLUTIONS",
    "LOGISTICS",
    "TRANSPORT",
    "ASSOCIATES",
    "INDUSTRIES",
    "PRODUCTS",
    "STORES",
    "SUPPLIERS",
    "DISTRIBUTORS",
    "CORPORATION",
    "CENTRAL",
    "TAMILNADU",
    "TAMIL",
    "NADU",
    "ERNAKULAM",
    "KUNNAMKULAM",
    "MADURAI",
    "TIRUNELVELI",
    "TRICHY",
    "CHENNAI",
    "COIMBATORE",
    "KERALA",
    "BANGALORE",
    "HYDERABAD",
    "SRI",
    "SHREE",
    "SHRI",
    "SPB",
    "LTD",
    "PVT",
]
# Sort descending by length so longer words match first (e.g. ENTERPRISES before ENTERPRISE)
PARTY_WORDS.sort(key=len, reverse=True)


class PartyNameNormalizer:
    """Normalizes party names and addresses to readable spacing without corrupting alphanumeric identifiers."""

    @classmethod
    def normalize(cls, name: str) -> str:
        if not name or name.startswith("UNKNOWN") or name.startswith("TO BE BILLED"):
            return name

        # Replace newlines with spaces and strip
        text = re.sub(r"[\r\n]+", " ", name).strip()

        tokens = text.split()
        new_tokens = []
        for token in tokens:
            # Preserve punctuation as separate boundaries
            sub_tokens = re.split(r"([,\./\-])", token)
            for st in sub_tokens:
                if not st or st in ",./-":
                    if st:
                        new_tokens.append(st)
                    continue

                upper_st = st.upper()
                pos = 0
                extracted: list[str] = []
                while pos < len(upper_st):
                    matched = False
                    for w in PARTY_WORDS:
                        if upper_st.startswith(w, pos):
                            # Preserve casing from original token slice
                            extracted.append(st[pos : pos + len(w)])
                            pos += len(w)
                            matched = True
                            break
                    if not matched:
                        extracted.append(st[pos:])
                        break

                if len(extracted) > 1:
                    new_tokens.extend(extracted)
                else:
                    new_tokens.append(st)

        res = " ".join(new_tokens)
        # Fix spacing around punctuation: no space before comma, single space after comma
        res = re.sub(r"\s+([,\./\-])", r"\1", res)
        res = re.sub(r"([,\./\-])(?=[^\s])", r"\1 ", res)
        return re.sub(r"\s+", " ", res).strip()
