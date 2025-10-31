#!/usr/bin/env python3
"""Utility to fetch cadastral data for a Spanish address.

The script communicates with the Catastro street index (callejero) web
service to resolve an address to a cadastral reference and then retrieves
building statistics for that reference.  The extracted figures are
returned as JSON on stdout.

Due to the amount of heuristics involved when extracting the desired
statistics, the script focuses on the values requested in the exercise:

* Superficie construida (huella)
* Superficie oficial total
* Perímetro
* Plantas
* Número de viviendas

Example usage::

    python catastro.py "av de españa 73, valdemoro"

The script only depends on the standard library so it can be executed in
restricted environments.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple, Union
from urllib.parse import urlencode
from urllib.request import Request, urlopen

BASE_URL = "https://ovc.catastro.meh.es/OVCServWeb/OVCWcfCallejero/COVCCallejero.svc/json"
USER_AGENT = "catastro-cli/1.0"
HTTP_TIMEOUT = 15

JsonDict = Dict[str, "Json"]
Json = Union[JsonDict, List["Json"], str, int, float, None]


class CatastroError(RuntimeError):
    """Raised when the Catastro services respond with an unexpected payload."""


@dataclass
class AddressParts:
    street: str
    number: str
    municipality: str
    province: Optional[str]


@dataclass
class CadastralDetails:
    referencia_catastral: str
    superficie_construida_huella_m2: Optional[float]
    superficie_oficial_total_m2: Optional[float]
    perimetro_m: Optional[float]
    plantas: Optional[int]
    numero_viviendas: Optional[int]

    def as_json(self) -> Dict[str, Union[str, float, int, None]]:
        return {
            "referencia_catastral": self.referencia_catastral,
            "superficie_construida_huella_m2": self.superficie_construida_huella_m2,
            "superficie_oficial_total_m2": self.superficie_oficial_total_m2,
            "perimetro_m": self.perimetro_m,
            "plantas": self.plantas,
            "numero_viviendas": self.numero_viviendas,
        }


# ---------------------------------------------------------------------------
# HTTP helpers


def _request_json(path: str, params: Optional[Dict[str, str]] = None) -> JsonDict:
    url = f"{BASE_URL}/{path}"
    if params:
        url = f"{url}?{urlencode(params)}"
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=HTTP_TIMEOUT) as response:
        payload = response.read().decode("utf-8")
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive
        raise CatastroError(f"Respuesta no válida del servicio {path!r}") from exc
    if not isinstance(data, dict):  # pragma: no cover - defensive
        raise CatastroError(f"Respuesta inesperada del servicio {path!r}")
    return data


def _ensure_list(value: Union[List[Json], Dict[str, Json], None]) -> List[JsonDict]:
    if value is None:
        return []
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        return [value]
    return []


# ---------------------------------------------------------------------------
# Address resolution


def parse_address(raw: str) -> AddressParts:
    """Split the free-form address into components."""

    # Basic heuristic-based parsing.  We expect formats similar to
    # "calle nombre 12, municipio" or "calle nombre 12, municipio, provincia".
    pattern = re.compile(
        r"\s*(?P<street>[\w\-\.\u00C0-\u017F\s]+?)\s+"
        r"(?P<number>\d+[A-Za-z0-9\-\\/]*)\s*,\s*"
        r"(?P<municipality>[\w\-\.\u00C0-\u017F\s]+?)"
        r"(?:\s*,\s*(?P<province>[\w\-\.\u00C0-\u017F\s]+))?\s*$",
        re.IGNORECASE,
    )
    match = pattern.match(raw)
    if not match:
        raise ValueError(
            "No se pudo interpretar la dirección. Usa el formato 'vía número, municipio[, provincia]'."
        )
    parts = match.groupdict()
    return AddressParts(
        street=parts["street"].strip(),
        number=parts["number"].strip(),
        municipality=parts["municipality"].strip(),
        province=(parts.get("province") or None),
    )


def find_province(municipality: str, preferred: Optional[str] = None) -> Tuple[str, str]:
    """Return the province and canonical municipality name for the given municipality."""

    provinces = _request_json("ConsultaProvincia").get("provinciero", [])
    if not isinstance(provinces, list):
        raise CatastroError("Lista de provincias no disponible")

    matches: List[Tuple[str, str]] = []
    preferred_lower = preferred.lower() if preferred else None

    for province_info in provinces:
        if not isinstance(province_info, dict):
            continue
        province_name = province_info.get("np")
        if not isinstance(province_name, str):
            continue
        if preferred_lower and preferred_lower not in province_name.lower():
            # Skip this province unless the preferred hint matches.
            continue
        muni_response = _request_json(
            "ConsultaMunicipio",
            {"Provincia": province_name, "Municipio": municipality},
        )
        for muni_info in _ensure_list(muni_response.get("municipiero")):
            muni_name = muni_info.get("nm")
            if not isinstance(muni_name, str):
                continue
            if municipality.lower() in muni_name.lower():
                matches.append((province_name, muni_name))

    if not matches:
        # If the hint filtered out every province, retry without filtering.
        if preferred_lower:
            return find_province(municipality, preferred=None)
        raise CatastroError("Municipio no encontrado en el callejero del Catastro")

    # Prefer an exact match when multiple results are returned.
    exact = [item for item in matches if item[1].lower() == municipality.lower()]
    if exact:
        return exact[0]
    return matches[0]


def find_street(province: str, municipality: str, street_query: str) -> Tuple[str, str]:
    """Resolve the requested street and return its (tipo, nombre) pair."""

    response = _request_json(
        "ConsultaVia",
        {"Provincia": province, "Municipio": municipality, "NombreVia": street_query},
    )
    for via_info in _ensure_list(response.get("callejero")):
        dir_info = via_info.get("dir")
        if isinstance(dir_info, dict):
            tipo = dir_info.get("tv")
            nombre = dir_info.get("nv")
            if isinstance(tipo, str) and isinstance(nombre, str):
                return tipo, nombre
    raise CatastroError("No se encontró la vía solicitada en el Catastro")


def find_reference(
    province: str, municipality: str, tipo_via: str, nombre_via: str, number: str
) -> str:
    """Return the cadastral reference (RC) for the provided door number."""

    response = _request_json(
        "ConsultaNumero",
        {
            "Provincia": province,
            "Municipio": municipality,
            "TipoVia": tipo_via,
            "NombreVia": nombre_via,
            "Numero": number,
        },
    )
    for entry in _ensure_list(response.get("numerero")):
        nump = entry.get("nump")
        if not isinstance(nump, dict):
            continue
        pc = nump.get("pc")
        if isinstance(pc, dict):
            pc1 = pc.get("pc1")
            pc2 = pc.get("pc2")
            if isinstance(pc1, str) and isinstance(pc2, str):
                return f"{pc1}{pc2}"
    raise CatastroError("No se encontró la referencia catastral para el número indicado")


# ---------------------------------------------------------------------------
# Building statistics


def _pick_first(data: Dict[str, Json], keys: Iterable[str]) -> Optional[Json]:
    for key in keys:
        value = data.get(key)
        if value not in (None, ""):
            return value
    return None


def _to_float(value: Json) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.strip().replace(".", "").replace(",", ".")
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def _to_int(value: Json) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(round(value))
    if isinstance(value, str):
        cleaned = re.sub(r"[^0-9]", "", value)
        if not cleaned:
            return None
        try:
            return int(cleaned)
        except ValueError:
            return None
    return None


def fetch_building_statistics(rc: str) -> CadastralDetails:
    """Fetch building statistics for the given cadastral reference."""

    response = _request_json("Consulta_DNPRC", {"RefCat": rc})
    bico = response.get("bico")
    if not isinstance(bico, dict):
        raise CatastroError("Información de inmueble no disponible para la referencia")
    bi = bico.get("bi")
    if not isinstance(bi, dict):
        raise CatastroError("Datos básicos del inmueble no disponibles")

    debi = bi.get("debi") if isinstance(bi.get("debi"), dict) else {}

    # Try to extract the requested statistics with a combination of known keys
    # and fallbacks.
    superficie_total = _to_float(
        _pick_first(
            debi,
            (
                "sfc",  # superficie construida total
                "sft",  # superficie total
                "stl",  # superficie total literal
                "stc",
            ),
        )
    )

    perimetro = _to_float(_pick_first(debi, ("perim", "per", "pr")))
    plantas = _to_int(_pick_first(debi, ("npl", "np", "npplanta", "nplanta")))
    numero_viviendas = _to_int(
        _pick_first(
            debi,
            (
                "nuv",  # numero de viviendas
                "nv",  # viviendas
                "nvi",
                "ncv",
            ),
        )
    )

    # Constructed surface on ground floor may not be explicitly provided. We
    # try to infer it from the list of constructions.
    superficie_huella = _to_float(_pick_first(debi, ("sfc1", "sfc_con", "spr")))

    cons_entries: List[JsonDict] = []
    lcons = bi.get("lcons")
    if isinstance(lcons, dict):
        cons_entries = _ensure_list(lcons.get("cons"))
    elif isinstance(lcons, list):
        cons_entries = [item for item in lcons if isinstance(item, dict)]

    sum_total = 0.0
    ground_candidates: List[Tuple[str, float]] = []
    dwellings_sum = 0

    for cons in cons_entries:
        dt = cons.get("dt") if isinstance(cons.get("dt"), dict) else cons
        if not isinstance(dt, dict):
            continue
        area = _to_float(
            _pick_first(
                dt,
                (
                    "sprcons",
                    "sfc",
                    "stl",
                    "sfc_con",
                    "scons",
                ),
            )
        )
        if area:
            sum_total += area
        level = _pick_first(
            dt,
            (
                "npcons",
                "planta",
                "np",
                "npp",
                "cod_planta",
            ),
        )
        level_str = str(level).upper() if level is not None else ""
        if area and level_str in {"0", "00", "PB", "BJ", "BAJA", "PLANTA BAJA"}:
            ground_candidates.append((level_str, area))
        dwellings = _to_int(_pick_first(dt, ("nuv", "nv", "nvi", "nviv")))
        if dwellings:
            dwellings_sum += dwellings

    if superficie_total is None and sum_total:
        superficie_total = sum_total

    if superficie_huella is None and ground_candidates:
        # Prefer the first candidate; if multiple floors labelled as ground are
        # available, use the one with the largest area.
        superficie_huella = max(ground_candidates, key=lambda item: item[1])[1]

    if numero_viviendas is None and dwellings_sum:
        numero_viviendas = dwellings_sum

    if plantas is None and cons_entries:
        plantas = len({
            str(
                _pick_first(
                    (cons.get("dt") if isinstance(cons.get("dt"), dict) else cons) or {},
                    ("npcons", "planta", "np", "npp", "cod_planta"),
                )
            ).upper()
            for cons in cons_entries
            if cons
        })

    return CadastralDetails(
        referencia_catastral=rc,
        superficie_construida_huella_m2=superficie_huella,
        superficie_oficial_total_m2=superficie_total,
        perimetro_m=perimetro,
        plantas=plantas,
        numero_viviendas=numero_viviendas,
    )


# ---------------------------------------------------------------------------
# Command line interface


def run_cli(argv: List[str]) -> int:
    if len(argv) < 2:
        address = "av de españa 73, valdemoro"
    else:
        address = argv[1]

    try:
        parts = parse_address(address)
        province_hint = parts.province
        province, municipality = find_province(parts.municipality, preferred=province_hint)
        tipo_via, nombre_via = find_street(province, municipality, parts.street)
        rc = find_reference(province, municipality, tipo_via, nombre_via, parts.number)
        stats = fetch_building_statistics(rc)
    except (ValueError, CatastroError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2))
        return 1

    print(json.dumps(stats.as_json(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(run_cli(sys.argv))
