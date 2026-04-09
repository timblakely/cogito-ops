import json
import os

with open('/home/tim/git/cogito/content.json', 'r') as f:
    data = json.load(f)

for item in data:
    if 'tag_name' in item:
        print(f"Release: {item['tag_name']}")
        print(item.get('body', ''))
        print('-'*40)
