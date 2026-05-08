import base64
import io
from typing import Any, Optional

from PIL import Image

from .base import BaseResponse


class ChartResponse(BaseResponse):
    def __init__(self, value: Any = None, last_code_executed: Optional[str] = None):
        super().__init__(value, "plot", last_code_executed)  # Issue 11: Use "plot" to match LLM output type and template

    def _get_image(self) -> Image.Image:
        # Handle dict values (e.g., {"path": "...", "base64": "..."})
        value = self.value
        if isinstance(value, dict):
            # Try to extract image data from dict
            if "base64" in value:
                image_data = base64.b64decode(value["base64"])
                return Image.open(io.BytesIO(image_data))
            if "path" in value:
                return Image.open(value["path"])
            raise ValueError(f"Cannot extract image from dict value: {list(value.keys())}")

        if not value.startswith("data:image"):
            return Image.open(value)

        base64_data = value.split(",")[1]
        image_data = base64.b64decode(base64_data)
        return Image.open(io.BytesIO(image_data))

    def save(self, path: str):
        img = self._get_image()
        img.save(path)

    def show(self):
        img = self._get_image()
        img.show()

    def __str__(self) -> str:
        if isinstance(self.value, dict):
            return str(self.value)
        return self.value

    def get_base64_image(self) -> str:
        img = self._get_image()
        img_byte_arr = io.BytesIO()
        img.save(img_byte_arr, format="PNG")
        img_byte_arr = img_byte_arr.getvalue()
        return base64.b64encode(img_byte_arr).decode("utf-8")
