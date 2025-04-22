from nerfstudio.viewer.server.viewer_state import ViewerState

class CustomViewerState(ViewerState):
    """Custom viewer implementation that extends the default viewer"""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        print("Custom viewer initialized!")
        
    # Override methods you want to customize
    def init_scene(self, *args, **kwargs):
        result = super().init_scene(*args, **kwargs)
        print("Custom scene initialization")
        return result