"""Normalise shipping addresses to a governorate / emirate / region (stdlib only).

Uses ../assets/regions.json (27 Egyptian governorates plus UAE, KSA, Kuwait, Qatar,
Bahrain, Oman). Preview one address:
    python3 regions.py "<province>" "<city>" "<country code or name>"
Prints JSON: {"region": ..., "country": ..., "source": "province|province_code|city|none"}.
"""
import json, os, re, sys, unicodedata

_HERE = os.path.dirname(os.path.abspath(__file__))
_TABLE = os.path.join(_HERE, "..", "assets", "regions.json")

_STOP = {"governorate", "governate", "gov", "govt", "province", "prov", "emirate", "region",
         "state", "muhafazat", "mohafazat", "mohafza", "muhafaza", "district", "area",
         "محافظه", "منطقه", "اماره", "مدينه", "city"}
_ARTICLES = {"al", "el", "ad", "ar", "as", "ash", "an", "at", "az", "ed", "es", "ec"}
_AR_MAP = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ة": "ه", "ى": "ي",
                         "ؤ": "و", "ئ": "ي", "ـ": None})
_AR_DIAC = re.compile("[ً-ْٰ]")
_AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")


def _words(text):
    s = unicodedata.normalize("NFKC", str(text or "")).lower()
    s = _AR_DIAC.sub("", s).translate(_AR_MAP).translate(_AR_DIGITS)
    s = re.sub(r"[^\w]+", " ", s).replace("_", " ")
    out = []
    for w in s.split():
        if w.startswith("ال") and len(w) > 3:
            w = w[2:]
        out.append(w)
    return out


def keys(text):
    """Lookup keys for a value, strictest first: all words, then without filler words."""
    w = _words(text)
    full = "".join(w)
    trimmed = "".join(x for x in w if x not in _STOP and x not in _ARTICLES)
    seen, out = set(), []
    for k in (full, trimmed):
        if k and k not in seen:
            seen.add(k)
            out.append(k)
    return out


class Regions:
    def __init__(self, path=_TABLE):
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        self.countries = {}      # country key -> ISO code
        self.by_country = {}     # ISO -> {key: region}
        self.codes = {}          # ISO -> {CODE: region}
        self.names = {}          # ISO -> country name
        glob = {}
        for iso, c in data["countries"].items():
            self.names[iso] = c["name"]
            for a in c["aliases"] + [iso, c["name"]]:
                for k in keys(a):
                    self.countries[k] = iso
            idx, codes = {}, {}
            for r in c["regions"]:
                for code in r.get("codes", []):
                    codes[code.upper()] = r["name"]
                for a in [r["name"], r["ar"]] + r.get("aliases", []) + r.get("cities", []):
                    for k in keys(a):
                        idx.setdefault(k, r["name"])
                        glob.setdefault(k, set()).add((iso, r["name"]))
            self.by_country[iso] = idx
            self.codes[iso] = codes
        # Global index only keeps keys that point to one region in one country.
        self.glob = {k: list(v)[0] for k, v in glob.items() if len(v) == 1}

    def add_aliases(self, region, spellings):
        """Extra spellings for a region (setup region_aliases). False if the region is unknown."""
        target = keys(region)
        for iso, idx in self.by_country.items():
            name = next((r for r in set(idx.values()) if keys(r)[:1] == target[:1]), None)
            if name:
                for sp in spellings:
                    for k in keys(sp):
                        idx[k] = name
                        self.glob.setdefault(k, (iso, name))
                return True
        return False

    def country(self, value):
        for k in keys(value):
            if k in self.countries:
                return self.countries[k]
        return None

    def _lookup(self, value, iso):
        for k in keys(value):
            if iso:
                hit = self.by_country.get(iso, {}).get(k)
                if hit:
                    return iso, hit
            else:
                hit = self.glob.get(k)
                if hit:
                    return hit
        return None

    def resolve(self, province_name="", province_code="", city="", country=""):
        """Return (region, iso, source). region is None when nothing matched."""
        iso = self.country(country) if country else None
        if province_name:
            hit = self._lookup(province_name, iso)
            if hit:
                return hit[1], hit[0], "province"
        code = str(province_code or "").strip().upper()
        if code.startswith(((iso or "") + "-")) and iso:
            code = code[len(iso) + 1:]
        if code and iso and code in self.codes.get(iso, {}):
            return self.codes[iso][code], iso, "province_code"
        if code and not province_name:
            hit = self._lookup(code, iso)
            if hit:
                return hit[1], hit[0], "province"
        if city:
            hit = self._lookup(city, iso)
            if hit:
                return hit[1], hit[0], "city"
        return None, iso, "none"


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    a = sys.argv[1:] + ["", "", ""]
    reg, iso, src = Regions().resolve(province_name=a[0], city=a[1], country=a[2], province_code=a[0])
    print(json.dumps({"region": reg, "country": iso, "source": src}, ensure_ascii=False))
