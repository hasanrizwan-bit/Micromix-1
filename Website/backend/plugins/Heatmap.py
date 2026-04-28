import os


def main(parameters):
    upload_url = os.environ.get("HEATMAP_FRONTEND_URL", "http://127.0.0.1:8081/").rstrip("/")
    print("heatmap.py")
    print(parameters)
    return upload_url + '/?config=' + str(parameters["db_entry_id"])
