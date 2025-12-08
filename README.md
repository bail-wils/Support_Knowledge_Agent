
Azure Function: OneDrive CSV parser and uploader
===============================================

Contents:
- __init__.py         -> Function code (HTTP-triggered)
- requirements.txt    -> Python dependencies
- function.json       -> Function binding configuration
- host.json           -> Host config (minimal)
- README.md           -> This file

Setup (quick):
1. Create an Azure Function (Python) in a Function App (consumption or premium).
2. Deploy these files into a function folder named e.g. 'ParseReport'.
3. Configure the following Application Settings (Environment variables) in Function App settings:
   - TENANT_ID
   - CLIENT_ID
   - CLIENT_SECRET
   - DRIVE_ID            (OneDrive drive id for the user's drive or SharePoint drive)
   - TARGET_FOLDER_ID    (Target folder item id where parsed files will be uploaded)
   - LAST_PROCESSED_BLOB_NAME (optional; used locally in demo to store lastProcessed timestamp)
4. Register an Azure AD application and grant it Microsoft Graph 'Files.ReadWrite.All' (application permission) and grant admin consent.
5. (Optional) Use Azure Key Vault and Managed Identity instead of storing client secret directly.
6. In Power Automate, create a flow that uploads the raw report to the OneDrive temp folder and calls this Function (POST) with JSON body:
   {
     "driveId": "<drive-id>",
     "itemPath": "temp/report_raw_YYYYMMDD_HHMM.csv"
   }
