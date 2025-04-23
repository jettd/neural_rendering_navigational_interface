"""
NavigationalSocketServer module for broadcasting camera data and handling pose updates
via WebSockets for Nerfstudio.
"""

import asyncio
import json
import logging
import threading
import time
from typing import Any, Dict, Optional, Set

import websockets

class NavigationalSocketServer:
    """WebSocket server that broadcasts camera data and handles navigation commands.
    
    Replaces the file-based CameraExporter with a real-time bidirectional
    communication channel for external tools and clients.
    """
    
    def __init__(
        self,
        viewer_state,
        pipeline,
        host: str = "0.0.0.0",
        port: int = 7008,
        fps: float = 20.0,
        log_level: str = "INFO"
    ):
        """Initialize the NavigationalSocketServer.
        
        Args:
            viewer_state: The viewer state object containing camera information
            pipeline: The NeRF pipeline with scene data
            host: Host address to bind the server to
            port: Port number to listen on
            fps: Target frames per second for camera state broadcasts
            log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        """
        self.viewer_state = viewer_state
        self.pipeline = pipeline
        self.host = host
        self.port = port
        self.broadcast_interval = 1.0 / fps
        
        # Configure logging
        numeric_level = getattr(logging, log_level.upper(), None)
        if not isinstance(numeric_level, int):
            raise ValueError(f"Invalid log level: {log_level}")
        
        logging.basicConfig(
            level=numeric_level,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        self.logger = logging.getLogger("NavigationalSocketServer")
        
        # Initialize server state
        self.clients = set()
        self.running = False
        self.server = None
        self.broadcast_task = None
        self.loop = None
        self.thread = None
        
        # Extract scene data
        self.scene_data = self._extract_scene_data()
        
        self.logger.info(f"NavigationalSocketServer initialized on {host}:{port}")
    
    def _extract_scene_data(self) -> Dict[str, Any]:
        """Extract scene data from the pipeline for initial client information.
        
        Returns:
            Dict containing scene bounds and scale factor
        """
        scene_data = {
            "type": "scene_data",
            "scale_factor": 10.0  # VISER_NERFSTUDIO_SCALE_RATIO
        }
        
        # Extract scene bounds if available
        if hasattr(self.pipeline.model, 'scene_box'):
            scene_data["scene_bounds"] = self.pipeline.model.scene_box.aabb.tolist()
            
        self.logger.info(f"Scene data extracted: {json.dumps(scene_data)}")
        return scene_data
    
    async def _broadcast_loop(self):
        """Continuously broadcast camera state to all connected clients."""
        self.logger.info(f"Starting broadcast loop at {1.0/self.broadcast_interval:.1f} FPS")
        
        while self.running:
            try:
                # Skip if no clients are connected
                if not self.clients:
                    await asyncio.sleep(self.broadcast_interval)
                    continue
                
                # Get camera state from viewer
                viser_clients = self.viewer_state.viser_server.get_clients()
                if viser_clients:
                    client = next(iter(viser_clients.values()))
                    camera_state = self.viewer_state.get_camera_state(client)
                    # Print all attributes of camera_state
                    self.logger.info(f"Camera state attributes: {dir(camera_state)}")
                    # Print any specific attributes that look interesting
                    for attr in dir(camera_state):
                        if not attr.startswith('_'):
                            try:
                                value = getattr(camera_state, attr)
                                self.logger.info(f"  {attr}: {value}")
                            except:
                                pass
                if not viser_clients:
                    await asyncio.sleep(self.broadcast_interval)
                    continue

                client = next(iter(viser_clients.values()))
                camera_state = self.viewer_state.get_camera_state(client)

                # Enhanced camera data message with more parameters
                message = {
                    "type": "camera",
                    "position": camera_state.c2w[:3, 3].tolist(),
                    "orientation": camera_state.c2w[:3, :3].tolist(),
                    "timestamp": time.time()
                }

                # Add field of view if available
                if hasattr(camera_state, 'fov'):
                    message["fov"] = camera_state.fov
                elif hasattr(camera_state, 'camera_type') and camera_state.camera_type == 'perspective':
                    message["fov"] = camera_state.fx  # This might be the field of view in some implementations

                # Add near/far clipping planes if available
                if hasattr(camera_state, 'near_plane'):
                    message["near_plane"] = camera_state.near_plane
                if hasattr(camera_state, 'far_plane'):
                    message["far_plane"] = camera_state.far_plane

                # Add aspect ratio if available
                if hasattr(camera_state, 'aspect'):
                    message["aspect"] = camera_state.aspect

                # Calculate look-at point (position + forward direction)
                # The third column of the rotation matrix is the forward direction
                forward_dir = camera_state.c2w[:3, 2]
                position = camera_state.c2w[:3, 3]
                # Look 10 units ahead
                look_at = (position + forward_dir * 10).tolist()
                message["look_at"] = look_at

                # Add up vector (second column of rotation matrix)
                up_vector = camera_state.c2w[:3, 1].tolist()
                message["up_vector"] = up_vector
                
                # Broadcast to all clients
                message_json = json.dumps(message)
                websocket_tasks = []
                clients_to_remove = set()
                
                for client in self.clients:
                    try:
                        # Use create_task for each client to handle them concurrently
                        websocket_tasks.append(asyncio.create_task(client.send(message_json)))
                    except websockets.exceptions.ConnectionClosed:
                        # Mark closed connections for removal
                        clients_to_remove.add(client)
                
                # Remove any disconnected clients
                for client in clients_to_remove:
                    self.clients.remove(client)
                
                if websocket_tasks:
                    # Wait for all send operations to complete
                    await asyncio.gather(*websocket_tasks, return_exceptions=True)
                
                # Sleep to maintain target FPS
                await asyncio.sleep(self.broadcast_interval)
                
            except Exception as e:
                self.logger.error(f"Error in broadcast loop: {str(e)}")
                await asyncio.sleep(1.0)  # Wait longer after errors
    
    async def _handler(self, websocket, path):
        """Handle WebSocket connections and messages."""
        # Register new client
        client_id = id(websocket)
        client_info = f"{websocket.remote_address[0]}:{websocket.remote_address[1]}"
        self.logger.info(f"Client connected: {client_info} (ID: {client_id})")
        
        try:
            # Add to active clients
            self.clients.add(websocket)
            
            # Send initial scene data
            await websocket.send(json.dumps(self.scene_data))
            self.logger.debug(f"Sent scene data to client {client_id}")
            
            # Process messages from this client
            async for message in websocket:
                try:
                    data = json.loads(message)
                    
                    if "type" not in data:
                        self.logger.warning(f"Received message without type field: {data}")
                        continue
                    
                    if data["type"] == "set_pose" and "pose" in data:
                        self.logger.info(f"Received set_pose command from client {client_id}")
                        
                        # Apply the pose update to viewer_state
                        try:
                            if hasattr(self.viewer_state, "set_camera_pose"):
                                self.viewer_state.set_camera_pose(data["pose"])
                            elif hasattr(self.viewer_state, "set_pose"):
                                self.viewer_state.set_pose(data["pose"])
                            else:
                                self.logger.warning("No set_pose or set_camera_pose method found in viewer_state")
                        except Exception as e:
                            self.logger.error(f"Error applying pose update: {str(e)}")
                    else:
                        self.logger.warning(f"Unknown message type: {data['type']}")
                        
                except json.JSONDecodeError:
                    self.logger.error(f"Received invalid JSON from client {client_id}")
                except Exception as e:
                    self.logger.error(f"Error processing message from client {client_id}: {str(e)}")
        
        except websockets.exceptions.ConnectionClosed as e:
            self.logger.info(f"Client {client_id} connection closed: {e.code} {e.reason}")
        except Exception as e:
            self.logger.error(f"Error handling client {client_id}: {str(e)}")
        finally:
            # Unregister client on disconnect
            if websocket in self.clients:
                self.clients.remove(websocket)
            self.logger.info(f"Client {client_id} removed, {len(self.clients)} clients remaining")
    
    def start(self):
        """Start the WebSocket server and broadcast loop."""
        if self.running:
            self.logger.warning("Server is already running")
            return
        
        self.running = True
        
        # Create new event loop in a background thread
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(
            target=self._run_server_thread,
            daemon=True
        )
        self.thread.start()
        
        self.logger.info(f"Server started on {self.host}:{self.port}")
    
    def _run_server_thread(self):
        """Run the server in a background thread."""
        # Set the event loop for this thread
        asyncio.set_event_loop(self.loop)
        
        # Define the server startup coroutine
        async def _start_server():
            # Start the WebSocket server
            self.server = await websockets.serve(
                self._handler,
                self.host,
                self.port
            )
            
            # Start the broadcast loop
            self.broadcast_task = asyncio.create_task(self._broadcast_loop())
            
            # Keep the server running until explicitly stopped
            await asyncio.Future()
        
        try:
            # Run the server until cancelled
            self.loop.run_until_complete(_start_server())
        except asyncio.CancelledError:
            self.logger.info("Server task cancelled")
        finally:
            # Clean up after loop exits
            self.loop.close()
    
    def stop(self):
        """Stop the server and clean up resources."""
        if not self.running:
            self.logger.warning("Server is not running")
            return
        
        self.logger.info("Stopping server...")
        self.running = False
        
        # Stop the event loop
        if self.loop and self.loop.is_running():
            # Schedule server shutdown in the event loop
            async def _shutdown():
                # Cancel the broadcast task
                if self.broadcast_task and not self.broadcast_task.done():
                    self.broadcast_task.cancel()
                
                # Close all client connections
                close_tasks = []
                for client in list(self.clients):
                    close_tasks.append(client.close())
                
                if close_tasks:
                    await asyncio.gather(*close_tasks, return_exceptions=True)
                
                # Close the server
                if self.server:
                    self.server.close()
                    await self.server.wait_closed()
                
                # Create a task to stop the loop
                asyncio.create_task(self._stop_loop())
            
            asyncio.run_coroutine_threadsafe(_shutdown(), self.loop)
            
            # Wait for the thread to finish
            if self.thread and self.thread.is_alive():
                self.thread.join(timeout=5.0)
                if self.thread.is_alive():
                    self.logger.warning("Server thread did not terminate within timeout")
        
        self.logger.info("Server stopped")
    
    async def _stop_loop(self):
        """Stop the event loop."""
        # Get all tasks in the loop and cancel them
        tasks = [task for task in asyncio.all_tasks(self.loop) 
                if task is not asyncio.current_task(self.loop)]
        
        for task in tasks:
            task.cancel()
        
        # Wait for all tasks to be cancelled
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        
        # Stop the loop
        self.loop.stop()