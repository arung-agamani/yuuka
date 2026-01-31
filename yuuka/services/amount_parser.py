import re
from typing import Optional


class AmountParser:
    """
    Parser for various amount formats commonly used in informal transactions.

    Supports:
    - Suffixes: k (thousand), m/mil/jt (million), b/mil (billion)
    - Indonesian decimal format: 52.500 = 52500 (dot as thousand separator)
    - Standard numbers: 1000, 500.50
    - Mixed formats: 1.5k = 1500, 2.5m = 2500000
    """

    # Multiplier patterns (case-insensitive)
    MULTIPLIERS = {
        "k": 1_000,
        "rb": 1_000,  # ribu (Indonesian)
        "ribu": 1_000,
        "m": 1_000_000,
        "jt": 1_000_000,  # juta (Indonesian)
        "juta": 1_000_000,
        "mil": 1_000_000,
        "million": 1_000_000,
        "b": 1_000_000_000,
        "billion": 1_000_000_000,
        "M": 1_000_000_000,  # miliar (Indonesian)
        "miliar": 1_000_000_000,
    }

    # Regex pattern for amount with optional suffix
    # Matches: 16k, 1.5mil, 52.500, 1,000.50, etc.
    # Uses negative lookbehind to avoid matching numbers within words like "account1"
    AMOUNT_PATTERN = re.compile(
        r"""
        (?<![a-zA-Z])                           # Not preceded by a letter
        (?P<number>
            \d{1,3}(?:[.,]\d{3})*(?:[.,]\d+)?  # Numbers with thousand separators
            |
            \d+(?:[.,]\d+)?                     # Simple numbers with optional decimal
        )
        \s*
        (?P<suffix>k|rb|ribu|m|jt|juta|mil|million|b|billion|miliar)?
        (?![a-zA-Z])                            # Not followed by a letter
        """,
        re.VERBOSE | re.IGNORECASE,
    )

    @classmethod
    def parse(cls, text: str) -> Optional[float]:
        """
        Parse an amount string and return the numeric value.

        Args:
            text: String containing an amount (e.g., "16k", "52.500", "1.5mil")

        Returns:
            Float value of the amount, or None if parsing fails
        """
        if not text:
            return None

        text = text.strip()
        match = cls.AMOUNT_PATTERN.search(text)

        if not match:
            return None

        number_str = match.group("number")
        suffix = match.group("suffix")

        # Parse the number
        number = cls._parse_number(number_str)
        if number is None:
            return None

        # Apply multiplier if suffix exists
        if suffix:
            suffix_lower = suffix.lower()
            multiplier = cls.MULTIPLIERS.get(suffix_lower, 1)
            number *= multiplier

        return float(number)

    @classmethod
    def _parse_number(cls, number_str: str) -> Optional[float]:
        """
        Parse a number string handling various formats.

        Handles:
        - Indonesian format: 52.500 (dot as thousand separator) -> 52500
        - Western format: 52,500.00 (comma as thousand, dot as decimal)
        - Simple: 52500
        """
        if not number_str:
            return None

        # Count dots and commas
        dots = number_str.count(".")
        commas = number_str.count(",")

        # Determine format and normalize
        if dots > 0 and commas > 0:
            # Mixed format - assume Western (1,234.56)
            normalized = number_str.replace(",", "")
        elif dots > 1:
            # Multiple dots - Indonesian thousand separator (1.234.567)
            normalized = number_str.replace(".", "")
        elif commas > 1:
            # Multiple commas - thousand separator (1,234,567)
            normalized = number_str.replace(",", "")
        elif dots == 1:
            # Single dot - could be decimal or thousand separator
            # Check position: if 3 digits after dot, likely thousand separator
            parts = number_str.split(".")
            if len(parts[1]) == 3 and len(parts[0]) <= 3:
                # Likely Indonesian format (52.500)
                normalized = number_str.replace(".", "")
            else:
                # Likely decimal (52.50)
                normalized = number_str
        elif commas == 1:
            # Single comma - treat as thousand separator or decimal
            parts = number_str.split(",")
            if len(parts[1]) == 3:
                # Thousand separator
                normalized = number_str.replace(",", "")
            else:
                # European decimal format
                normalized = number_str.replace(",", ".")
        else:
            # No separators
            normalized = number_str

        try:
            return float(normalized)
        except ValueError:
            return None

    @classmethod
    def find_amount_in_text(cls, text: str) -> Optional[tuple[float, str]]:
        """
        Find and parse the first amount in a text string.

        Args:
            text: Text that may contain an amount

        Returns:
            Tuple of (parsed_amount, matched_string) or None if no amount found
        """
        match = cls.AMOUNT_PATTERN.search(text)
        if not match:
            return None

        matched_text = match.group(0)
        amount = cls.parse(matched_text)

        if amount is not None:
            return (amount, matched_text)

        return None

    @classmethod
    def find_all_amounts(cls, text: str) -> list[tuple[float, str, int, int]]:
        """
        Find all amounts in a text string.

        Args:
            text: Text that may contain amounts

        Returns:
            List of tuples: (parsed_amount, matched_string, start_pos, end_pos)
        """
        results = []

        for match in cls.AMOUNT_PATTERN.finditer(text):
            matched_text = match.group(0)
            amount = cls.parse(matched_text)

            if amount is not None:
                results.append(
                    (amount, matched_text.strip(), match.start(), match.end())
                )

        return results
