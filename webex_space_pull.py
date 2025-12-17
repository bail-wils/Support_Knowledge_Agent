
import requests
import json

access_token =  "NDNkMDQ4NDMtOTk5Ny00NDk0LTlkNGYtYTJhNzg4Y2U5ODA5MmViNDdlYzUtZWYz_PF84_1eb65fdf-9643-417f-9974-ad72cae0e10f" # Replace with your Personal Access Token

# to get room_id, you need to convert the space URL to base 64: echo -n 'ciscospark://us/ROOM/0a8ebef0-57f5-11e6-9562-91b08a890d87' | base64
room_id = "Y2lzY29zcGFyazovL3VzL1JPT00vNmFkZmIyMzAtYzE4Yy0xMWVjLTk4ZGEtNDVmYWQ4MTkwNmFh"  # Replace with the ID of the room you want to download
output_filename = "Umbrella_Product_dec11.txt"

url = f"https://webexapis.com/v1/messages?roomId={room_id}&max=100"
headers = {
    "Authorization": f"Bearer {access_token}",
    "Accept": "application/json"
}

all_messages = []
print(f"Fetching messages from room: {room_id}")

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
            
    print(f"\nSuccess! All messages have been downloaded to '{output_filename}'")

except Exception as e:
    print(f"An error occurred while writing to the file: {e}")
