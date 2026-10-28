import os
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/drive"]

def main():
    if not os.path.exists("credentials.json"):
        print("ERROR: credentials.json not found!")
        return

    flow = InstalledAppFlow.from_client_secrets_file(
        "credentials.json",
        SCOPES
    )

    print("Opening Google authorization...")
    creds = flow.run_local_server(
        host="127.0.0.1",
        port=0,
        open_browser=False
    )

    service = build("drive", "v3", credentials=creds)

    # Save the token locally for future API requests
    with open("token.json", "w") as token_file:
        token_file.write(creds.to_json())

    results = service.files().list(
        q="trashed = false and mimeType = 'application/vnd.google-apps.folder'",
        pageSize=10,
        fields="files(id, name)"
    ).execute()

    print("\nGoogle Drive connected successfully!")
    print("Folders visible to the app:")

    for folder in results.get("files", []):
        print(f"- {folder['name']} (ID: {folder['id']})")

if __name__ == "__main__":
    main()
