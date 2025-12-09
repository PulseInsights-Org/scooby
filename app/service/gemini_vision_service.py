import os
import base64
import logging
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
import google.generativeai as genai
from app.core.config import get_config

logger = logging.getLogger(__name__)


class ScreenContent(BaseModel):
    """Structured output for screenshare analysis"""
    content_type: str = Field(description="Type of content: code, presentation, browser, terminal, diagram, document, etc.")
    primary_content: str = Field(description="Main description of what's visible on screen")
    text_detected: Optional[str] = Field(default=None, description="Any visible text, code, or labels")
    key_elements: List[str] = Field(default_factory=list, description="Notable items, UI elements, or features visible")
    technical_context: Optional[str] = Field(default=None, description="Programming language, tools, frameworks, or technical details")
    confidence: float = Field(default=0.0, description="Confidence score from 0.0 to 1.0")


class GeminiVisionService:
    """Service for analyzing screenshare frames using Google Gemini Vision API"""

    def __init__(self):
        self.config = get_config()
        
        # Configure Gemini API
        if self.config.gemini_api_key:
            genai.configure(api_key=self.config.gemini_api_key)
            self.model = genai.GenerativeModel(self.config.vision_model)
            self.enabled = self.config.vision_enabled
            logger.info(f"Initialized GeminiVisionService with model: {self.config.vision_model}")
        else:
            self.model = None
            self.enabled = False
            logger.warning("GeminiVisionService disabled: GEMINI_API_KEY not configured")

    def _prepare_image_parts(self, frames: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Convert base64 frames to Gemini image parts"""
        image_parts = []
        
        for frame in frames:
            image_b64 = frame.get("image_base64")
            if not image_b64:
                continue
            
            try:
                # Gemini expects image data as bytes
                image_bytes = base64.b64decode(image_b64)
                
                # Create image part for Gemini
                image_parts.append({
                    "mime_type": "image/png",
                    "data": image_bytes
                })
            except Exception as e:
                logger.warning(f"Failed to prepare image part: {e}")
                continue
        
        return image_parts

    def _build_analysis_prompt(self, context: Optional[str] = None) -> str:
        """Build the prompt for Gemini vision analysis"""
        
        base_prompt = """Analyze the screenshare image(s) and provide a detailed description.

Focus on:
1. **Content Type**: Identify what type of content is being shown (code editor, presentation, browser, terminal, diagram, document, etc.)
2. **Primary Content**: Describe the main content visible on screen
3. **Text Detection**: Extract any visible text, code snippets, or important labels
4. **Key Elements**: List notable UI elements, buttons, sections, or features
5. **Technical Context**: If code or technical content is visible, identify the programming language, framework, tools, or technologies

Provide your analysis in a structured format:

Content Type: [type]
Primary Content: [description]
Text Detected: [any visible text or code]
Key Elements:
- [element 1]
- [element 2]
- [element 3]
Technical Context: [language/tools/frameworks if applicable]
Confidence: [0.0 to 1.0]"""

        if context:
            base_prompt += f"\n\nAdditional Context: {context}"
        
        return base_prompt

    def _parse_gemini_response(self, response_text: str) -> ScreenContent:
        """Parse Gemini's text response into structured ScreenContent"""
        
        # Initialize default values
        content_type = "unknown"
        primary_content = ""
        text_detected = None
        key_elements = []
        technical_context = None
        confidence = 0.7  # Default confidence
        
        try:
            lines = response_text.strip().split('\n')
            current_section = None
            
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                
                # Parse structured sections
                if line.startswith("Content Type:"):
                    content_type = line.replace("Content Type:", "").strip()
                elif line.startswith("Primary Content:"):
                    primary_content = line.replace("Primary Content:", "").strip()
                elif line.startswith("Text Detected:"):
                    text_detected = line.replace("Text Detected:", "").strip()
                    if text_detected.lower() in ["none", "n/a", ""]:
                        text_detected = None
                elif line.startswith("Key Elements:"):
                    current_section = "key_elements"
                elif line.startswith("Technical Context:"):
                    technical_context = line.replace("Technical Context:", "").strip()
                    if technical_context.lower() in ["none", "n/a", ""]:
                        technical_context = None
                    current_section = None
                elif line.startswith("Confidence:"):
                    conf_str = line.replace("Confidence:", "").strip()
                    try:
                        confidence = float(conf_str)
                    except ValueError:
                        confidence = 0.7
                    current_section = None
                elif current_section == "key_elements" and line.startswith("-"):
                    element = line.lstrip("- ").strip()
                    if element:
                        key_elements.append(element)
            
            # If parsing failed to extract primary content, use the whole response
            if not primary_content:
                primary_content = response_text[:500]  # Limit length
            
        except Exception as e:
            logger.error(f"Error parsing Gemini response: {e}")
            primary_content = response_text[:500]
        
        return ScreenContent(
            content_type=content_type,
            primary_content=primary_content,
            text_detected=text_detected,
            key_elements=key_elements,
            technical_context=technical_context,
            confidence=confidence
        )

    async def analyze_frames(
        self,
        frames: List[Dict[str, Any]],
        context: Optional[str] = None,
        max_frames: Optional[int] = None
    ) -> ScreenContent:
        """
        Analyze screenshare frames using Gemini Vision
        
        Args:
            frames: List of frame dicts with image_base64 field
            context: Optional context about the meeting or discussion
            max_frames: Maximum number of frames to analyze (default from config)
        
        Returns:
            ScreenContent with structured analysis
        """
        
        if not self.enabled or not self.model:
            logger.warning("Vision analysis disabled or not configured")
            return ScreenContent(
                content_type="unavailable",
                primary_content="Vision analysis is not enabled or configured.",
                confidence=0.0
            )
        
        if not frames:
            logger.warning("No frames provided for analysis")
            return ScreenContent(
                content_type="no_data",
                primary_content="No screenshare frames available for analysis.",
                confidence=0.0
            )
        
        # Limit number of frames
        max_frames = max_frames or self.config.vision_max_images_per_request
        frames_to_analyze = frames[:max_frames]
        
        logger.info(f"Analyzing {len(frames_to_analyze)} screenshare frames with Gemini Vision")
        
        try:
            # Prepare image parts
            image_parts = self._prepare_image_parts(frames_to_analyze)
            
            if not image_parts:
                logger.warning("No valid images could be prepared from frames")
                return ScreenContent(
                    content_type="error",
                    primary_content="Failed to prepare images for analysis.",
                    confidence=0.0
                )
            
            # Build prompt
            prompt = self._build_analysis_prompt(context)
            
            # Create content list with prompt and images
            content = [prompt] + image_parts
            
            # Generate response from Gemini
            logger.debug(f"Sending {len(image_parts)} images to Gemini for analysis")
            response = self.model.generate_content(
                content,
                generation_config=genai.types.GenerationConfig(
                    max_output_tokens=self.config.vision_max_tokens,
                    temperature=self.config.vision_temperature,
                )
            )
            
            # Parse response
            response_text = response.text
            logger.debug(f"Gemini response: {response_text[:200]}...")
            
            result = self._parse_gemini_response(response_text)
            
            logger.info(
                f"Vision analysis complete: type={result.content_type}, "
                f"confidence={result.confidence:.2f}"
            )
            
            return result
            
        except Exception as e:
            logger.exception(f"Error during Gemini vision analysis: {e}")
            return ScreenContent(
                content_type="error",
                primary_content=f"Vision analysis failed: {str(e)}",
                confidence=0.0
            )

    def format_for_slack(self, analysis: ScreenContent, frame_count: int, time_range: str) -> str:
        """Format analysis result for Slack message"""
        
        lines = [
            f"📊 **Screenshare Analysis** ({frame_count} frames analyzed)",
            "",
            f"🎯 **Content Type:** {analysis.content_type.title()}",
            "",
            f"📝 **What's Visible:**",
            analysis.primary_content,
        ]
        
        if analysis.text_detected:
            lines.extend([
                "",
                f"💬 **Text Detected:**",
                f"```{analysis.text_detected[:500]}```"
            ])
        
        if analysis.technical_context:
            lines.extend([
                "",
                f"💡 **Technical Context:**",
                analysis.technical_context
            ])
        
        if analysis.key_elements:
            lines.extend([
                "",
                f"🔍 **Key Elements:**"
            ])
            for element in analysis.key_elements[:5]:  # Limit to 5
                lines.append(f"• {element}")
        
        lines.extend([
            "",
            f"⏱️ **Time Range:** {time_range}",
            f"✅ **Confidence:** {analysis.confidence:.0%}"
        ])
        
        return "\n".join(lines)
