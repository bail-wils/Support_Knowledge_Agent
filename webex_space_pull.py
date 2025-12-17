
import requests
import json

access_token =  "MmQ1OWFiODQtODk4Ny00MjdhLTk0MDktN2NkOTVmNGI0YjdiMDEzNWVlNWUtOTBl_PF84_1eb65fdf-9643-417f-9974-ad72cae0e10f" # Replace with your Personal Access Token

# to get room_id, you need to convert the space URL to base 64: echo -n 'ciscospark://us/ROOM/0a8ebef0-57f5-11e6-9562-91b08a890d87' | base64
room_ids = {
    "UI-Products": "Y2lzY29zcGFyazovL3VzL1JPT00vMGZlOTIzNDAtNTdmNS0xMWU2LTk3MWQtOTM2OGZjMDZjYTkw",
    "MR-Products": "Y2lzY29zcGFyazovL3VzL1JPT00vY2EzYTM3ZjAtY2JjZC0xMWVjLTljY2MtNjNhYWRiMmQxZDY2",
    "MS_Classic-Products": "Y2lzY29zcGFyazovL3VzL1JPT00vMGJiZDA1YzAtNTdmNS0xMWU2LWIyYTMtYjllNjYyYWY1OGUx",
    "Catalyst_Wireless_Product": "Y2lzY29zcGFyazovL3VzL1JPT00vYjc1ZDBmYjAtMWQ5Ny0xMWVkLTllZDQtYTNhMmZiNWUwOTli",
    "Cloud Monitoring/Catalyst_Switching_Product": "Y2lzY29zcGFyazovL3VzL1JPT00vYzY3NjRhYzAtZTZhYi0xMWVjLThjMTAtMjFkZGY1YzE1OGFj",
    "Cisco_Access_Manager_Products": "Y2lzY29zcGFyazovL3VzL1JPT00vYmVhZWY1NDAtZmY0OC0xMWVmLWEwODUtYzU5NjNmM2IyY2Fh",
    "Cisco_Access_Manager": "Y2lzY29zcGFyazovL3VzL1JPT00vZWZkMzVkNjAtMzZmOC0xMWVlLTg3OTgtZjVlNTczNjNjOTI3",
    "Umbrella_Meraki_Support_Collaboration": "Y2lzY29zcGFyazovL3VzL1JPT00vNmFkZmIyMzAtYzE4Yy0xMWVjLTk4ZGEtNDVmYWQ4MTkwNmFh",
    "API": "Y2lzY29zcGFyazovL3VzL1JPT00vMTE4ZDVkNjAtNTdmNS0xMWU2LTk5MzktNzM3ZTA0NmZhYzU5",
    "CNHE_Support_Space_CSC": "Y2lzY29zcGFyazovL3VzL1JPT00vZjhmZjkzMzAtODFlYi0xMWVkLWFiODctMjFmNThmMjEwZDI1",
    }

headers = {
    "Authorization": f"Bearer {access_token}",
    "Accept": "application/json"
}

for name, id in room_ids.items():
    output_filename = f"{name}.txt"
    url = f"https://webexapis.com/v1/messages?roomId={id}&max=100"

    all_messages = []
    print(f"\nFetching messages from room: {id}")

    while url:
        response = requests.get(url, headers=headers)
        
        if response.status_code == 200:
            data = response.json()
            messages = data.get("items", [])
            all_messages.extend(messages)
            
            # Check for the 'next' link in the response headers for pagination
            url = response.links.get('next', {}).get('url')
            if url:
                print("Fetching next page of messages...")
        else:
            print(f"Error fetching messages: {response.status_code}")
            print(response.text)
            break

    # Reverse the list so messages are in chronological order (oldest first)
    all_messages.reverse()

    # Save the messages to a file
    try:
        with open(output_filename, "w", encoding="utf-8") as f:
            for msg in all_messages:
                # Format the output line
                timestamp = msg.get("created", "No Timestamp")
                sender = msg.get("personEmail", "Unknown Sender")
                content = msg.get("text", "[This message has no text, it might be a file or a GIF]")
                
                f.write(f"[{timestamp}] {sender}:\n")
                f.write(f"{content}\n")
                f.write("-" * 20 + "\n")
                
        print(f"Success! All messages have been downloaded to '{output_filename}'")

    except Exception as e:
        print(f"An error occurred while writing to the file: {e}")
