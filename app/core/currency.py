CURRENCY_DISPLAY = {
    "XOF": "F CFA",
    "XAF": "F CFA",
    "EUR": "€",
    "USD": "$",
    "MAD": "DH",
}

def get_currency_symbol(code: str) -> str:
    return CURRENCY_DISPLAY.get(code, code)