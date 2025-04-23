#!/usr/bin/env python3
"""
Mock Camera Data Server - Simulates NavigationalSocketServer for development

This script creates a WebSocket server that broadcasts simulated camera data
at 25 FPS, mimicking the behavior of a camera circling around a scene.
No GPU or Nerfstudio installation required.
"""

import asyncio
import json
import logging
import math
import time
import argparse
from datetime import datetime
import numpy as np
import websockets

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("MockCameraServer")

# Global state
clients = set()
running = False

# Camera animation parameters
RADIUS = 3.0  # Distance from origin
HEIGHT = 1.5   # Camera height
ROTATION_SPEED = 0.2  # Radians per second
OSCILLATION_SPEED = 0.5  # For height variation
OSCILLATION_AMPLITUDE = 0.5  # For height variation
LOOK_AT_CENTER = [0, 0, 0]  # Look at the origin

class SceneData:
    """Simulates scene data like bounds and scale."""
    def __init__(self):
        # Scene bounds as a box around the origin
        self.scene_bounds = [[-2, -2, -2], [2, 2, 2]]
        self.scale_factor = 10.0
    
    def to_dict(self):
        """Convert to dictionary for JSON serialization."""
        return {
            "type": "scene_data",
            "scene_bounds": self.scene_bounds,
            "scale_factor": self.scale_factor
        }

def calculate_camera_matrix(position, look_at, up=[0, 1, 0]):
    """Calculate the camera-to-world matrix for a given position and look_at point."""
    # Convert to numpy arrays
    position = np.array(position, dtype=np.float64)
    look_at = np.array(look_at, dtype=np.float64)
    up = np.array(up, dtype=np.float64)
    
    # Calculate forward (z) direction
    forward = look_at - position
    forward = forward / np.linalg.norm(forward)
    
    # Calculate right (x) direction
    right = np.cross(forward, up)
    right = right / np.linalg.norm(right)
    
    # Recalculate up (y) direction to ensure orthogonality
    up = np.cross(right, forward)
    
    # Build the rotation matrix
    rotation = np.column_stack((right, up, forward))
    
    # Build the 3x4 camera-to-world matrix
    c2w = np.column_stack((rotation, position))
    
    return c2w

async def generate_camera_data():
    """Generate simulated camera data including position, orientation, FOV, etc."""
    start_time = time.time()
    
    while running:
        current_time = time.time()
        elapsed = current_time - start_time
        
        # Calculate circular path position
        angle = elapsed * ROTATION_SPEED
        x = RADIUS * math.cos(angle)
        z = RADIUS * math.sin(angle)
        
        # Add subtle height oscillation
        height_offset = OSCILLATION_AMPLITUDE * math.sin(elapsed * OSCILLATION_SPEED)
        y = HEIGHT + height_offset
        
        position = [x, y, z]
        
        # Calculate camera matrix (position and orientation)
        c2w = calculate_camera_matrix(position, LOOK_AT_CENTER)
        
        # Create camera data message
        message = {
            "type": "camera",
            "position": position,
            "orientation": c2w[:, :3].tolist(),  # First 3 columns = rotation matrix
            "timestamp": current_time,
            "fov": 75.0 * (math.pi / 180.0),  # 75 degrees in radians
            "aspect": 16/9,  # Standard 16:9 aspect ratio
            "look_at": LOOK_AT_CENTER,
            "up_vector": c2w[:, 1].tolist(),  # Second column = up vector
        }
        
        # Broadcast to all clients
        if clients:
            message_json = json.dumps(message)
            websocket_tasks = []
            clients_to_remove = set()
            
            for client in clients:
                try:
                    websocket_tasks.append(asyncio.create_task(client.send(message_json)))
                except websockets.exceptions.ConnectionClosed:
                    clients_to_remove.add(client)
            
            # Remove any disconnected clients
            for client in clients_to_remove:
                if client in clients:
                    clients.remove(client)
            
            if websocket_tasks:
                await asyncio.gather(*websocket_tasks, return_exceptions=True)
        
        # Sleep to maintain 25 FPS
        await asyncio.sleep(1.0 / 25.0)

async def handle_client(websocket, path):
    """Handle WebSocket client connections."""
    client_id = id(websocket)
    client_info = f"{websocket.remote_address[0]}:{websocket.remote_address[1]}"
    logger.info(f"Client connected: {client_info} (ID: {client_id})")
    
    try:
        # Add client to active clients
        clients.add(websocket)
        
        # Send initial scene data
        scene_data = SceneData().to_dict()
        await websocket.send(json.dumps(scene_data))
        logger.info(f"Sent scene data to client {client_id}")
        
        # Process messages from this client
        async for message in websocket:
            try:
                data = json.loads(message)
                
                if "type" not in data:
                    logger.warning(f"Received message without type field: {data}")
                    continue
                
                if data["type"] == "set_pose" and "pose" in data:
                    # Just acknowledge the message - we won't actually set the pose
                    # since we're running a pre-determined animation
                    logger.info(f"Received set_pose command from client {client_id}")
                    logger.info(f"Note: Mock server ignores pose updates and continues animation")
                else:
                    logger.warning(f"Unknown message type: {data['type']}")
                    
            except json.JSONDecodeError:
                logger.error(f"Received invalid JSON from client {client_id}")
            except Exception as e:
                logger.error(f"Error processing message from client {client_id}: {str(e)}")
    
    except websockets.exceptions.ConnectionClosed as e:
        logger.info(f"Client {client_id} connection closed: {e.code} {e.reason}")
    except Exception as e:
        logger.error(f"Error handling client {client_id}: {str(e)}")
    finally:
        # Unregister client on disconnect
        if websocket in clients:
            clients.remove(websocket)
        logger.info(f"Client {client_id} removed, {len(clients)} clients remaining")

async def start_server(host, port):
    """Start the WebSocket server."""
    global running
    running = True
    
    # Start the camera data generator
    camera_task = asyncio.create_task(generate_camera_data())
    
    # Start the WebSocket server
    server = await websockets.serve(handle_client, host, port)
    logger.info(f"Mock camera server running on {host}:{port}")
    
    try:
        # Keep the server running indefinitely
        await asyncio.Future()
    except asyncio.CancelledError:
        # Clean shutdown
        logger.info("Server shutting down...")
    finally:
        # Clean up
        running = False
        camera_task.cancel()
        server.close()
        await server.wait_closed()
        logger.info("Server stopped")

def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Mock Camera Data Server")
    parser.add_argument("--host", default="localhost", help="Server hostname")
    parser.add_argument("--port", type=int, default=7008, help="Server port")
    args = parser.parse_args()
    
    print(f"Starting mock camera server on {args.host}:{args.port}")
    print("Press Ctrl+C to stop")
    
    # Set up event loop
    loop = asyncio.get_event_loop()
    
    try:
        loop.run_until_complete(start_server(args.host, args.port))
    except KeyboardInterrupt:
        print("Shutting down server...")
    finally:
        pending = asyncio.all_tasks(loop)
        for task in pending:
            task.cancel()
        
        # Give tasks a chance to clean up
        loop.run_until_complete(asyncio.sleep(0.1))
        loop.close()
        
        print("Server stopped")

if __name__ == "__main__":
    main()