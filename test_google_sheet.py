import os
import gspread

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow


SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

SPREADSHEET_ID = "1Hzy2fWYd8pfVttOinSPZz3fxgQEqxnuFleBu1nYrR_E"
WORKSHEET_NAME = "Sheet1"


def get_gspread_client():
    creds = None

    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                "credentials.json",
                SCOPES,
            )
            creds = flow.run_local_server(port=0)

        with open("token.json", "w") as token:
            token.write(creds.to_json())

    return gspread.authorize(creds)


client = get_gspread_client()

spreadsheet = client.open_by_key(SPREADSHEET_ID)

print("Connected to:", spreadsheet.title)
print("Worksheets:")
for ws in spreadsheet.worksheets():
    print("-", ws.title)