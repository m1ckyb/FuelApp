"""MQTT Client for Home Assistant Integration."""

import json
import logging
from typing import Optional, Dict, Any

import paho.mqtt.client as mqtt

from .config import Config

_LOGGER = logging.getLogger(__name__)


class MQTTClient:
    """MQTT Client wrapper for Home Assistant discovery and state updates."""

    def __init__(self, config: Config):
        """Initialize MQTT client."""
        self.config = config
        self.client: Optional[mqtt.Client] = None
        self.connected = False
        
        if not self.config.mqtt_broker:
            _LOGGER.info("MQTT broker not configured, skipping MQTT initialization")
            return

        self._init_client()

    def _init_client(self):
        """Initialize the Paho MQTT client."""
        try:
            # Generate a unique client ID
            client_id = f"fuelapp_{self.config.mqtt_discovery_prefix}"
            self.client = mqtt.Client(client_id=client_id)
            
            if self.config.mqtt_user and self.config.mqtt_password:
                self.client.username_pw_set(
                    self.config.mqtt_user, 
                    self.config.mqtt_password
                )
            
            self.client.on_connect = self._on_connect
            self.client.on_disconnect = self._on_disconnect
            
            _LOGGER.info(
                "Connecting to MQTT broker %s:%d", 
                self.config.mqtt_broker, 
                self.config.mqtt_port
            )
            
            # Async connection to avoid blocking
            self.client.connect_async(
                self.config.mqtt_broker, 
                self.config.mqtt_port, 
                60
            )
            self.client.loop_start()
            
        except Exception as e:
            _LOGGER.error("Failed to initialize MQTT client: %s", e)

    def _on_connect(self, client, userdata, flags, rc):
        """Handle connection established."""
        if rc == 0:
            _LOGGER.info("Connected to MQTT broker")
            self.connected = True
        else:
            _LOGGER.error("Failed to connect to MQTT broker, return code %d", rc)
            self.connected = False

    def _on_disconnect(self, client, userdata, rc):
        """Handle disconnection."""
        _LOGGER.info("Disconnected from MQTT broker (rc=%d)", rc)
        self.connected = False

    def publish_discovery(self, station_id: int, station_name: str, fuel_types: list[str]):
        """
        Publish Home Assistant discovery messages for a station.
        
        Args:
            station_id: Station ID
            station_name: Station Name
            fuel_types: List of fuel types available at this station
        """
        if not self.client or not self.connected:
            return

        for fuel_type in fuel_types:
            unique_id = f"fuelapp_{station_id}_{fuel_type}"
            discovery_topic = f"{self.config.mqtt_discovery_prefix}/sensor/fuelapp/{unique_id}/config"
            state_topic = f"fuelapp/sensor/{station_id}/{fuel_type}/state"
            
            # Sanitize names for HA
            safe_name = station_name.replace('"', '').replace("'", "")
            
            payload = {
                "name": f"{fuel_type} Price",
                "unique_id": unique_id,
                "state_topic": state_topic,
                "unit_of_measurement": "¢",
                "device_class": "monetary",
                "icon": "mdi:gas-station",
                "device": {
                    "identifiers": [f"fuelapp_{station_id}"],
                    "name": safe_name,
                    "manufacturer": "NSW FuelCheck",
                    "model": "Fuel Station Monitor",
                    "sw_version": "1.0.0"
                }
            }
            
            try:
                self.client.publish(discovery_topic, json.dumps(payload), retain=True)
                _LOGGER.debug("Published discovery for %s", unique_id)
            except Exception as e:
                _LOGGER.error("Failed to publish discovery: %s", e)

    def publish_state(self, station_id: int, fuel_type: str, price: float):
        """
        Publish price state for a station fuel type.
        
        Args:
            station_id: Station ID
            fuel_type: Fuel Type
            price: Current price
        """
        if not self.client or not self.connected:
            return
            
        state_topic = f"fuelapp/sensor/{station_id}/{fuel_type}/state"
        
        try:
            self.client.publish(state_topic, str(price), retain=True)
            _LOGGER.debug("Published state for %s/%s: %.1f", station_id, fuel_type, price)
        except Exception as e:
            _LOGGER.error("Failed to publish state: %s", e)

    def close(self):
        """Stop MQTT client."""
        if self.client:
            self.client.loop_stop()
            self.client.disconnect()

    @staticmethod
    def test_connection(broker: str, port: int, user: str = None, password: str = None) -> tuple[bool, str]:
        """
        Test connection to MQTT broker.
        
        Returns:
            Tuple of (success, message)
        """
        try:
            client = mqtt.Client(client_id="fuelapp_test_connection")
            if user and password:
                client.username_pw_set(user, password)
            
            # Use a mutable list to store result from callback
            result = {'connected': False, 'error': 'Connection timed out'}
            
            def on_connect(client, userdata, flags, rc):
                if rc == 0:
                    result['connected'] = True
                    result['error'] = None
                else:
                    result['connected'] = False
                    result['error'] = f"Connection refused with code {rc}"
            
            client.on_connect = on_connect
            
            client.connect(broker, port, keepalive=10)
            client.loop_start()
            
            # Wait for connection
            import time
            start = time.time()
            while time.time() - start < 5:
                if result['connected'] or (result['error'] != 'Connection timed out' and result['error'] is not None):
                    break
                time.sleep(0.1)
                
            client.loop_stop()
            client.disconnect()
            
            if result['connected']:
                return True, "Successfully connected to broker"
            else:
                return False, result['error']
                
        except Exception as e:
            return False, str(e)
