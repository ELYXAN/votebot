"""Votebot - Twitch Channel Point Vote Tracker mit Web-Dashboard."""
import os

__version__ = "4.0.1"


def _use_bundled_ca_certificates() -> None:
    """Windows: mitgelieferte Stammzertifikate (certifi) für HTTPS bereitstellen.

    Python liest unter Windows die Stammzertifikate aus dem Zertifikatsspeicher
    des Systems. Windows lädt viele davon aber erst bei Bedarf nach, und Python
    löst dieses Nachladen nicht aus. Auf einem frischen System fehlt dann z. B.
    das Zertifikat für id.twitch.tv, und die Anmeldung scheitert mit
    ``CERTIFICATE_VERIFY_FAILED: unable to get local issuer certificate``.

    ``SSL_CERT_FILE`` ergänzt den Systemspeicher um das certifi-Bündel. Das
    muss passieren, bevor aiohttp importiert wird, weil aiohttp seinen
    TLS-Kontext beim Import anlegt; deshalb steht es hier im Paket-Start.
    Eine vom Nutzer gesetzte Variable bleibt unangetastet.
    """
    if os.name != "nt" or os.environ.get("SSL_CERT_FILE"):
        return
    try:
        import certifi
    except ImportError:
        return
    os.environ["SSL_CERT_FILE"] = certifi.where()


_use_bundled_ca_certificates()
