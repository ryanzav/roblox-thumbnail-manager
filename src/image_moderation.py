"""Content moderation for generated images.

Detects content that might be rejected by Roblox and handles image validation
before they're added to the queue or activated.
"""

import json
import logging

from .config import Config

log = logging.getLogger(__name__)

# Safety categories that Roblox typically flags
UNSAFE_CATEGORIES = {
    "VIOLENCE",
    "SEXUAL",
    "HARASSMENT",
    "HATE_SPEECH",
    "DANGEROUS_GOODS",
    "MEDICAL",
    "SPAM",
}


class ModerationError(Exception):
    """Raised when content moderation fails."""
    pass


def check_image_safety(cfg: Config, image_bytes: bytes) -> dict:
    """Check an image for potentially unsafe content using Gemini Vision.
    
    Returns a dict with:
    - safe: bool indicating if the image passes moderation
    - reason: str explaining why it failed (or "safe" if it passes)
    - categories: list of flagged safety categories
    """
    if not cfg.ai_image_api_key:
        raise ModerationError("AI_IMAGE_API_KEY is not set")
    
    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:
        raise ModerationError("google-genai is not installed") from exc
    
    try:
        client = genai.Client(api_key=cfg.ai_image_api_key)
        
        # Use Gemini to analyze the image for safety
        prompt = """Analyze this image for content that might violate Roblox's content policy. 
        
Check for:
- Violence or graphic content
- Sexual or adult content
- Hate speech or harassment
- Dangerous activities or items
- Medical/gore content
- Spam or low-quality content

Respond with ONLY a JSON object in this exact format (no markdown, no extra text):
{
  "safe": true/false,
  "categories": ["CATEGORY1", "CATEGORY2"],
  "reasoning": "Brief explanation"
}

If safe, return empty categories list."""
        
        response = client.models.generate_content(
            model="gemini-3.6-flash",
            contents=[
                prompt,
                types.Part(inline_data=types.Blob(mime_type="image/png", data=image_bytes))
            ]
        )
        
        # Parse the response
        text = response.text.strip()
        
        # Remove markdown code blocks if present
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()
        
        result = json.loads(text)
        
        is_safe = result.get("safe", True)
        categories = result.get("categories", [])
        reasoning = result.get("reasoning", "")
        
        return {
            "safe": is_safe,
            "reason": reasoning if not is_safe else "safe",
            "categories": categories,
        }
    
    except ModerationError:
        raise
    except json.JSONDecodeError as exc:
        raise ModerationError(f"Could not parse moderation response: {exc}") from exc
    except Exception as exc:
        raise ModerationError(
            f"Moderation check failed: {type(exc).__name__}: {exc}") from exc
