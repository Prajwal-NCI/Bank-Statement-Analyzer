"""
invoice_tax_pkg

Small Python package for VAT calculations on invoice amounts.
Created for MSc Cloud Computing (Cloud Platform Programming module).
"""

from .tax_calculator import TaxCalculator

__all__ = ["TaxCalculator"]
