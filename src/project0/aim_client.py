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


def post_to_aim(temperature_k: float, rh: float, species: Dict[str, float], solids: set | None = None, timeout: int = 30) -> str:
    """Submit the AIM form as if the user filled it and clicked the run button.

    Strategy:
    - Start a session and GET the model page to obtain the form and any hidden fields.
    - Auto-fill matching inputs (temperature, RH, species) using sensible name matching.
    - Include the first submit/button value so the server treats this like the Run click.
    - POST to the form action and return the resulting HTML.

    This avoids using Selenium while still replicating the site's form workflow.
    """
    sess = requests.Session()
    sess.headers.update(HEADERS)

    # GET the form page first to collect hidden fields and the real action URL
    r = sess.get(AIM_URL, timeout=timeout)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "lxml")
    form = soup.find("form")
    if not form:
        # fallback to a direct POST if no form found
        payload = build_payload(temperature_k, rh, species)
        resp = sess.post(AIM_URL, data=payload, timeout=timeout)
        resp.raise_for_status()
        return resp.text

    # Determine action URL
    action = form.get("action") or AIM_URL
    action_url = requests.compat.urljoin(AIM_URL, action)

    # Start with all existing input values
    payload: Dict[str, str] = {}
    # inputs
    for inp in form.find_all(["input", "select", "textarea"]):
        name = inp.get("name")
        if not name:
            continue
        # textarea: use its text as default
        if inp.name == "textarea":
            payload[name] = inp.get_text("\n")
            continue
        # select: prefer selected option
        if inp.name == "select":
            sel = inp.find("option", selected=True)
            if sel and sel.get("value") is not None:
                payload[name] = sel.get("value")
            else:
                # take first option value if present
                opt = inp.find("option")
                payload[name] = opt.get("value") if opt and opt.get("value") is not None else ""
            continue

        # input types
        itype = (inp.get("type") or "text").lower()
        if itype in ("checkbox", "radio"):
            if inp.has_attr("checked"):
                payload[name] = inp.get("value", "on")
            else:
                # leave unchecked inputs out
                continue
        else:
            payload[name] = inp.get("value", "")

    # Heuristically fill temperature and RH fields
    def match_name(n: str, patterns):
        nlow = n.lower()
        return any(p in nlow for p in patterns)

    for key in list(payload.keys()):
        if match_name(key, ["temp", "temperature", "t_"]) or key.lower() == "t":
            payload[key] = str(temperature_k)
        elif match_name(key, ["rh", "humid", "relative"]):
            payload[key] = str(rh)

    # The AIM form uses 'water_var' for Relative Humidity; set it and switch
    # the interactive type to RH mode (2) so the server uses RH rather than temp.
    if any(k.lower() == 'water_var' or 'water_var' in k.lower() or 'water' in k.lower() for k in payload):
        # prefer explicit water_var name
        if 'water_var' in payload:
            payload['water_var'] = str(rh)
        else:
            # set any water-like field
            for k in list(payload.keys()):
                if 'water' in k.lower():
                    payload[k] = str(rh)
                    break
        # set interactive_type to 2 (RH mode)
        payload['interactive_type'] = '2'

    # Attempt to place species values: match by exact name or common species input areas
    species_lines = "\n".join(f"{k} {v}" for k, v in species.items())
    placed = set()
    for sname in species.keys():
        for key in payload:
            if key.lower() == sname.lower():
                payload[key] = str(species[sname])
                placed.add(sname)
                break

    # If a textarea exists that looks like a species input, put species_lines there
    if species_lines and not placed:
        for inp in form.find_all("textarea"):
            name = inp.get("name")
            if not name:
                continue
            lname = name.lower()
            if any(p in lname for p in ("species", "conc", "concentration", "input")):
                payload[name] = species_lines
                placed = set(species.keys())
                break

    # If no textarea found, but there is a field named like 'species' or 'concs', use it
    if species_lines and not placed:
        for key in list(payload.keys()):
            if any(p in key.lower() for p in ("species", "conc", "concentration", "mole")):
                payload[key] = species_lines
                placed = set(species.keys())
                break

    # Ensure temperature/rh also in payload even if no matching field was found previously
    if not any(match_name(k, ["temp", "temperature", "t_"]) or k.lower() == "t" for k in payload):
        # add generic names
        payload.setdefault("Temperature", str(temperature_k))
        payload.setdefault("T", str(temperature_k))
    if not any(match_name(k, ["rh", "humid", "relative"]) for k in payload):
        payload.setdefault("RH", str(rh))

    # If requested, set checkbox/radio inputs matching solid species
    if solids:
        for inp in form.find_all("input"):
            itype = (inp.get("type") or "").lower()
            if itype in ("checkbox", "radio"):
                name = inp.get("name")
                if not name:
                    continue
                val = inp.get("value", "on")
                lname = (name or "").lower()
                lval = (val or "").lower()
                # try to find a label for this input
                label_text = ""
                iid = inp.get("id")
                if iid:
                    lab = form.find("label", attrs={"for": iid})
                    if lab:
                        label_text = lab.get_text(" ").lower()
                for s in solids:
                    s_low = s.lower()
                    if s_low in lname or s_low in lval or s_low in label_text:
                        payload[name] = val
                        break

    # Include a submit value by finding a submit/button element
    submit_added = False
    for btn in form.find_all(["input", "button"]):
        btype = (btn.get("type") or "").lower()
        if btype == "submit" or btn.name == "button":
            name = btn.get("name")
            val = btn.get("value") or btn.get_text(strip=True) or "Run"
            if name:
                payload[name] = val
                submit_added = True
                break
    if not submit_added:
        payload.setdefault("submit", "Run model")

    # Finally POST to the action URL
    resp = sess.post(action_url, data=payload, headers={"Referer": AIM_URL, **HEADERS}, timeout=timeout)
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


def run_and_parse(temperature_k: float, rh: float, species: Dict[str, float], solids: set | None = None) -> Dict[str, Any]:
    """High-level helper: post, extract <pre> text, parse, and return results.

    `solids` is an optional set of species names that should be checked
    on the remote form (solid-phase species checkboxes).
    """
    html = post_to_aim(temperature_k, rh, species, solids=solids)
    pre_text = extract_pre_text(html)
    return parse_aim_output(pre_text)
