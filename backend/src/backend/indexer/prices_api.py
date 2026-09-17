DEFAULT_PRICES_API_BASE_URL = "https://prices.wavey.info"


class PricesApiError(RuntimeError):
    pass


class PricesApiAuthError(PricesApiError):
    pass


class PricesApiRateLimitError(PricesApiError):
    pass
