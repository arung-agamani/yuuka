import re
from typing import Optional

import spacy
from spacy.matcher import Matcher

from ..models.transaction import ParsedTransaction, TransactionAction
from .amount_parser import AmountParser


class TransactionNLPService:
    """
    NLP Service for parsing natural language transaction descriptions.

    Uses spaCy for tokenization and pattern matching to extract:
    - Action: incoming, outgoing, or transfer
    - Amount: monetary value
    - Source: where funds come from ("from X")
    - Destination: where funds go to ("to X")
    - Description: purpose or note for the transaction
    """

    # Keywords that indicate transaction actions
    INCOMING_KEYWORDS = {
        "incoming",
        "received",
        "got",
        "income",
        "salary",
        "earn",
        "earned",
    }
    OUTGOING_KEYWORDS = {"spent", "paid", "bought", "buy", "expense", "for"}
    TRANSFER_KEYWORDS = {"transfer", "transferred", "move", "moved", "send", "sent"}

    def __init__(self, model_name: str = "en_core_web_sm"):
        """
        Initialize the NLP service.

        Args:
            model_name: Name of the spaCy model to load
        """
        self.nlp = spacy.load(model_name)
        self.matcher = Matcher(self.nlp.vocab)
        self._setup_patterns()

    def _setup_patterns(self):
        """Setup spaCy matcher patterns for entity extraction."""
        # Pattern for "from X" - source extraction
        from_pattern = [{"LOWER": "from"}, {"IS_ALPHA": True, "OP": "+"}]
        self.matcher.add("FROM_ENTITY", [from_pattern])

        # Pattern for "to X" - destination extraction
        to_pattern = [{"LOWER": "to"}, {"IS_ALPHA": True, "OP": "+"}]
        self.matcher.add("TO_ENTITY", [to_pattern])

        # Pattern for "for X" - description/purpose
        for_pattern = [{"LOWER": "for"}, {"IS_ALPHA": True, "OP": "+"}]
        self.matcher.add("FOR_ENTITY", [for_pattern])

    def parse(self, text: str) -> ParsedTransaction:
        """
        Parse a transaction description into structured data.

        Args:
            text: Natural language transaction description

        Returns:
            ParsedTransaction with extracted fields
        """
        text = text.strip()
        text_lower = text.lower()
        doc = self.nlp(text)

        # Extract components
        action = self._detect_action(text_lower, doc)
        amount = self._extract_amount(text)
        source = self._extract_source(text_lower, doc)
        destination = self._extract_destination(text_lower, doc)
        description = self._extract_description(text_lower, doc)

        # Calculate confidence based on how many fields were extracted
        confidence = self._calculate_confidence(action, amount, source, destination)

        return ParsedTransaction(
            action=action,
            amount=amount,
            source=source,
            destination=destination,
            description=description,
            raw_text=text,
            confidence=confidence,
        )

    def _detect_action(self, text_lower: str, doc) -> TransactionAction:
        """Detect the transaction action type from text."""
        tokens = set(token.text.lower() for token in doc)

        # Check for explicit action keywords
        if tokens & self.TRANSFER_KEYWORDS or "transfer" in text_lower:
            return TransactionAction.TRANSFER

        if tokens & self.INCOMING_KEYWORDS or text_lower.startswith("incoming"):
            return TransactionAction.INCOMING

        # Check patterns to infer action
        has_from = "from" in text_lower
        has_to = "to" in text_lower
        has_for = "for" in text_lower

        # "transfer from X to Y" pattern
        if has_from and has_to:
            return TransactionAction.TRANSFER

        # "X to Y" without from usually indicates incoming
        if has_to and not has_from:
            return TransactionAction.INCOMING

        # "from X for Y" pattern - money going out from a source for a purpose
        if has_from and has_for:
            return TransactionAction.OUTGOING

        # "from X" alone typically means outgoing
        if has_from:
            return TransactionAction.OUTGOING

        # Default to outgoing for expense-like patterns
        if tokens & self.OUTGOING_KEYWORDS:
            return TransactionAction.OUTGOING

        # If nothing else matches, default based on common patterns
        return TransactionAction.OUTGOING

    def _extract_amount(self, text: str) -> Optional[float]:
        """Extract monetary amount from text."""
        result = AmountParser.find_amount_in_text(text)
        if result:
            return result[0]
        return None

    def _extract_source(self, text_lower: str, doc) -> Optional[str]:
        """Extract the source of funds (after 'from' keyword)."""
        # Special handling for "from X to Y" pattern
        from_to_pattern = r"\bfrom\s+(.+?)\s+to\b"
        match = re.search(from_to_pattern, text_lower)
        if match:
            entity = match.group(1).strip()
            entity = self._clean_entity(entity)
            if entity:
                return entity

        return self._extract_entity_after_keyword(text_lower, "from", doc)

    def _extract_destination(self, text_lower: str, doc) -> Optional[str]:
        """Extract the destination of funds (after 'to' keyword)."""
        # Special handling for "to X" at end or before "for"
        to_pattern = r"\bto\s+(.+?)(?:\s+for\b|$)"
        match = re.search(to_pattern, text_lower)
        if match:
            entity = match.group(1).strip()
            entity = self._clean_entity(entity)
            if entity:
                return entity

        return self._extract_entity_after_keyword(text_lower, "to", doc)

    def _extract_description(self, text_lower: str, doc) -> Optional[str]:
        """Extract the purpose/description (after 'for' keyword or other context)."""
        # First try to get text after "for"
        description = self._extract_entity_after_keyword(text_lower, "for", doc)
        if description:
            return description

        # For incoming transactions, try to extract description before "to"
        # e.g., "incoming salary 21m to main pocket" -> "salary"
        if "incoming" in text_lower:
            # Find text between "incoming" and amount or "to"
            match = re.search(r"incoming\s+(\w+)", text_lower)
            if match:
                word = match.group(1)
                # Make sure it's not a number
                if not AmountParser.parse(word):
                    return word

        return None

    def _extract_entity_after_keyword(
        self, text_lower: str, keyword: str, doc
    ) -> Optional[str]:
        """
        Extract entity/phrase that follows a specific keyword.

        Handles multi-word entities like "main pocket", "account1", etc.
        """
        # Find the keyword position
        pattern = rf"\b{keyword}\s+(.+?)(?:\s+(?:from|to|for)\b|$)"
        match = re.search(pattern, text_lower)

        if match:
            entity = match.group(1).strip()
            # Clean up: remove any amount patterns from the entity
            entity = self._clean_entity(entity)
            if entity:
                return entity

        # Fallback: simple extraction
        simple_pattern = rf"\b{keyword}\s+(\S+(?:\s+\S+)?)"
        match = re.search(simple_pattern, text_lower)

        if match:
            entity = match.group(1).strip()
            entity = self._clean_entity(entity)
            if entity:
                return entity

        return None

    def _clean_entity(self, entity: str) -> Optional[str]:
        """Clean extracted entity by removing amounts and extra whitespace."""
        if not entity:
            return None

        # Remove amount patterns
        amount_result = AmountParser.find_amount_in_text(entity)
        if amount_result:
            _, matched_amount = amount_result
            # If the entity is just an amount, return None
            if entity.strip() == matched_amount.strip():
                return None

        # Split and filter out amount-like tokens
        words = entity.split()
        cleaned_words = []
        for word in words:
            # Skip if word looks like an amount
            if AmountParser.parse(word) is not None:
                continue
            # Skip common stopwords that shouldn't be entities
            if word.lower() in {"the", "a", "an"}:
                continue
            cleaned_words.append(word)

        if cleaned_words:
            return " ".join(cleaned_words)

        return None

    def _calculate_confidence(
        self,
        action: TransactionAction,
        amount: Optional[float],
        source: Optional[str],
        destination: Optional[str],
    ) -> float:
        """
        Calculate a confidence score for the parsing result.

        Higher score = more complete and reliable extraction.
        """
        score = 0.0

        # Amount is crucial
        if amount is not None:
            score += 0.4

        # Source/destination based on action type
        if action == TransactionAction.TRANSFER:
            if source:
                score += 0.2
            if destination:
                score += 0.2
            if source and destination:
                score += 0.2  # Bonus for complete transfer
        elif action == TransactionAction.INCOMING:
            if destination:
                score += 0.4
            if source:
                score += 0.1  # Bonus if source is also known
        elif action == TransactionAction.OUTGOING:
            if source:
                score += 0.4
            if destination:
                score += 0.1  # Bonus if destination is also known

        # Cap at 1.0
        return min(score, 1.0)

    def parse_batch(self, texts: list[str]) -> list[ParsedTransaction]:
        """
        Parse multiple transaction descriptions.

        Args:
            texts: List of transaction descriptions

        Returns:
            List of ParsedTransaction objects
        """
        return [self.parse(text) for text in texts]


# Singleton instance for convenience
_default_service: Optional[TransactionNLPService] = None


def get_nlp_service() -> TransactionNLPService:
    """Get or create the default NLP service instance."""
    global _default_service
    if _default_service is None:
        _default_service = TransactionNLPService()
    return _default_service


def parse_transaction(text: str) -> ParsedTransaction:
    """
    Convenience function to parse a transaction using the default service.

    Args:
        text: Transaction description

    Returns:
        ParsedTransaction with extracted fields
    """
    return get_nlp_service().parse(text)
