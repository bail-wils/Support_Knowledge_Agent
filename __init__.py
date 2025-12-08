import logging
import os
import io
import json
import requests
import pandas as pd
import azure.functions as func
import shutil

# Import your existing parser module (ensure combined_csv_to_md.py is in the same folder)
import combined_csv_to_md as csv_md

# Environment variables to set in Function App settings:
# TENANT_ID, CLIENT_ID, CLIENT_SECRET, DRIVE_ID (optional), TARGET_FOLDER_ID

MS_TOKEN_URL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
GRAPH_BASE = "https://graph.microsoft.com/v1.0"


def get_app_token(tenant, client_id, client_secret):
    url = MS_TOKEN_URL.format(tenant=tenant)
    data = {
        'client_id': client_id,
        'scope': 'https://graph.microsoft.com/.default',
        'client_secret': client_secret,
        'grant_type': 'client_credentials'
    }
    r = requests.post(url, data=data)
    r.raise_for_status()
    return r.json()['access_token']


def download_file_from_onedrive(access_token, drive_id, item_path):
    url = f"{GRAPH_BASE}/drives/{drive_id}/root:/{item_path}:/content"
    r = requests.get(url, headers={'Authorization': f'Bearer {access_token}'}, stream=True)
    r.raise_for_status()
    return r.content


def upload_file_to_onedrive(access_token, drive_id, folder_id, filename, data_bytes):
    # Upload by path under folder id
    url = f"{GRAPH_BASE}/drives/{drive_id}/items/{folder_id}:/{filename}:/content"
    r = requests.put(url, headers={'Authorization': f'Bearer {access_token}', 'Content-Type': 'application/octet-stream'}, data=data_bytes)
    r.raise_for_status()
    return r.json()


def main(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('Azure Function: Received request to parse OneDrive report (using combined_csv_to_md)')

    try:
        body = req.get_json()
    except Exception:
        body = {}

    drive_id = body.get('driveId') or os.getenv('DRIVE_ID')
    item_path = body.get('itemPath')  # e.g., 'temp/report_raw_YYYYMMDD_HHMM.csv'

    tenant = os.getenv('TENANT_ID')
    client_id = os.getenv('CLIENT_ID')
    client_secret = os.getenv('CLIENT_SECRET')
    target_folder_id = os.getenv('TARGET_FOLDER_ID')

    if not (tenant and client_id and client_secret and drive_id and item_path and target_folder_id):
        return func.HttpResponse("Missing configuration or payload fields", status_code=400)

    # Acquire token
    try:
        token = get_app_token(tenant, client_id, client_secret)
    except Exception as e:
        logging.exception("Failed to acquire Graph token")
        return func.HttpResponse(f"Auth error: {e}", status_code=500)

    # Download the file content from OneDrive
    try:
        raw = download_file_from_onedrive(token, drive_id, item_path)
    except Exception as e:
        logging.exception("Failed to download file from OneDrive")
        return func.HttpResponse(f"Download error: {e}", status_code=500)

    # Save the downloaded bytes to a temporary input file (preserve extension if present)
    try:
        # derive filename from item_path
        base_name = os.path.basename(item_path)
        tmp_input_path = os.path.join("/tmp", base_name or "input_report.csv")
        with open(tmp_input_path, "wb") as f:
            f.write(raw)
    except Exception as e:
        logging.exception("Failed to write temp input file")
        return func.HttpResponse(f"Temp write error: {e}", status_code=500)

    # Create a temporary output folder and run the existing parser
    tmp_output_dir = os.path.join("/tmp", f"out_{os.path.splitext(base_name)[0]}")
    try:
        # Ensure the output folder is empty
        if os.path.exists(tmp_output_dir):
            shutil.rmtree(tmp_output_dir)
        os.makedirs(tmp_output_dir, exist_ok=True)

        # Use your existing processing function
        csv_md.process_file(tmp_input_path, tmp_output_dir)
    except Exception as e:
        logging.exception("Failed to parse file with combined_csv_to_md")
        return func.HttpResponse(f"Parse error: {e}", status_code=500)

    # Upload every file created in tmp_output_dir to OneDrive target folder
    uploaded = []
    try:
        for root, _, files in os.walk(tmp_output_dir):
            for fname in files:
                file_path = os.path.join(root, fname)
                with open(file_path, "rb") as fh:
                    content = fh.read()
                # Optionally, you could prefix folders inside OneDrive; here we upload directly
                try:
                    upload_file_to_onedrive(token, drive_id, target_folder_id, fname, content)
                    uploaded.append(fname)
                except Exception:
                    logging.exception(f"Failed to upload {fname} to OneDrive; continuing")
                    # continue with other files
    except Exception as e:
        logging.exception("Failed enumerating/uploading parsed files")
        return func.HttpResponse(f"Upload error: {e}", status_code=500)

    # Optionally cleanup tmp files (function host will purge /tmp eventually)
    try:
        shutil.rmtree(tmp_output_dir)
        os.remove(tmp_input_path)
    except Exception:
        # not critical; just log and continue
        logging.info("Cleanup of temp files failed or not needed")

    resp = {
        "uploaded": uploaded,
        "count": len(uploaded),
        "inputFile": base_name
    }
    return func.HttpResponse(json.dumps(resp), status_code=200, mimetype="application/json")
