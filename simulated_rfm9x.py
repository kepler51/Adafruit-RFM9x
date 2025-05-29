'''
Simulated RFM9x LoRa Client
===========================

This module provides a software simulation of the Adafruit RFM9x LoRa radio module,
allowing users to run CircuitPython-style radio communication code without needing
physical LoRa hardware.

Each simulated node connects to a central simulation server via TCP and mimics the
`adafruit_rfm9x.RFM9x` API, supporting basic send/receive operations along with
reliable datagram behavior (ACK/Retry).

Usage Example:
--------------
This client is typically used in conjunction with `./simulated_server.py`.

Run in simulation mode:
    python ./example/simpletest.py --simulate --id=1
'''

import socket
import json
import time
import random
import binascii


class SimulatedRFM9x:
    def __init__(self, server_ip='localhost', server_port=5000, frequency=915.0):
        """
        Initialize the simulated RFM9x module.

        Parameters:
        - node_id (int): Unique identifier for this simulated node.
        - server_ip (str): IP address of the simulation server.
        - server_port (int): Port of the simulation server.
        - location (tuple): (x, y) location in km
        - frequency (int): Frequency at which the node is sending data.
        """
        self.node = 1
        self.location = (0,0)
        self.frequency = frequency
        self.destination = 0XFF
        self.server = (server_ip, server_port)
        
        # Connection state
        self.connected = False
        self.connection_lost = False
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 3
        self.reconnect_delay = 5.0
        
        # Create socket but don't connect yet
        self.sock = None
        
        # Simulated configuration & telemetry
        self.tx_power = 23
        self.last_rssi = -42
        self.last_snr = 0.0
        self.enable_crc = True

        # Packet metadata
        self.sequence_number = 0
        self.flags = 0
        self.identifier = 0

        # Timing
        self.receive_timeout = 0.5
        self.ack_wait = 0.5
        self.ack_delay = None
        self.ack_retries = 5

        self._keep_listening = False

    def _connect(self):
        """Establish connection to the simulation server."""
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.connect(self.server)
            self.sock.settimeout(0.1)
            self.connected = True
            self.connection_lost = False
            self.reconnect_attempts = 0
            return True
        except ConnectionRefusedError:
            return False
        except Exception as e:
            print(f"[SimulatedRFM9x] Connection error: {e}")
            return False

    def _reconnect(self):
        """Attempt to reconnect to the simulation server."""
        if self.reconnect_attempts >= self.max_reconnect_attempts:
            print(f"[SimulatedRFM9x] Maximum reconnection attempts ({self.max_reconnect_attempts}) reached. Giving up.")
            raise ConnectionError("Unable to reconnect to simulation server")
        
        self.reconnect_attempts += 1
        print(f"[SimulatedRFM9x] Lost connection to server. Attempting to reconnect... (attempt {self.reconnect_attempts}/{self.max_reconnect_attempts})")
        
        # Close the old socket
        if self.sock:
            try:
                self.sock.close()
            except:
                pass
        
        # Wait before reconnecting
        print(f"[SimulatedRFM9x] Waiting {self.reconnect_delay} seconds before reconnection attempt...")
        time.sleep(self.reconnect_delay)
        
        # Try to reconnect
        if self._connect():
            print("[SimulatedRFM9x] Successfully reconnected to simulation server!")
            # Re-register with the server
            self.initialize()
            return True
        else:
            print(f"[SimulatedRFM9x] Reconnection attempt {self.reconnect_attempts} failed.")
            return False

    def initialize(self):
        """Must be called after setting node, location, and frequency."""
        if not self.connected:
            if not self._connect():
                raise ConnectionRefusedError("[SimulatedRFM9x] Cannot connect to simulation server. Please ensure simulated_server.py is running.")
        
        msg = {
            "type": "register",
            "node_id": self.node,
            "location": self.location,
            "frequency": self.frequency
        }
        
        try:
            self.sock.sendall((json.dumps(msg) + '\n').encode())
        except (BrokenPipeError, ConnectionResetError, socket.error) as e:
            self.connection_lost = True
            if self._reconnect():
                # Retry registration after reconnection
                self.sock.sendall((json.dumps(msg) + '\n').encode())
            else:
                raise ConnectionError(f"[SimulatedRFM9x] Failed to initialize: {e}")
    
    def _crc16(self, data: bytes) -> int:
        return binascii.crc_hqx(data, 0xFFFF)

    def send(self, data: bytes, *, keep_listening=False, destination=None,
             node=None, identifier=None, flags=None):
        """
        Send a packet of data to the simulation server.

        Parameters:
        - data (bytes): The payload to transmit.
        - keep_listening (bool): If True, receive mode is re-enabled immediately after sending.
        - destination (int): Destination address (default: 0xFF broadcast).
        - node (int): Source address override (default: self.node).
        - identifier (int): Sequence number for reliable datagrams.
        - flags (int): Bit flags (ACK, retry, etc.).
        """
        if not self.connected or self.connection_lost:
            if not self._reconnect():
                raise ConnectionError("[SimulatedRFM9x] Not connected to simulation server")
        
        # Convert data to base64 to safely transmit binary data as JSON
        import base64
        
        if isinstance(data, bytes):
            data_str = base64.b64encode(data).decode('ascii')
            is_binary = True
        else:
            data_str = data
            is_binary = False

        # Build metadata for the RadioHead-style header
        header = {
            "destination": destination if destination is not None else self.destination,
            "node": node if node is not None else self.node,
            "identifier": identifier if identifier is not None else self.identifier,
            "flags": flags if flags is not None else self.flags
        }

        payload = data if isinstance(data, bytes) else data.encode('utf-8')
        crc = self._crc16(payload) if self.enable_crc else None

        msg = {
            "type": "tx",
            "from": self.node,
            "data": data_str,
            "is_binary": is_binary,
            "meta": {
                **header,
                "tx_power": self.tx_power,
                "timestamp": time.time(),
                "crc": crc
            }
        }

        try:
            self.sock.sendall((json.dumps(msg) + '\n').encode())
            self._keep_listening = keep_listening
        except (BrokenPipeError, ConnectionResetError, socket.error) as e:
            self.connection_lost = True
            if self._reconnect():
                # Retry send after reconnection
                self.sock.sendall((json.dumps(msg) + '\n').encode())
                self._keep_listening = keep_listening
            else:
                raise ConnectionError(f"[SimulatedRFM9x] Failed to send: {e}")

    def receive(self, *, keep_listening=True, with_header=False, with_ack=False, timeout=None):
        """
        Receive a packet from the server. If no packet is received in time, returns None.

        Parameters:
        - keep_listening (bool): Keep listen mode active after receiving.
        - with_header (bool): Include the 4-byte RadioHead header in the returned data.
        - with_ack (bool): Automatically send an ACK if requested.
        - timeout (float): Optional timeout override.

        Returns:
        - bytearray or None
        """
        if not self.connected or self.connection_lost:
            if not self._reconnect():
                return None
        
        import base64
        
        timeout = timeout if timeout is not None else self.receive_timeout
        self.sock.settimeout(timeout)

        try:
            raw = self.sock.recv(4096)
            
            # Check if we received empty data (server closed connection)
            if not raw:
                self.connection_lost = True
                print("[SimulatedRFM9x] Server closed connection")
                if self._reconnect():
                    # Retry receive after reconnection
                    return self.receive(keep_listening=keep_listening, with_header=with_header, 
                                      with_ack=with_ack, timeout=timeout)
                else:
                    return None
            
            msg = json.loads(raw.decode())

            # Update telemetry
            self.last_rssi = msg.get("rssi", -90)
            self.last_snr = msg.get("snr", 0.0)

            payload_str = msg.get("data", "")
            is_binary = msg.get("is_binary", False)
            header = msg.get("meta", {})
            received_crc = header.get("crc")

            # Decode the payload
            if is_binary:
                payload_bytes = base64.b64decode(payload_str)
                payload = payload_bytes.decode('utf-8', errors='ignore') if not with_header else payload_bytes
            else:
                payload = payload_str
                payload_bytes = payload.encode('utf-8')

            if self.enable_crc and received_crc is not None:
                computed_crc = self._crc16(payload_bytes)
                if computed_crc != received_crc:
                    print(f"[CRC ERROR] Received: {received_crc}, Computed: {computed_crc}")
                    return None

            # Respond with ACK if requested
            if with_ack and not (header.get("flags", 0) & 0x80) and header.get("destination") != 0xFF:
                self._send_ack(
                    to_node=header["node"],
                    identifier=header["identifier"],
                    original_flags=header["flags"]
                )

            self._keep_listening = keep_listening

            # Return payload with or without header
            if with_header:
                return bytearray([
                    header.get("destination", 0xFF),
                    header.get("node", 0xFF),
                    header.get("identifier", 0),
                    header.get("flags", 0)
                ]) + (payload_bytes if is_binary else bytearray(payload, 'utf-8'))

            if is_binary:
                return bytearray(payload_bytes)
            else:
                return bytearray(payload, 'utf-8')

        except socket.timeout:
            return None
        except json.JSONDecodeError as e:
            # This often happens when server disconnects
            self.connection_lost = True
            if "Expecting value" in str(e):
                print("[SimulatedRFM9x] Server appears to have disconnected")
                if self._reconnect():
                    return None  # Don't retry receive immediately after reconnect
                else:
                    return None
            else:
                print(f"[SimulatedRFM9x] Error parsing server response: {e}")
                return None
        except (ConnectionResetError, BrokenPipeError, socket.error) as e:
            self.connection_lost = True
            print(f"[SimulatedRFM9x] Connection error: {e}")
            if self._reconnect():
                return None
            else:
                return None
        except Exception as e:
            print(f"[SimulatedRFM9x] Unexpected error receiving: {e}")
            return None

    def _send_ack(self, to_node, identifier, original_flags):
        """
        Send an ACK message to the sender node.

        Parameters:
        - to_node (int): Destination node to acknowledge.
        - identifier (int): Packet ID to acknowledge.
        - original_flags (int): Flags from original message.
        """
        ack_msg = {
            "type": "tx",
            "from": self.node,
            "data": "!",
            "meta": {
                "destination": to_node,
                "node": self.node,
                "identifier": identifier,
                "flags": original_flags | 0x80,
                "tx_power": self.tx_power,
                "timestamp": time.time()
            }
        }

        if self.ack_delay:
            time.sleep(self.ack_delay)

        try:
            self.sock.sendall((json.dumps(ack_msg) + '\n').encode())
        except (BrokenPipeError, ConnectionResetError, socket.error):
            # Ignore ACK send failures
            pass

    def send_with_ack(self, data: bytes) -> bool:
        """
        Send a packet and wait for an ACK.

        Parameters:
        - data (bytes): The data to send.

        Returns:
        - bool: True if ACK received, False otherwise.
        """
        self.sequence_number = (self.sequence_number + 1) & 0xFF
        self.identifier = self.sequence_number
        retries = self.ack_retries

        while retries > 0:
            try:
                self.send(data, keep_listening=True, identifier=self.identifier, flags=self.flags)
            except ConnectionError:
                return False

            if self.destination == 0xFF:
                return True

            ack = self.receive(timeout=self.ack_wait, with_header=True)

            if ack and ack[3] & 0x80 and ack[2] == self.identifier:
                return True

            retries -= 1
            time.sleep(self.ack_wait + random.uniform(0, 0.1))

        return False

    def disconnect(self):
        """Gracefully disconnect from the simulation server."""
        if not self.connected:
            return
            
        try:
            # Send disconnect message
            msg = {
                "type": "disconnect",
                "node_id": self.node
            }
            self.sock.sendall((json.dumps(msg) + '\n').encode())
            time.sleep(0.1)
        except:
            pass
        
        # Close the socket
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except:
            pass
        
        try:
            self.sock.close()
        except:
            pass
        
        self.connected = False

    def __del__(self):
        """Destructor to ensure clean disconnect."""
        self.disconnect()

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.disconnect()
        return False