"""
Demo script for the Transaction NLP Service.

This demonstrates parsing natural language transaction descriptions
into structured data.
"""

from yuuka.services import TransactionNLPService, parse_transaction


def main():
    # Example transaction descriptions
    examples = [
        "16k from gopay for commuting",
        "52.500 from main pocket for lunch",
        "transfer 1mil from account1 to account3",
        "incoming salary 21m to main pocket",
        "spent 150k from wallet for groceries",
        "received 500k to savings",
        "25.000 from cash for coffee",
        "transfer 2.5m from savings to investment",
    ]

    print("=" * 60)
    print("Transaction NLP Service Demo")
    print("=" * 60)

    # Initialize the service
    service = TransactionNLPService()

    for text in examples:
        print(f'\nInput: "{text}"')
        print("-" * 40)

        result = service.parse(text)

        print(f"  Action:      {result.action.value}")
        print(
            f"  Amount:      {result.amount:,.0f}"
            if result.amount
            else "  Amount:      None"
        )
        print(f"  Source:      {result.source or 'None'}")
        print(f"  Destination: {result.destination or 'None'}")
        print(f"  Description: {result.description or 'None'}")
        print(f"  Confidence:  {result.confidence:.0%}")
        print(f"  Valid:       {result.is_valid()}")

    print("\n" + "=" * 60)
    print("Using convenience function")
    print("=" * 60)

    # Using the convenience function
    parsed = parse_transaction("100k from bank for dinner")
    print(f"\nParsed: {parsed.to_dict()}")


if __name__ == "__main__":
    main()
