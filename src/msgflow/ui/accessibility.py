import logging

logger = logging.getLogger(__name__)

try:
    import HIServices
except ImportError:  # pragma: no cover - depends on pyobjc ApplicationServices bindings
    HIServices = None

def _prompt_option_key():
    if HIServices is None:
        return "AXTrustedCheckOptionPrompt"
    return getattr(HIServices, "kAXTrustedCheckOptionPrompt", "AXTrustedCheckOptionPrompt")


def accessibility_authorized() -> bool:
    if HIServices is None:
        return False
    try:
        if hasattr(HIServices, "AXIsProcessTrusted"):
            return bool(HIServices.AXIsProcessTrusted())
        if hasattr(HIServices, "AXIsProcessTrustedWithOptions"):
            return bool(HIServices.AXIsProcessTrustedWithOptions({}))
    except Exception:
        logger.exception("failed to check accessibility authorization state")
    return False


def request_accessibility_authorization() -> bool:
    if HIServices is None:
        return False
    try:
        if hasattr(HIServices, "AXIsProcessTrustedWithOptions"):
            return bool(
                HIServices.AXIsProcessTrustedWithOptions(
                    {_prompt_option_key(): True}
                )
            )
    except Exception:
        logger.exception("failed to request accessibility authorization")
    return accessibility_authorized()
