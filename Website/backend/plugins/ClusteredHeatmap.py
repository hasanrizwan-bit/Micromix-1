import os


def main(parameters):
    upload_url = os.environ.get("CLUSTERED_HEATMAP_FRONTEND_URL", "http://127.0.0.1:8082/").rstrip("/")
    print("clustered_heatmap.py")
    print(parameters)
    return upload_url + '/?config=' + str(parameters["db_entry_id"])
