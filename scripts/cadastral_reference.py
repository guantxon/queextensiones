"""Utilities to retrieve the Spanish cadastral reference for a given address.

This module focuses on the public web services made available by the
Dirección General del Catastro.  The service exposes a set of XML endpoints
that can be accessed without authentication.  The goal of this script is to
provide a simple command line interface that:

* Normalises an address passed via CLI arguments.
* Queries the Catastro "ConsultaRC" endpoint and extracts the returned
  references.
* Prints the references to stdout while keeping the code easily extensible
  for future scrapers (e.g. real estate portals).

The script has been intentionally designed with testability and extensibility
in mind.  A base ``ReferenceProvider`` protocol describes the behaviour that
any scraper must implement.  Only the Catastro provider is implemented here,
while additional providers can be plugged into the ``ReferenceAggregator``.
"""

from __future__ import annotations

import argparse
import logging
import sys
import textwrap
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Iterable, Optional, Protocol, Sequence, Set

import requests

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class Address:
    """Simple container for the relevant address fields.

    Parameters
    ----------
    province:
        Spanish province name (``Provincia`` parameter for Catastro).
    municipality:
        Municipality/locality name (``Municipio``).
    street:
        Street name without the road type prefix.  Use ``road_type`` for
        prefixes such as "Calle" or "Avenida".
    number:
        Street number or property identifier as expected by Catastro.
    road_type:
        Optional road type (``Sigla`` parameter in the Catastro API).  When
        unsure, leave it empty and the service will perform a broader search.
    postal_code:
        Optional postal code.  This field is not used by the official web
        service but it is kept here for potential future scrapers that rely on
        it (e.g. real estate portals).
    """

    province: str
    municipality: str
    street: str
    number: str
    road_type: str | None = None
    postal_code: str | None = None

    def as_query(self) -> dict[str, str]:
        """Return the mapping of query parameters required by Catastro."""

        query = {
            "Provincia": self.province.strip(),
            "Municipio": self.municipality.strip(),
            "Calle": self.street.strip(),
            "Numero": self.number.strip(),
        }
        if self.road_type:
            query["Sigla"] = self.road_type.strip()
        return query


class ReferenceProvider(Protocol):
    """Minimal contract that any cadastral reference provider must follow."""

    def fetch(self, address: Address) -> Sequence[str]:
        """Return a list of possible cadastral references for ``address``."""


class CatastroProvider:
    """Client for the public Catastro "ConsultaRC" XML endpoint."""

    BASE_URL = (
        "https://www1.sedecatastro.gob.es/OVCServWeb/OVCSWLocalizacionRC/"
        "OVCSWLocalizacionRC.asmx"
    )

    #: Endpoints exposed by the ``.asmx`` service.  ``ConsultaRCByCalle`` is the
    #: documented method for single properties.  ``ConsultaRC`` is kept as a
    #: fallback because some deployments expose it as an alias.
    ENDPOINT_CANDIDATES = ("ConsultaRCByCalle", "ConsultaRC")

    def __init__(self, session: Optional[requests.Session] = None) -> None:
        self.session = session or requests.Session()

    def fetch(self, address: Address) -> Sequence[str]:
        last_error: Optional[Exception] = None
        for endpoint in self.ENDPOINT_CANDIDATES:
            try:
                xml_text = self._call_endpoint(endpoint, address.as_query())
            except Exception as exc:  # pragma: no cover - defensive logging
                last_error = exc
                LOGGER.debug("Catastro endpoint %s failed: %s", endpoint, exc)
                continue

            references = list(self._parse_references(xml_text))
            if references:
                return references
        if last_error:
            raise RuntimeError("Catastro service call failed") from last_error
        return []

    def _call_endpoint(self, endpoint: str, params: dict[str, str]) -> str:
        url = f"{self.BASE_URL}/{endpoint}"
        LOGGER.debug("Calling %s with %s", url, params)
        response = self.session.get(url, params=params, timeout=20)
        response.raise_for_status()
        return response.text

    @staticmethod
    def _parse_references(xml_text: str) -> Iterable[str]:
        """Extract cadastral reference codes from the XML payload."""

        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:  # pragma: no cover - upstream payload
            LOGGER.debug(
                "Invalid XML received from Catastro:\n%s",
                xml_text,
            )
            return []

        references: Set[str] = set()
        for element in root.iter():
            tag = element.tag.rsplit("}", 1)[-1]  # strip namespace if present
            if tag.lower() == "rc" and element.text:
                value = element.text.strip()
                if value:
                    references.add(value)
        return sorted(references)


class ReferenceAggregator:
    """Iterates through a collection of providers until one succeeds."""

    def __init__(self, providers: Sequence[ReferenceProvider]) -> None:
        if not providers:
            raise ValueError("At least one provider must be supplied")
        self._providers = providers

    def lookup(self, address: Address) -> Sequence[str]:
        for provider in self._providers:
            LOGGER.debug("Trying provider %s", provider.__class__.__name__)
            result = provider.fetch(address)
            if result:
                return result
        return []


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Obtén la referencia catastral a partir de una dirección",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(
            """
            Ejemplos:

            python scripts/cadastral_reference.py \\
                --province "Madrid" --municipality "Madrid" \\
                --street "Gran Vía" --number 1

            python scripts/cadastral_reference.py \\
                --province "Barcelona" --municipality "Badalona" \\
                --road-type "Av" --street "President Companys" --number 13
            """
        ),
    )
    parser.add_argument("--province", required=True, help="Provincia")
    parser.add_argument("--municipality", required=True, help="Municipio")
    parser.add_argument("--street", required=True, help="Nombre de la calle")
    parser.add_argument("--number", required=True, help="Número de portal")
    parser.add_argument(
        "--road-type",
        help="Sigla del tipo de vía (por ejemplo, CL, AV, PS)",
    )
    parser.add_argument(
        "--postal-code",
        help="Código postal (opcional, reservado para futuras integraciones)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Activa el modo debug para ver las peticiones HTTP",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO)

    address = Address(
        province=args.province,
        municipality=args.municipality,
        street=args.street,
        number=args.number,
        road_type=args.road_type,
        postal_code=args.postal_code,
    )

    aggregator = ReferenceAggregator([CatastroProvider()])
    references = aggregator.lookup(address)

    if not references:
        LOGGER.error("No se encontró ninguna referencia catastral")
        return 1

    for ref in references:
        print(ref)
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    sys.exit(main())
