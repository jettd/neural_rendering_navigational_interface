#!/usr/bin/env python3
"""
WebSocket client demo for testing the NavigationalSocketServer

This script connects to a running NavigationalSocketServer instance,
receives camera and scene data, and prints it to the console.
It can also send test pose updates.
"""

import asyncio
import json
import argparse
import signal
import time
from datetime import datetime

import websockets

# Terminal colors for better readability
class Colors:
    BLUE = '\033[94m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BOLD = '\033[1m'
    END = '\033[0m'

async def connect_to_server(uri, send_test_poses=False):
    """Connect to the WebSocket server and process messages."""
    print(f"{Colors.BOLD}Connecting to {uri}...{Colors.END}")
    
    try:
        async with websockets.connect(uri) as websocket:
            print(f"{Colors.GREEN}Connected!{Colors.END}")
            
            # Handle server messages and user input concurrently
            done = asyncio.Future()
            
            # Create tasks for receiving messages and handling user input
            receive_task = asyncio.create_task(
                receive_messages(websocket, done)
            )
            
            # Optionally send test poses
            if send_test_poses:
                pose_task = asyncio.create_task(
                    send_test_poses_periodically(websocket)
                )
            
            # Wait for the receive task to complete (when connection closes)
            await receive_task
            
            # Cancel other tasks if they exist
            if send_test_poses:
                pose_task.cancel()
                
    except ConnectionRefusedError:
        print(f"{Colors.RED}Connection refused. Is the server running?{Colors.END}")
    except websockets.exceptions.InvalidStatusCode as e:
        print(f"{Colors.RED}Failed to connect: {e}{Colors.END}")
    except Exception as e:
        print(f"{Colors.RED}Error: {e}{Colors.END}")

async def receive_messages(websocket, done):
    """Receive and display messages from the server."""
    try:
        async for message in websocket:
            timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            
            try:
                # Parse the JSON message
                data = json.loads(message)
                message_type = data.get("type")
                
                if message_type == "scene_data":
                    print(f"\n{Colors.BOLD}{Colors.BLUE}Scene Data Received:{Colors.END}")
                    # Pretty print scene data
                    for key, value in data.items():
                        if key != "type":
                            print(f"  {Colors.BLUE}{key}:{Colors.END} {value}")
                
                elif message_type == "camera":
                    # Format timestamp
                    msg_time = data.get("timestamp", 0)
                    latency = (time.time() - msg_time) * 1000  # milliseconds
                    
                    # Print camera data
                    position = data.get("position", [0, 0, 0])
                    position_str = ", ".join(f"{p:.2f}" for p in position)
                    
                    # Basic camera info
                    print(f"[{timestamp}] Camera: pos=[{position_str}] (latency: {latency:.1f}ms)")
                    
                    # Additional camera parameters if available
                    if "fov" in data:
                        print(f"  FOV: {data['fov']:.2f} degrees")
                    
                    if "look_at" in data:
                        look_at = data.get("look_at")
                        look_at_str = ", ".join(f"{p:.2f}" for p in look_at)
                        print(f"  Looking at: [{look_at_str}]")
                    
                    if "up_vector" in data:
                        up = data.get("up_vector")
                        up_str = ", ".join(f"{p:.2f}" for p in up)
                        print(f"  Up vector: [{up_str}]")
                    
                    if "near_plane" in data and "far_plane" in data:
                        print(f"  Clipping planes: near={data['near_plane']:.2f}, far={data['far_plane']:.2f}")
                    
                    if "aspect" in data:
                        print(f"  Aspect ratio: {data['aspect']:.2f}")
                
                else:
                    print(f"\n{Colors.BOLD}Unknown message type:{Colors.END} {message_type}")
                    print(json.dumps(data, indent=2))
            
            except json.JSONDecodeError:
                print(f"\n{Colors.RED}Invalid JSON message:{Colors.END} {message}")
    
    except websockets.exceptions.ConnectionClosed as e:
        print(f"\n{Colors.RED}Connection closed: {e.code} {e.reason}{Colors.END}")
    except Exception as e:
        print(f"\n{Colors.RED}Error: {e}{Colors.END}")
    finally:
        # Signal that we're done
        if not done.done():
            done.set_result(None)

async def send_test_poses_periodically(websocket):
    """Send test camera pose updates periodically."""
    print(f"{Colors.GREEN}Will send test pose updates every 5 seconds...{Colors.END}")
    
    # Simple circular motion
    import math
    try:
        i = 0
        while True:
            await asyncio.sleep(5)  # Send every 5 seconds
            
            # Calculate position on a circle
            angle = i * 0.1
            x = 5 * math.cos(angle)
            z = 5 * math.sin(angle)
            y = 0.5  # Fixed height
            
            # Simple identity rotation matrix
            rotation = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
            
            # Create a test pose message
            pose_msg = {
                "type": "set_pose",
                "pose": [
                    [rotation[0][0], rotation[0][1], rotation[0][2], x],
                    [rotation[1][0], rotation[1][1], rotation[1][2], y],
                    [rotation[2][0], rotation[2][1], rotation[2][2], z],
                    [0, 0, 0, 1]
                ]
            }
            
            # Send the pose update
            await websocket.send(json.dumps(pose_msg))
            print(f"\n{Colors.GREEN}Sent test pose: [{x:.2f}, {y:.2f}, {z:.2f}]{Colors.END}")
            
            i += 1
    
    except asyncio.CancelledError:
        # Task was cancelled, exit gracefully
        pass
    except Exception as e:
        print(f"{Colors.RED}Error sending test pose: {e}{Colors.END}")

def main():
    parser = argparse.ArgumentParser(description="WebSocket client for NavigationalSocketServer")
    parser.add_argument("--host", default="localhost", help="Server hostname")
    parser.add_argument("--port", type=int, default=7007, help="Server port")
    parser.add_argument("--send-poses", action="store_true", help="Send test pose updates")
    args = parser.parse_args()
    
    uri = f"ws://{args.host}:{args.port}"
    
    # Set up clean shutdown on Ctrl+C
    loop = asyncio.get_event_loop()
    
    def signal_handler():
        print(f"\n{Colors.BOLD}Shutting down...{Colors.END}")
        for task in asyncio.all_tasks(loop):
            task.cancel()
    
    # Register signal handlers
    loop.add_signal_handler(signal.SIGINT, signal_handler)
    loop.add_signal_handler(signal.SIGTERM, signal_handler)
    
    try:
        loop.run_until_complete(connect_to_server(uri, args.send_poses))
    except asyncio.CancelledError:
        # This is expected during shutdown
        pass
    finally:
        loop.close()
        print(f"{Colors.BOLD}Client stopped.{Colors.END}")

if __name__ == "__main__":
    main()