"""
Support for RelayMaster relay control boards.
For more details about this platform, please refer to the documentation at
https://home-assistant.io/components/switch.relaymaster/
"""

import logging
import xml.etree.ElementTree as ET
from datetime import timedelta

import requests
import voluptuous as vol

from homeassistant.components.switch import (SwitchDevice, PLATFORM_SCHEMA)
from homeassistant.const import (CONF_URL, CONF_USERNAME, CONF_PASSWORD)
from homeassistant.util import Throttle
import homeassistant.helpers.config_validation as cv

_LOGGER = logging.getLogger(__name__)

DEVICE_CONFIG_ENDPOINT = '/ioconf.xml'
DEVICE_STATE_ENDPOINT = '/ajax.xml'
RELAY_TOGGLE_ENDPOINT = '/cgi/relays.cgi'
OUTPUT_NODE_REGEX = '^o[0-9]+$'
RELAY_NODE = 'r{}'
MIN_TIME_BETWEEN_UPDATES = timedelta(seconds=1)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Required(CONF_URL): cv.url,
    vol.Required(CONF_USERNAME): cv.string,
    vol.Required(CONF_PASSWORD): cv.string
})


# pylint: disable=unused-argument
def setup_platform(hass, config, add_devices, discovery_info=None):
    """Set up the relay board switches."""
    import re

    base_url = config.get(CONF_URL).rstrip('/')
    username = config.get(CONF_USERNAME)
    password = config.get(CONF_PASSWORD)

    session = requests.Session()
    session.auth = requests.auth.HTTPBasicAuth(username, password)
    board = RelayMasterBoard(session, base_url)

    response = None
    try:
        response = board.get(DEVICE_CONFIG_ENDPOINT)
    except requests.exceptions.MissingSchema:
        _LOGGER.error("Missing resource or schema in configuration. "
                      "Add http:// to your URL")
        return False

    if response is None:
        return False

    relays = []

    for child in ET.fromstring(response.text):
        if not re.match(OUTPUT_NODE_REGEX, child.tag):
            continue
        config = child.text.split(';')
        name = config[0]
        pair = (int(config[10]), int(config[11]))
        if pair[0] == 0:
            continue
        if pair[1] != 0:
            relays.append(RelayMasterRelay(board, pair[0], name + ' A'))
            relays.append(RelayMasterRelay(board, pair[1], name + ' B'))
        else:
            relays.append(RelayMasterRelay(board, pair[0], name))

    add_devices(relays)

class RelayMasterBoard(object):
    """Representation of board state."""

    def __init__(self, session, base_url):
        """Initialize the board object."""
        self._session = session
        self._base_url = base_url
        self.data = None

    @Throttle(MIN_TIME_BETWEEN_UPDATES)
    def update(self):
        """Update the board data."""
        response = self.get(DEVICE_STATE_ENDPOINT)
        if response is None:
            return

        self.data = ET.fromstring(response.text)

    def get(self, endpoint, params=None):
        """Send request to board."""
        url = self._base_url + endpoint
        response = None

        try:
            response = self._session.get(url, timeout=10, params=params)
        except requests.exceptions.ConnectionError:
            _LOGGER.warning("No route to device %s", self._base_url)
            return None

        if response.status_code != 200:
            _LOGGER.warning("Request error for %s: %s",
                            response.url, response.text)
            return None

        return response

class RelayMasterRelay(SwitchDevice):
    """Representation of a RelayMaster relay."""

    def __init__(self, board, number, name):
        """Initialize the switch."""
        self._board = board
        self._number = number
        self._name = name
        self._state = None

    @property
    def name(self):
        """Return the name of the relay."""
        return self._name.replace(".", " ").title()

    @property
    def is_on(self):
        """Return true if relay is on."""
        return self._state

    def turn_on(self, **kwargs):
        """Switch the relay on."""
        if self._state:
            return

        response = self._board.get(RELAY_TOGGLE_ENDPOINT,
                                   params={'rel': self._number})
        if response is None:
            return

        self._state = True

    def turn_off(self, **kwargs):
        """Switch the relay off."""
        if not self._state:
            return

        response = self._board.get(RELAY_TOGGLE_ENDPOINT,
                                   params={'rel': self._number})
        if response is None:
            return

        self._state = False

    def update(self):
        """Update the state of the relay."""
        self._board.update()

        for child in self._board.data:
            if child.tag == RELAY_NODE.format(self._number):
                self._state = int(child.text) == 1
                break
