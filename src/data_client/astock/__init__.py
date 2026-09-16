"""Chinese A-share news, provided through the causal-memory hub."""

from src.data_client.astock.news_source import AstockNewsSource, available

__all__ = ["AstockNewsSource", "available"]
