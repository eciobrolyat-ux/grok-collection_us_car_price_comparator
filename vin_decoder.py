import requests

def decode_vin_nhtsa(vin: str) -> dict:
    url = f"https://vpic.nhtsa.dot.gov/api/vehicles/decodevinvalues/{vin}?format=json"
    r = requests.get(url)
    r.raise_for_status()
    results = r.json().get("Results") or []
    if not results:
        raise ValueError(f"NHTSA returned no results for VIN {vin}")
    data = results[0]
    return {
        "trim": data.get("Trim", ""),
        "series": data.get("Series", ""),
        "body_class": data.get("BodyClass", ""),
        "engine": data.get("EngineModel", ""),
        "drive_type": data.get("DriveType", "")
    }
