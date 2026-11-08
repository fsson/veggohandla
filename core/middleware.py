"""Per-request locale details that the pure domain layer can't look up itself."""

from django.utils import translation

from core.domain.units import decimal_separator


class DecimalSeparatorMiddleware:
    """Make `format_number` use the decimal separator of the active language.

    Must come after LocaleMiddleware. The domain layer has no Django dependency, so it
    reads a context variable that is set here for the duration of each request.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        lang = translation.get_language() or "sv"
        token = decimal_separator.set("," if lang.startswith("sv") else ".")
        try:
            return self.get_response(request)
        finally:
            decimal_separator.reset(token)
