import datetime
import re
from typing import Any

from absl import app
from absl import flags
import requests

_TAILNET = flags.DEFINE_string("tailnet",
                               None,
                               "Tailscale Tailnet",
                               required=True)
_API_KEY = flags.DEFINE_string("api_key",
                               None,
                               "Tailscale API Key",
                               required=True)
_OFFLINE_ONLY = flags.DEFINE_bool(
    "offline_only",
    True,
    "Only remove offline devices",
)

_OFFLINE_DURATION = flags.DEFINE_integer(
    "offline_duration",
    5,
    "Only remove devices that have been offline for this many minutes",
)

_REGEX = flags.DEFINE_string(
    "regex",
    None,
    "Only remove devices whose hostname matches this regex",
    required=True,
)

_API_ENDPOPINT = flags.DEFINE_string(
    "api_endpoint",
    "https://api.tailscale.com/api/v2",
    "Tailscale API Endpoint",
)


def api_call(uri: str, *, method: str, params: dict[str, Any] | None = None):
  url = f'{_API_ENDPOPINT.value}/{uri}'
  headers = {
      "Authorization": f"Bearer {_API_KEY.value}",
  }

  response = requests.get(url, params=params, headers=headers)
  response.raise_for_status()  # Raise an exception for bad status codes
  return response.json().get("devices", [])


def devices():
  return api_call(f'tailnet/{_TAILNET.value}/devices',
                  method='GET',
                  params={'fields': 'all'})


def main(argv):
  del argv  # Unused.
  regex = re.compile(_REGEX.value)
  pending_deletion = []
  for device in devices():
    print(f"Found device: {device['hostname']} (ID: {device['id']})")
    if not regex.search(device['hostname']):
      print(f'Skipping device {device["hostname"]} as it does not match regex')
      continue
    if _OFFLINE_ONLY.value:
      last_seen_str = device.get('lastSeen')
      if not last_seen_str:
        print(
            f'Skipping device {device["hostname"]} as it has never been online')
        continue
      last_seen = datetime.datetime.fromisoformat(
          last_seen_str.replace('Z', '+00:00'))
      offline_duration = datetime.datetime.now(
          datetime.timezone.utc) - last_seen
      offline_minutes = offline_duration.total_seconds() / 60
      if offline_minutes < _OFFLINE_DURATION.value:
        print(
            f'Skipping device {device["hostname"]} as it has been offline for only {offline_minutes:.1f} minutes'
        )
        continue
    pending_deletion.append(device)
  print(f'Found {len(pending_deletion)} devices pending deletion')
  for device in pending_deletion:
    print(f" - {device['hostname']} (ID: {device['id']})")
    last_seen_str = device.get("lastSeen")
    if last_seen_str:
      last_seen = datetime.datetime.fromisoformat(
          last_seen_str.replace('Z', '+00:00'))
      hours_ago = (datetime.datetime.now(datetime.timezone.utc) -
                   last_seen).total_seconds() / 3600
      print(f'   Last seen: {hours_ago:.2f} hours ago')
    else:
      print('   Last seen: never')

  confirm = input('Are you sure you want to delete these devices? (y/N) ')
  if confirm.lower() != 'y':
    print('Aborting')
    return
  for device in pending_deletion:
    device_id = device['nodeId']
    hostname = device['hostname']
    print(f'Removing device {hostname} with ID {device_id}')
    response = requests.delete(f'{_API_ENDPOPINT.value}/device/{device_id}',
                               headers={
                                   "Authorization": f"Bearer {_API_KEY.value}",
                               })
    if response.status_code == 200 or response.status_code == 204:
      print(f'Successfully removed device {hostname} with ID {device_id}')
    else:
      print(
          f'Failed to remove device {hostname} with ID {device_id}: {response.status_code} {response.text}'
      )


if __name__ == "__main__":
  app.run(main)
