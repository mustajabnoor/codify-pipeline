import logging
import sys


def setup_logging(verbose: bool = False) -> None:
    """Log to stderr so stdout stays clean for --dry-run output."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        stream=sys.stderr,
        force=True,
    )
    # Supabase's HTTP stack logs every request at INFO.
    for noisy in ("httpx", "httpcore", "hpack"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
