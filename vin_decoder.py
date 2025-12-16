import requests

def decode_vin_nhtsa(vin: str) -> dict:
    url = f"https://vpic.nhtsa.dot.gov/api/vehicles/decodevinvalues/{vin}?format=json"
    data = requests.get(url).json()["Results"][0]
    return {
        "trim": data.get("Trim", ""),
        "series": data.get("Series", ""),
        "body_class": data.get("BodyClass", ""),
        "engine": data.get("EngineModel", ""),
        "drive_type": data.get("DriveType", "")
    }
