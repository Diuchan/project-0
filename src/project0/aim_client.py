"""Simple AIM (model2a.php) client using requests and a text parser.

This module posts form-like data to the AIM URL and parses the returned
plain-text `<pre>` block using BeautifulSoup + regex to extract key values.

Note: The exact form field names required by the remote site may differ.
This client attempts a generic mapping (temperature, RH, and species keys).
If the remote form uses different names you can update `build_payload`.
"""
from typing import Dict, Any
import requests
from bs4 import BeautifulSoup
import re


AIM_URL = "https://www.aim.env.uea.ac.uk/aim/model2/model2a.php"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36"
    )
}


def build_payload(temperature_k: float, rh: float, species: Dict[str, float]) -> Dict[str, Any]:
    """Create a payload dict suitable for the AIM form.

    The real site may use field names other than these; adjust if needed.
    """
    payload: Dict[str, Any] = {
        # common sensible names - adjust these to match the live form if needed
        "Temperature": str(temperature_k),
        "T": str(temperature_k),
        "RH": str(rh),
    }
    # Add species concentrations directly (e.g. 'Na+' : '0.1')
    for k, v in species.items():
        payload[str(k).strip()] = str(v)
    # Some servers expect a submit key
    payload.setdefault("submit", "Run model")
    return payload


def post_to_aim(temperature_k: float, rh: float, species: Dict[str, float], timeout: int = 30) -> str:
    """POST data to the AIM endpoint and return the response text.

    Raises requests.RequestException on network/HTTP errors.
    """
    payload = build_payload(temperature_k, rh, species)
    resp = requests.post(AIM_URL, data=payload, headers=HEADERS, timeout=timeout)
    resp.raise_for_status()
    return resp.text


def extract_pre_text(html: str) -> str:
    """Return the contents of the first <pre> block if present, else whole text."""
    soup = BeautifulSoup(html, "lxml")
    pre = soup.find("pre")
    if pre:
        return pre.get_text(separator="\n")
    return soup.get_text(separator="\n")


_NUMBER = r"[+-]?\d*\.?\d+(?:[Ee][+-]?\d+)?"


def parse_aim_output(text: str) -> Dict[str, Any]:
    """Parse the AIM plain-text output and extract a dictionary of results.

    The function looks for common items: Total Gibbs Free Energy, pH and
    tabular molarities. It returns a dict with simple keys and a nested
    'molarities' dict when species values are found.
    """
    results: Dict[str, Any] = {}
    # Normalize whitespace
    txt = text

    # Total Gibbs Free Energy (common wording variations handled case-insensitively)
    m = re.search(rf"(?mi)total\s+gibbs[^:=\n]*[:=]\s*({_NUMBER})", txt)
    if m:
        results["Total Gibbs Free Energy"] = float(m.group(1))

    # pH
    m = re.search(rf"(?mi)\bph\b[^:=\n]*[:=]\s*({_NUMBER})", txt)
    if m:
        try:
            results["pH"] = float(m.group(1))
        except ValueError:
            results["pH"] = m.group(1)

    # Capture simple name/value lines which often represent molarities.
    molarities: Dict[str, float] = {}
    for line in txt.splitlines():
        line = line.strip()
        if not line:
            continue
        # look for lines like: H+    1.23E-07
        m = re.match(rf"^([A-Za-z0-9_+\-()\[\]/]+)\s+({_NUMBER})$", line)
        if m:
            name = m.group(1)
            val = float(m.group(2))
            molarities[name] = val

    if molarities:
        results["molarities"] = molarities

    # If nothing was found, keep a small excerpt so callers can show the raw text
    if not results:
        results["raw"] = txt[:2000]

    return results


def run_and_parse(temperature_k: float, rh: float, species: Dict[str, float]) -> Dict[str, Any]:
    """High-level helper: post, extract <pre> text, parse, and return results."""
    html = post_to_aim(temperature_k, rh, species)
    pre_text = extract_pre_text(html)
    return parse_aim_output(pre_text)
