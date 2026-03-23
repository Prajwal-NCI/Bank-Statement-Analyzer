"""
tax_calculator.py

Simple tax (VAT) calculation helper class.

This module is part of my MSc Cloud Computing project and is inspired by
the NumberProperties example from the lecture. Instead of checking numbers,
it focuses on basic VAT calculations for invoice amounts.

At the moment it supports a few hard-coded VAT rates for demonstration:
- Ireland (IE): 23%
- United Kingdom (UK): 20%
- Germany (DE): 19%
- Default: 20%

The goal is to keep this library small and easy to understand so that it
can be reused in my cloud-based invoice management application.
"""

from decimal import Decimal


class TaxCalculator:
    """
    TaxCalculator is a small helper class for calculating VAT.

    It can:
    - calculate VAT on a net amount
    - extract VAT from a gross amount
    - use different rates for different countries

    Example usage:

        calc = TaxCalculator()
        vat, gross = calc.add_vat(100.0, country_code="IE")
        print(vat, gross)

        vat, net = calc.extract_vat(123.0, country_code="IE")
        print(vat, net)
    """

    def __init__(self):
        """
        Initialise the calculator with some default VAT rates.

        These are simplified and for demo purposes only.
        """
        self.vat_rates = {
            "IE": 0.23,  # Ireland standard VAT
            "UK": 0.20,  # UK standard VAT
            "DE": 0.19,  # Germany standard VAT
            "DEFAULT": 0.20,
        }

    def get_rate(self, country_code: str) -> float:
        """
        Get the VAT rate for a given country code.

        If the code is not recognised, return the DEFAULT rate.
        """
        if not country_code:
            return self.vat_rates["DEFAULT"]

        code = country_code.upper()

        if code in self.vat_rates:
            return self.vat_rates[code]
        else:
            # fall back to default
            return self.vat_rates["DEFAULT"]

    def add_vat(self, net_amount, country_code: str = "IE"):
        """
        Calculate VAT and gross amount from a net amount.

        Args:
            net_amount: net price (before VAT), can be float or Decimal
            country_code: two-letter country code, e.g. "IE", "UK"

        Returns:
            (vat_amount, gross_amount) as floats

        Example:
            vat, gross = calc.add_vat(100.0, "IE")
        """
        # convert to Decimal for better precision
        net = Decimal(str(net_amount))
        rate = Decimal(str(self.get_rate(country_code)))

        vat = net * rate
        gross = net + vat

        # return as simple floats to make it easy for JSON, JS, etc.
        return float(vat), float(gross)

    def extract_vat(self, gross_amount, country_code: str = "IE"):
        """
        Extract VAT and net amount from a gross amount.

        This is useful when the invoice total already includes VAT.

        Args:
            gross_amount: total price including VAT
            country_code: two-letter country code

        Returns:
            (vat_amount, net_amount) as floats

        Example:
            vat, net = calc.extract_vat(123.0, "IE")
        """
        gross = Decimal(str(gross_amount))
        rate = Decimal(str(self.get_rate(country_code)))

        # formula: net = gross / (1 + rate)
        divisor = Decimal("1.0") + rate

        if divisor == 0:
            # should never happen but guard anyway
            net = gross
            vat = Decimal("0")
        else:
            net = gross / divisor
            vat = gross - net

        return float(vat), float(net)


if __name__ == "__main__":
    # Simple manual test, similar to the lecture style

    calc = TaxCalculator()

    print("\n=== Manual tests for TaxCalculator ===")

    net = 100.0
    vat, gross = calc.add_vat(net, "IE")
    print(f"IE add_vat: net={net}, vat={vat:.2f}, gross={gross:.2f}")

    gross = 123.0
    vat2, net2 = calc.extract_vat(gross, "IE")
    print(f"IE extract_vat: gross={gross}, vat={vat2:.2f}, net={net2:.2f}")

    vat_uk, gross_uk = calc.add_vat(100.0, "UK")
    print(f"UK add_vat: net=100.0, vat={vat_uk:.2f}, gross={gross_uk:.2f}")
