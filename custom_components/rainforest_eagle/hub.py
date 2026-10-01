"""EAGLE-200/EAGLE-3 hub that talks HTTPS directly."""

import asyncio
import logging
from time import time

import aioeagle
import xmltodict

from homeassistant.core import HomeAssistant
from homeassistant.helpers import aiohttp_client

_LOGGER = logging.getLogger(__name__)


class EagleHubHttps(aioeagle.EagleHub):
    """EagleHub using HTTPS.

    EAGLE-3 firmware redirects HTTP API calls to an unreachable 192.168.7.1,
    so go straight to HTTPS. The device uses a self-signed certificate.
    """

    async def make_request(self, command_xml: str):
        """Make a request."""
        wait_time = self.next_request - time()
        if wait_time > 0:
            await asyncio.sleep(wait_time)

        url = f"https://{self.host}/cgi-bin/post_manager"
        _LOGGER.debug("Sending to %s: %s", url, command_xml)

        async with self.session.post(
            url,
            headers={"Authorization": self.auth_header, "content-type": "text/xml"},
            data=command_xml,
        ) as response:
            self.next_request = time() + 1

            if response.status == 401:
                raise aioeagle.BadAuth

            text = await response.text()
            return xmltodict.parse(text, dict_constructor=dict)


def create_hub(
    hass: HomeAssistant, cloud_id: str, install_code: str, host: str
) -> EagleHubHttps:
    """Create a hub using a session that accepts the self-signed certificate."""
    return EagleHubHttps(
        aiohttp_client.async_get_clientsession(hass, verify_ssl=False),
        cloud_id,
        install_code,
        host=host,
    )
