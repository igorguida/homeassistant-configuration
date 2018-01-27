"""
Support for RelayMaster inputs.
For more details about this platform, please refer to the documentation at
https://home-assistant.io/components/sensor.relaymaster/
"""

import logging
import xml.etree.ElementTree as ET
from datetime import timedelta

import requests
import voluptuous as vol

from homeassistant.const import (CONF_URL, CONF_USERNAME, CONF_PASSWORD)
from homeassistant.components.binary_sensor import (BinarySensorDevice,
                                                    PLATFORM_SCHEMA)
from homeassistant.util import Throttle
import homeassistant.helpers.config_validation as cv

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(seconds=1)
MIN_TIME_BETWEEN_UPDATES = timedelta(milliseconds=100)

CONF_MAX_NUMBER = 'max_number'
CONF_IGNORE_UNUSED = 'ignore_unused'
DEVICE_CONFIG_ENDPOINT = '/ioconf.xml'
DEVICE_STATE_ENDPOINT = '/ajax.xml'
UNUSED_INPUT_REGEX = '^(ANINP|INPUT)_[0-9]+_'
INPUT_NODE_REGEX = '^i([0-9]+)$'
INPUT_NODE = 'i{}'

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Required(CONF_URL): cv.url,
    vol.Required(CONF_USERNAME): cv.string,
    vol.Required(CONF_PASSWORD): cv.string,
    vol.Optional(CONF_MAX_NUMBER, default=12): cv.positive_int,
    vol.Optional(CONF_IGNORE_UNUSED, default=True): cv.boolean
})


# pylint: disable=unused-argument
def setup_platform(hass, config, add_devices, discovery_info=None):
    """Set up the relay board inputs."""
    import re

    max_number = config.get(CONF_MAX_NUMBER)
    ignore = config.get(CONF_IGNORE_UNUSED)
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

    inputs = []

    for child in ET.fromstring(response.text):
        match = re.search(INPUT_NODE_REGEX, child.tag)
        if not match:
            continue
        number = int(match.group(1))
        if number > max_number:
            continue
        if ignore and re.match(UNUSED_INPUT_REGEX, child.text):
            continue
        inputs.append(RelayMasterInput(board, number, child.text))

    add_devices(inputs)

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

class RelayMasterInput(BinarySensorDevice):
    """Representation of a RelayMaster input."""

    def __init__(self, board, number, name):
        """Initialize the input."""
        self._board = board
        self._number = number
        self._name = name
        self._state = None

    @property
    def name(self):
        """Return the name of the input."""
        return self._name.replace(".", " ").title()

    @property
    def is_on(self):
        """Return the state of the input."""
        return self._state

    def update(self):
        """Update the state of the input."""
        self._board.update()

        tag = INPUT_NODE.format(self._number)
        for child in self._board.data:
            if child.tag == tag:
                self._state = child.text == "up"
                break
